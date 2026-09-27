"""Durable snapshot-diff outbox and three-way, field-level replication.

Local application writes are already durable in SQLite. A transactional snapshot
finds their net changes, including writes made by importers or background jobs.
The outbox is immutable until its own relay event is applied. Remote data, shadow,
conflict copies, acknowledgement and cursor commit in one SQLite transaction.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.device_sync.library import now, snapshot, write_record
from on1y.device_sync.protocol import MAX_BODY, PROTOCOL_VERSION, Operation, encode

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def sync_lock(path: Path) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(str(path.resolve()), threading.RLock())


def validate_url(url: str) -> str:
    url = url.strip().rstrip("/")
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请输入不含账号、查询参数的同步服务地址")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("远程同步必须使用 HTTPS；HTTP 仅允许本机或 SSH 隧道")
    return url


class DeviceSync:
    def __init__(self, storage: SqliteStorage):
        self.storage = storage
        self.conn = storage._connect()
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS device_sync_config (
                id INTEGER PRIMARY KEY CHECK(id=1), user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL, server_url TEXT NOT NULL DEFAULT '',
                token TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 0,
                library_id TEXT NOT NULL DEFAULT '', cursor INTEGER NOT NULL DEFAULT 0,
                cursor_hash TEXT NOT NULL DEFAULT '',
                last_sync TEXT, last_error TEXT);
            CREATE TABLE IF NOT EXISTS device_sync_shadow (
                key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device_sync_outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                op_id TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device_sync_conflicts (
                id TEXT PRIMARY KEY, data TEXT NOT NULL);
        """)
        # Keep the opt-in schema additive for development databases made before checkpoints.
        if "cursor_hash" not in {
            row[1] for row in self.conn.execute("PRAGMA table_info(device_sync_config)")
        }:
            with self.conn:
                self.conn.execute(
                    "ALTER TABLE device_sync_config ADD COLUMN cursor_hash TEXT NOT NULL DEFAULT ''"
                )

    def config(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM device_sync_config WHERE id=1").fetchone()
        return dict(row) if row else None

    def check_owner(self, user_id: int) -> None:
        config = self.config()
        if config and config["user_id"] != user_id:
            raise ValueError("此设备的同步已绑定另一个本地账号，请切换回原账号")

    def configure(self, user_id: int, server_url: str, token: str, enabled: bool) -> None:
        self.check_owner(user_id)
        if not self.conn.execute(
            "SELECT 1 FROM users WHERE id=? AND is_active=1", (user_id,)
        ).fetchone():
            raise ValueError("请先登录一个有效的本地账号")
        old = self.config() or {}
        # A blank password input retains the stored key, but it is never sent to the UI.
        token = token.strip() or old.get("token", "")
        if enabled or server_url:
            server_url = validate_url(server_url)
        if enabled and (len(token) < 32 or not token.isascii() or any(c.isspace() for c in token)):
            raise ValueError("配对密钥至少需要 32 个 ASCII 字符，且不能包含空白")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO device_sync_config(id,user_id,device_id,server_url,token,enabled)
                VALUES (1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    server_url=excluded.server_url,token=excluded.token,enabled=excluded.enabled,
                    last_error=NULL
            """,
                (user_id, old.get("device_id") or str(uuid4()), server_url, token, int(enabled)),
            )

    def status(self, user_id: int) -> dict[str, Any]:
        self.check_owner(user_id)
        config = self.config() or {}
        conflicts = [
            json.loads(row[0])
            for row in self.conn.execute("SELECT data FROM device_sync_conflicts ORDER BY rowid")
        ]
        return {
            "enabled": bool(config.get("enabled")),
            "server_url": config.get("server_url", ""),
            "has_key": bool(config.get("token")),
            "device_id": config.get("device_id", ""),
            "library_id": config.get("library_id", ""),
            "last_sync": config.get("last_sync"),
            "last_error": config.get("last_error"),
            "cursor": config.get("cursor", 0),
            "pending": self.conn.execute("SELECT COUNT(*) FROM device_sync_outbox").fetchone()[0],
            "conflicts": [c for c in conflicts if not c["resolved"]],
        }

    def capture(self, user_id: int, device_id: str) -> None:
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            # Do not generate a second operation using stale base revisions.
            if self.conn.execute("SELECT 1 FROM device_sync_outbox LIMIT 1").fetchone():
                return
            local = snapshot(self.conn, user_id)
            shadows = {
                row[0]: json.loads(row[1])
                for row in self.conn.execute("SELECT key,data FROM device_sync_shadow")
            }
            for key, shadow in shadows.items():
                if key not in local:
                    local[key] = {**shadow, "fields": {**shadow["fields"], "_deleted": True}}
            for key, record in local.items():
                shadow = shadows.get(key, {"fields": {}, "versions": {}})
                fields, previous = record["fields"], shadow["fields"]
                patch = {
                    f: fields.get(f)
                    for f in sorted(set(fields) | set(previous))
                    if fields.get(f) != previous.get(f)
                }
                if not patch:
                    continue
                op = Operation(
                    op_id=str(uuid4()),
                    device_id=device_id,
                    kind=record["kind"],
                    identity=record["identity"],
                    patch=patch,
                    base={f: shadow["versions"].get(f, 0) for f in patch},
                )
                data = encode(op.model_dump())
                if len(data.encode()) > MAX_BODY // 2:
                    raise ValueError("单条内容过大，暂无法同步，请缩小正文或笔记后重试")
                self.conn.execute(
                    "INSERT INTO device_sync_outbox(op_id,data) VALUES (?,?)", (op.op_id, data)
                )

    def apply(self, events: list[dict[str, Any]], user_id: int) -> None:
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            local = snapshot(self.conn, user_id)
            for event in events:
                config = self.config()
                assert config is not None
                if event["seq"] <= config["cursor"]:
                    continue
                if event["seq"] != config["cursor"] + 1:
                    raise ValueError("同步事件不连续，已停止以保护本地数据")
                payload = {name: event[name] for name in ("op_id", "record", "conflicts")}
                digest = hashlib.sha256(encode(payload).encode()).hexdigest()
                if event.get("hash") != digest:
                    raise ValueError("同步内容校验失败，已停止以保护本地数据")
                remote = event["record"]
                key = remote["key"]
                row = self.conn.execute(
                    "SELECT data FROM device_sync_shadow WHERE key=?", (key,)
                ).fetchone()
                shadow = json.loads(row[0]) if row else {"fields": {}, "versions": {}}
                current = local.get(key)
                current_fields = (
                    current["fields"]
                    if current
                    else ({**shadow["fields"], "_deleted": True} if row else {})
                )
                queued = self.conn.execute(
                    "SELECT data FROM device_sync_outbox WHERE op_id=?", (event["op_id"],)
                ).fetchone()
                sent = json.loads(queued[0])["patch"] if queued else {}
                merged = dict(current_fields)
                for field, value in remote["fields"].items():
                    # Preserve edits committed while HTTP was in flight. Our own event
                    # may replace the attempted value only if the user hasn't edited it again.
                    if current_fields.get(field) == shadow["fields"].get(field) or (
                        field in sent and current_fields.get(field) == sent[field]
                    ):
                        merged[field] = value
                combined = {**remote, "fields": merged}
                if merged != current_fields or (current is None and not merged.get("_deleted")):
                    write_record(self.conn, user_id, combined)
                local[key] = combined
                self.conn.execute(
                    "INSERT OR REPLACE INTO device_sync_shadow VALUES (?,?)", (key, encode(remote))
                )
                for conflict in event["conflicts"]:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO device_sync_conflicts VALUES (?,?)",
                        (conflict["id"], encode(conflict)),
                    )
                self.conn.execute("DELETE FROM device_sync_outbox WHERE op_id=?", (event["op_id"],))
                self.conn.execute(
                    "UPDATE device_sync_config SET cursor=?,cursor_hash=? WHERE id=1",
                    (event["seq"], digest),
                )

    def handshake(self, client: Any) -> None:
        config = self.config()
        assert config is not None
        # Pin identity before validating the checkpoint, so a replacement library
        # produces a useful identity error even when it has an empty event log.
        response = client.get("/v1/info")
        response.raise_for_status()
        info = response.json()
        if info.get("protocol") != PROTOCOL_VERSION or not info.get("library_id"):
            raise ValueError("同步协议不兼容")
        if config["library_id"] and config["library_id"] != info["library_id"]:
            raise ValueError("同步资料库已改变，已停止上传；请恢复原服务及其数据库")
        if config["cursor"]:
            response = client.get(
                "/v1/info", params={"cursor": config["cursor"], "checkpoint": config["cursor_hash"]}
            )
            response.raise_for_status()
        with self.conn:
            self.conn.execute(
                "UPDATE device_sync_config SET library_id=? WHERE id=1", (info["library_id"],)
            )
        client.headers["X-On1y-Library"] = info["library_id"]

    def sync(self, client: Any, *, user_id: int) -> dict[str, Any]:
        self.check_owner(user_id)
        config = self.config()
        if not config or not config["enabled"]:
            raise ValueError("请先开启跨设备同步")
        self.capture(user_id, config["device_id"])
        self.handshake(client)
        batch, size = [], 0
        # Bounded runs keep the UI responsive on large libraries. Remaining outbox
        # operations survive and are sent by the next automatic round.
        for row in self.conn.execute("SELECT data FROM device_sync_outbox ORDER BY seq LIMIT 50"):
            if batch and size + len(row[0].encode()) > MAX_BODY // 2:
                break
            batch.append(json.loads(row[0]))
            size += len(row[0].encode())
        if batch:
            response = client.post("/v1/push", json=batch)
            response.raise_for_status()
        for _ in range(20):
            response = client.get("/v1/pull", params={"cursor": self.config()["cursor"]})
            response.raise_for_status()
            result = response.json()
            if result.get("library_id") != self.config()["library_id"]:
                raise ValueError("同步资料库已改变")
            self.apply(result["events"], user_id)
            if not result["more"]:
                break
        with self.conn:
            self.conn.execute(
                "UPDATE device_sync_config SET last_sync=?,last_error=NULL WHERE id=1", (now(),)
            )
        return self.status(user_id)


def safe_error(exc: Exception) -> str:
    # Do not persist/log response bodies, pairing keys or request URLs.
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return {
            401: "配对密钥不正确",
            409: "服务数据或冲突版本已变化，请检查服务备份或保留当前版本",
            413: "同步内容超出服务大小限制",
        }.get(code, f"同步服务返回错误（HTTP {code}）")
    if isinstance(exc, httpx.RequestError):
        return "无法连接同步服务，数据已保留，将在下次自动重试"
    if isinstance(exc, ValueError):
        return str(exc)[:200]
    return "同步未完成，本地数据已保留，请检查服务状态"


def run_sync(path: Path, user_id: int | None = None, *, resolution: tuple[str, str] | None = None):
    with sync_lock(path):
        storage = SqliteStorage(path)
        try:
            sync = DeviceSync(storage)
            config = sync.config()
            if not config or not config["enabled"]:
                return None
            uid = user_id if user_id is not None else config["user_id"]
            sync.check_owner(uid)
            active = sync.conn.execute("SELECT is_active FROM users WHERE id=?", (uid,)).fetchone()
            if not active or not active[0]:
                raise ValueError("绑定的本地账号已停用")
            with httpx.Client(
                base_url=validate_url(config["server_url"]),
                headers={"Authorization": f"Bearer {config['token']}"},
                timeout=15,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                if resolution:
                    sync.handshake(client)
                    conflict_id, choice = resolution
                    response = client.post(
                        f"/v1/conflicts/{conflict_id}/resolve", json={"choice": choice}
                    )
                    response.raise_for_status()
                return sync.sync(client, user_id=uid)
        except Exception as exc:
            # Configure/status can show the safe message even after restart.
            try:
                with storage._connect() as conn:
                    conn.execute(
                        "UPDATE device_sync_config SET last_error=? WHERE id=1", (safe_error(exc),)
                    )
            except sqlite3.Error:
                pass
            raise ValueError(safe_error(exc)) from exc
        finally:
            storage.close()
