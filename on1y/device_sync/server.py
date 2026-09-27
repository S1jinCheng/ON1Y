"""Small single-library relay. Run separately; never expose the desktop API."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import ValidationError

from on1y.device_sync.protocol import (
    MAX_BODY,
    PROTOCOL_VERSION,
    Operation,
    encode,
    record_key,
)


class Relay:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conflicts (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)
            conn.execute("INSERT OR IGNORE INTO metadata VALUES ('library_id', ?)", (str(uuid4()),))
            self.library_id = conn.execute(
                "SELECT value FROM metadata WHERE key='library_id'"
            ).fetchone()[0]

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def push(self, operations: list[Operation]) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for op in operations:
                serialized = encode(op.model_dump())
                previous = conn.execute(
                    "SELECT data FROM operations WHERE id=?", (op.op_id,)
                ).fetchone()
                if previous:
                    if previous[0] != serialized:
                        raise ValueError("operation id reused with different content")
                    continue
                key = record_key(op.kind, op.identity)
                row = conn.execute("SELECT data FROM records WHERE key=?", (key,)).fetchone()
                record = (
                    json.loads(row[0])
                    if row
                    else {
                        "key": key,
                        "kind": op.kind,
                        "identity": op.identity,
                        "fields": {},
                        "versions": {},
                    }
                )
                # Event sequence is the authoritative clock, never a device timestamp.
                seq = conn.execute("INSERT INTO events(data) VALUES ('{}')").lastrowid
                conflicts = []
                for field, incoming in op.patch.items():
                    current = record["fields"].get(field)
                    revision = record["versions"].get(field, 0)
                    if op.base[field] != revision and incoming != current:
                        conflict = {
                            "id": str(uuid4()),
                            "key": key,
                            "kind": op.kind,
                            "identity": op.identity,
                            "field": field,
                            "current": current,
                            "incoming": incoming,
                            "device_id": op.device_id,
                            "revision": revision,
                            "resolved": False,
                        }
                        conflicts.append(conflict)
                        conn.execute(
                            "INSERT INTO conflicts VALUES (?,?)", (conflict["id"], encode(conflict))
                        )
                    elif incoming != current or field not in record["fields"]:
                        record["fields"][field] = incoming
                        record["versions"][field] = seq
                conn.execute("INSERT OR REPLACE INTO records VALUES (?,?)", (key, encode(record)))
                event = {"op_id": op.op_id, "record": record, "conflicts": conflicts}
                conn.execute("UPDATE events SET data=? WHERE seq=?", (encode(event), seq))
                conn.execute("INSERT INTO operations VALUES (?,?)", (op.op_id, serialized))

    def verify_checkpoint(self, cursor: int, checkpoint: str) -> None:
        if cursor == 0:
            return
        with self.connect() as conn:
            row = conn.execute("SELECT data FROM events WHERE seq=?", (cursor,)).fetchone()
            if not row or hashlib.sha256(row[0].encode()).hexdigest() != checkpoint:
                raise ValueError("server history changed; restore the original relay database")

    def pull(self, cursor: int) -> dict[str, Any]:
        with self.connect() as conn:
            maximum = conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            if cursor > maximum:
                raise ValueError("server history was rolled back; restore the relay backup")
            rows = conn.execute(
                "SELECT seq,data FROM events WHERE seq>? ORDER BY seq LIMIT 100", (cursor,)
            ).fetchall()
            events, size = [], 0
            for seq, raw in rows:
                if events and size + len(raw.encode()) > MAX_BODY:
                    break
                size += len(raw.encode())
                events.append(
                    {
                        "seq": seq,
                        "hash": hashlib.sha256(raw.encode()).hexdigest(),
                        **json.loads(raw),
                    }
                )
            end = events[-1]["seq"] if events else cursor
            return {"library_id": self.library_id, "events": events, "more": end < maximum}

    def resolve(self, conflict_id: str, choice: str) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT data FROM conflicts WHERE id=?", (conflict_id,)).fetchone()
            if not row:
                raise ValueError("conflict not found")
            conflict = json.loads(row[0])
            if conflict["resolved"]:
                return
            record = json.loads(
                conn.execute("SELECT data FROM records WHERE key=?", (conflict["key"],)).fetchone()[
                    0
                ]
            )
            field = conflict["field"]
            if choice == "incoming" and record["versions"].get(field, 0) != conflict["revision"]:
                raise ValueError(
                    "field changed again; keep current and manually merge the saved copy"
                )
            seq = conn.execute("INSERT INTO events(data) VALUES ('{}')").lastrowid
            if choice == "incoming":
                record["fields"][field] = conflict["incoming"]
                record["versions"][field] = seq
                conn.execute(
                    "UPDATE records SET data=? WHERE key=?", (encode(record), record["key"])
                )
            conflict["resolved"] = True
            conn.execute("UPDATE conflicts SET data=? WHERE id=?", (encode(conflict), conflict_id))
            conn.execute(
                "UPDATE events SET data=? WHERE seq=?",
                (
                    encode(
                        {
                            "op_id": f"resolve:{conflict_id}",
                            "record": record,
                            "conflicts": [conflict],
                        }
                    ),
                    seq,
                ),
            )


async def read_body(request: Request) -> Any:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise HTTPException(413, "sync request too large")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "invalid JSON") from exc


def create_sync_app(db_path: Path, token: str) -> FastAPI:
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("sync key must contain at least 32 ASCII characters without spaces")
    relay = Relay(db_path)

    def authorize(
        request: Request,
        authorization: str = Header(default=""),
        x_on1y_library: str = Header(default=""),
    ) -> None:
        if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "invalid pairing key")
        if request.url.path != "/v1/info" and x_on1y_library != relay.library_id:
            raise HTTPException(409, "library identity mismatch; handshake required")

    app = FastAPI(
        title="On1y personal sync",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(authorize)],
    )

    @app.get("/v1/info")
    def info(cursor: int = 0, checkpoint: str = "") -> dict[str, Any]:
        try:
            relay.verify_checkpoint(cursor, checkpoint)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"protocol": PROTOCOL_VERSION, "library_id": relay.library_id}

    @app.post("/v1/push")
    async def push(request: Request) -> dict[str, bool]:
        body = await read_body(request)
        try:
            if not isinstance(body, list) or not 1 <= len(body) <= 50:
                raise ValueError("expected 1 to 50 operations")
            relay.push([Operation.model_validate(item) for item in body])
        except (ValueError, ValidationError) as exc:
            raise HTTPException(400, "invalid sync operations") from exc
        return {"ok": True}

    @app.get("/v1/pull")
    def pull(cursor: int = 0) -> dict[str, Any]:
        if cursor < 0:
            raise HTTPException(400, "invalid cursor")
        try:
            return relay.pull(cursor)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/v1/conflicts/{conflict_id}/resolve")
    async def resolve(conflict_id: str, request: Request) -> dict[str, bool]:
        body = await read_body(request)
        choice = body.get("choice") if isinstance(body, dict) else None
        if choice not in {"current", "incoming"}:
            raise HTTPException(400, "invalid conflict choice")
        try:
            relay.resolve(conflict_id, choice)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True}

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Single-library On1y sync relay")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    token = os.environ.get("ON1Y_DEVICE_SYNC_KEY", "")
    if len(token) < 32:
        parser.error("set ON1Y_DEVICE_SYNC_KEY to a random key of at least 32 characters")
    uvicorn.run(create_sync_app(args.db, token), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
