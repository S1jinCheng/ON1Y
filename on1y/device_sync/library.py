"""Translate portable sync records without leaking machine paths or credentials.

All writes use the caller's transaction, including FTS and the sync cursor.
No storage helper which commits independently may be used here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from on1y.device_sync.protocol import (
    DISTILL_FIELDS,
    META_FIELDS,
    RAW_FIELDS,
    THEME_FIELDS,
    encode,
    record_key,
)
from on1y.hotlist.sql import is_feed_row_sql
from on1y.search.fts import index_raw_item
from on1y.taxonomy.constants import DEFAULT_THEMES
from on1y.utils.json_util import loads_meta


def now() -> str:
    return datetime.now(UTC).isoformat()


def snapshot(conn: sqlite3.Connection, user_id: int) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in conn.execute("SELECT * FROM themes WHERE is_builtin=0 ORDER BY id"):
        if row["slug"] in {theme.slug for theme in DEFAULT_THEMES}:
            continue
        fields = {f: row[f] for f in THEME_FIELDS}
        fields["_deleted"] = bool(row["archived_at"])
        key = record_key("theme", row["slug"])
        records[key] = {"key": key, "kind": "theme", "identity": row["slug"], "fields": fields}
    tags: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        """
        SELECT it.raw_id,t.name FROM item_tags it JOIN tags t ON t.id=it.tag_id
        JOIN raw_items r ON r.id=it.raw_id WHERE r.user_id=?
    """,
        (user_id,),
    ):
        tags.setdefault(row["raw_id"], {})[f"tag/{row['name']}"] = True
    distills = {
        row["raw_id"]: dict(row)
        for row in conn.execute(
            """
        SELECT d.* FROM distilled_items d JOIN raw_items r ON r.id=d.raw_id WHERE r.user_id=?
    """,
            (user_id,),
        )
    }
    for row in conn.execute(
        f"""
        SELECT r.*, t.slug AS theme_slug FROM raw_items r
        LEFT JOIN themes t ON t.id=r.theme_id WHERE r.user_id=? AND {is_feed_row_sql("r")}
        ORDER BY r.id
    """,
        (user_id,),
    ):
        fields = {f: row[f] for f in RAW_FIELDS}
        fields["_deleted"] = bool(row["deleted_at"])
        meta = loads_meta(row["source_meta"])
        for name in META_FIELDS:
            if name in meta:
                value = meta[name]
                if name not in {"starred", "importance"} and value is not None:
                    value = str(value)
                fields[f"meta/{name}"] = value
        fields.update(tags.get(row["id"], {}))
        distill = distills.get(row["id"])
        if distill:
            for name in DISTILL_FIELDS:
                value = distill[name]
                if name in {"key_points", "topics"}:
                    value = json.loads(value or "[]")
                fields[f"distill/{name}"] = value
        key = record_key("item", row["url"])
        records[key] = {"key": key, "kind": "item", "identity": row["url"], "fields": fields}
    return records


def write_record(conn: sqlite3.Connection, user_id: int, record: dict[str, Any]) -> None:
    fields = record["fields"]
    identity = record["identity"]
    if record["kind"] == "theme":
        existing = conn.execute("SELECT * FROM themes WHERE slug=?", (identity,)).fetchone()
        if identity in {theme.slug for theme in DEFAULT_THEMES} or (
            existing and existing["is_builtin"]
        ):
            raise ValueError("a remote custom theme conflicts with a built-in theme")
        if not existing and fields.get("_deleted"):
            return
        conn.execute(
            """
            INSERT INTO themes(slug,name_zh,name_en) VALUES (?,?,?)
            ON CONFLICT(slug) DO NOTHING
        """,
            (identity, fields.get("name_zh") or identity, fields.get("name_en") or identity),
        )
        conn.execute(
            """
            UPDATE themes SET name_zh=?,name_en=?,description_zh=?,description_en=?,
                sort_order=?,archived_at=?,updated_at=? WHERE slug=?
        """,
            (
                fields.get("name_zh") or identity,
                fields.get("name_en") or identity,
                fields.get("description_zh") or "",
                fields.get("description_en") or "",
                fields.get("sort_order") or 0,
                now() if fields.get("_deleted") else None,
                now(),
                identity,
            ),
        )
        for row in conn.execute(
            """
            SELECT r.id FROM raw_items r JOIN themes t ON t.id=r.theme_id WHERE t.slug=?
        """,
            (identity,),
        ).fetchall():
            index_raw_item(conn, row[0])
        return

    existing = conn.execute(
        "SELECT * FROM raw_items WHERE user_id=? AND url=?", (user_id, identity)
    ).fetchone()
    if not existing and fields.get("_deleted"):
        return
    # A URL already used by a book/paper/hotlist must never be converted to a feed row.
    if existing:
        is_feed = conn.execute(
            f"SELECT 1 FROM raw_items r WHERE id=? AND {is_feed_row_sql('r')}",
            (existing["id"],),
        ).fetchone()
        if not is_feed:
            raise ValueError("sync URL collides with a local non-feed item")
    if not existing:
        conn.execute(
            """
            INSERT INTO raw_items(url,user_id,platform,source,content_type,extract_status)
            VALUES (?,?,'unknown','manual','unknown','ok')
        """,
            (identity, user_id),
        )
        existing = conn.execute(
            "SELECT * FROM raw_items WHERE user_id=? AND url=?", (user_id, identity)
        ).fetchone()
    raw_id = existing["id"]
    meta = loads_meta(existing["source_meta"])
    for name in META_FIELDS:
        value = fields.get(f"meta/{name}")
        if value is None:
            meta.pop(name, None)
        else:
            meta[name] = value
    theme_slug = fields.get("theme_slug")
    theme = conn.execute("SELECT id FROM themes WHERE slug=?", (theme_slug,)).fetchone()
    conn.execute(
        """
        UPDATE raw_items SET platform=?,source=?,raw_title=?,body_text=?,content_type=?,
            extract_status=?,ingested_at=?,theme_id=?,theme_source=?,source_meta=?,
            deleted_at=?,word_count=?,updated_at=? WHERE id=?
    """,
        (
            fields.get("platform") or "unknown",
            fields.get("source") or "manual",
            fields.get("raw_title"),
            fields.get("body_text"),
            fields.get("content_type") or "unknown",
            fields.get("extract_status") or "ok",
            fields.get("ingested_at") or existing["ingested_at"],
            theme[0] if theme else None,
            fields.get("theme_source") or "llm",
            encode(meta),
            (existing["deleted_at"] or now()) if fields.get("_deleted") else None,
            len((fields.get("body_text") or "").split()),
            now(),
            raw_id,
        ),
    )
    if any(fields.get(f"distill/{name}") is not None for name in DISTILL_FIELDS):
        columns = sorted(DISTILL_FIELDS)
        values = []
        for name in columns:
            value = fields.get(f"distill/{name}")
            if name in {"key_points", "topics"}:
                value = encode(value or [])
            elif name == "distill_status":
                value = value or "ok"
            values.append(value)
        conn.execute(
            f"""
            INSERT INTO distilled_items(raw_id,{",".join(columns)})
            VALUES ({",".join("?" for _ in range(len(columns) + 1))})
            ON CONFLICT(raw_id) DO UPDATE SET
            {",".join(f"{name}=excluded.{name}" for name in columns)}
        """,
            (raw_id, *values),
        )
    else:
        conn.execute("DELETE FROM distilled_items WHERE raw_id=?", (raw_id,))
    wanted = {field[4:] for field, value in fields.items() if field.startswith("tag/") and value}
    for row in conn.execute(
        """
        SELECT it.tag_id,t.name FROM item_tags it JOIN tags t ON t.id=it.tag_id WHERE raw_id=?
    """,
        (raw_id,),
    ).fetchall():
        if row["name"] not in wanted:
            conn.execute(
                "DELETE FROM item_tags WHERE raw_id=? AND tag_id=?", (raw_id, row["tag_id"])
            )
    for name in wanted:
        slug = "sync-" + hashlib.sha256(name.encode()).hexdigest()
        conn.execute(
            "INSERT INTO tags(name,slug) VALUES (?,?) ON CONFLICT(name) DO NOTHING", (name, slug)
        )
        tag_id = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO item_tags(raw_id,tag_id,source) VALUES (?,?,'manual')",
            (raw_id, tag_id),
        )
    index_raw_item(conn, raw_id)
