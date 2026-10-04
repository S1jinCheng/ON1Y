"""Allow-listed library mapping. Database IDs and file paths stay on each device."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from on1y.device_sync.library import snapshot as feed_snapshot
from on1y.device_sync.library import write_record as write_feed
from on1y.device_sync.protocol import DISTILL_FIELDS, RAW_FIELDS, encode, record_key
from on1y.folder_sync.files import cached_attachment
from on1y.folder_sync.protocol import BOOK_FIELDS, PAPER_FIELDS
from on1y.utils.json_util import loads_meta

TABLES = {"book": "book_shelf_items", "paper": "paper_items"}


def web_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        return (
            value
            if parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not (parsed.username or parsed.password)
            else None
        )
    except ValueError:
        return None


def portable_notes(notes: str | None) -> str | None:
    lines = [
        line
        for line in (notes or "").splitlines()
        if not line.strip().lower().startswith(("cached:", "source:", "original:"))
    ]
    return "\n".join(lines).strip() or None


def attachment_path(kind: str, row: sqlite3.Row) -> Path | None:
    from on1y.books.models import parse_cached_path

    value = row["pdf_path"] if kind == "paper" else parse_cached_path(row["notes"])
    return Path(value).expanduser() if value else None


def identity_for(kind: str, row: sqlite3.Row, attachment: dict | None) -> str:
    if kind == "paper":
        from on1y.papers.shelf import normalize_doi

        if row["doi"]:
            return "doi:" + normalize_doi(row["doi"])
        if url := web_url(row["url"]):
            return url
    else:
        from on1y.books.enrich import douban_url_from_links
        from on1y.books.models import BookLink

        links = [BookLink.model_validate(v) for v in json.loads(row["links_json"])]
        if url := douban_url_from_links(links):
            return url
    if attachment:
        return "sha256:" + attachment["sha256"]
    return "uuid:" + str(uuid4())


def snapshot(conn: sqlite3.Connection, user_id: int, staging: Path) -> dict[str, dict]:
    records = feed_snapshot(conn, user_id)
    for kind, table in TABLES.items():
        for row in conn.execute(f"SELECT * FROM {table} WHERE user_id=?", (user_id,)).fetchall():
            mapping = conn.execute(
                "SELECT * FROM folder_sync_mapping WHERE user_id=? AND kind=? AND local_id=?",
                (user_id, kind, row["id"]),
            ).fetchone()
            old = (
                conn.execute(
                    "SELECT data FROM folder_sync_shadow WHERE key=?", (mapping["key"],)
                ).fetchone()
                if mapping
                else None
            )
            previous = json.loads(old[0])["fields"] if old else {}
            attachment = previous.get("attachment")
            local_path = attachment_path(kind, row)
            if local_path is not None:
                attachment = cached_attachment(conn, local_path, staging) or attachment
            if not mapping:
                identity = identity_for(kind, row, attachment)
                key = record_key(kind, identity)
                # Preserve intentionally duplicated local editions rather than dropping a row.
                if conn.execute("SELECT 1 FROM folder_sync_mapping WHERE key=?", (key,)).fetchone():
                    identity = "uuid:" + str(uuid4())
                    key = record_key(kind, identity)
                conn.execute(
                    "INSERT INTO folder_sync_mapping VALUES (?,?,?,?,?)",
                    (key, user_id, kind, row["id"], identity),
                )
            else:
                key, identity = mapping["key"], mapping["identity"]
            names = BOOK_FIELDS if kind == "book" else PAPER_FIELDS
            fields = {"library/" + name: row[name] for name in names}
            if kind == "book":
                fields["library/notes"] = portable_notes(row["notes"])
                fields["library/cover_url"] = web_url(row["cover_url"])
                fields["library/links_json"] = encode(
                    [
                        {"label": v["label"], "url": v["url"]}
                        for v in json.loads(row["links_json"] or "[]")
                        if web_url(v.get("url"))
                    ]
                )
            else:
                fields["library/url"] = web_url(row["url"])
            raw = conn.execute(
                "SELECT r.*,t.slug AS theme_slug FROM raw_items r "
                "LEFT JOIN themes t ON t.id=r.theme_id WHERE r.id=? AND r.user_id=?",
                (row["raw_id"], user_id),
            ).fetchone()
            fields["_deleted"] = bool(raw["deleted_at"] if raw else previous.get("_deleted"))
            if raw:
                fields.update({name: raw[name] for name in RAW_FIELDS})
                distill = conn.execute(
                    "SELECT * FROM distilled_items WHERE raw_id=?", (raw["id"],)
                ).fetchone()
                if distill:
                    for name in DISTILL_FIELDS:
                        value = distill[name]
                        fields["distill/" + name] = (
                            json.loads(value or "[]") if name in {"topics", "key_points"} else value
                        )
            fields.update(
                {
                    "platform": kind,
                    "source": "manual",
                    "content_type": "article",
                    "extract_status": "ok",
                    "raw_title": row["title"],
                    "meta/user_note_html": row["user_note_html"],
                    "meta/importance": row["importance"],
                    "theme_slug": row["theme_slug"],
                    "attachment": attachment,
                }
            )
            fields.update({"tag/" + str(tag): True for tag in json.loads(row["tags_json"] or "[]")})
            records[key] = {"key": key, "kind": kind, "identity": identity, "fields": fields}
    return records


def pending_literature_fields(conn: sqlite3.Connection, user_id: int, paper_id: int) -> set[str]:
    """Fields waiting to be committed to this device's canonical Literature Vault."""

    if not conn.execute(
        """SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='folder_sync_literature_outbox'"""
    ).fetchone():
        return set()

    return {
        str(row[0])
        for row in conn.execute(
            """SELECT field FROM folder_sync_literature_outbox
            WHERE user_id=? AND paper_id=?""",
            (user_id, paper_id),
        )
    }


def drain_literature_outbox(conn: sqlite3.Connection, user_id: int) -> int:
    """Apply durable cross-database updates after the main SQLite commit."""

    rows = conn.execute(
        """SELECT paper_id,literature_paper_id,field,data
        FROM folder_sync_literature_outbox WHERE user_id=?
        ORDER BY paper_id,field""",
        (user_id,),
    ).fetchall()
    if not rows:
        return 0

    from on1y.papers.literature import LiteratureVault, local_vault_paper_ids

    expected_ids = list(dict.fromkeys(str(row["literature_paper_id"]) for row in rows))
    owned_ids = local_vault_paper_ids(user_id, expected_ids)
    if any(paper_id not in owned_ids for paper_id in expected_ids):
        raise ValueError(
            "当前 Literature Vault 不包含待同步论文，已暂停写入；请恢复原 Vault 后重试"
        )
    vault = LiteratureVault(user_id)
    drained = 0
    for row in rows:
        value = json.loads(row["data"])
        if row["field"] == "status":
            vault.set_paper_statuses([row["literature_paper_id"]], value)
        elif row["field"] == "importance":
            vault.set_paper_importance(row["literature_paper_id"], value)
        else:  # The table constraint protects new rows; fail closed on legacy corruption.
            raise ValueError("unsupported Literature bridge field")
        with conn:
            deleted = conn.execute(
                """DELETE FROM folder_sync_literature_outbox
                WHERE user_id=? AND paper_id=? AND field=? AND data=?""",
                (user_id, row["paper_id"], row["field"], row["data"]),
            ).rowcount
        drained += int(bool(deleted))
    return drained


def _queue_literature_updates(
    conn: sqlite3.Connection,
    user_id: int,
    row: sqlite3.Row,
    fields: dict,
    values: dict,
    *,
    created: bool,
) -> None:
    literature_id = str(
        values.get("literature_paper_id") or row["literature_paper_id"] or ""
    ).strip()
    if not literature_id:
        return
    updates = {}
    if "library/status" in fields and (created or values.get("status") != row["status"]):
        updates["status"] = values.get("status")
    if "meta/importance" in fields and (created or values.get("importance") != row["importance"]):
        updates["importance"] = values.get("importance")
    if not updates:
        return

    from on1y.papers.literature import local_vault_has_paper

    if not local_vault_has_paper(user_id, literature_id):
        return
    for field, value in updates.items():
        conn.execute(
            """INSERT INTO folder_sync_literature_outbox(
            user_id,paper_id,literature_paper_id,field,data) VALUES (?,?,?,?,?)
            ON CONFLICT(user_id,paper_id,field) DO UPDATE SET
            literature_paper_id=excluded.literature_paper_id,data=excluded.data""",
            (user_id, row["id"], literature_id, field, encode(value)),
        )


def write_record(conn: sqlite3.Connection, user_id: int, record: dict) -> None:
    kind, fields = record["kind"], record["fields"]
    if kind not in TABLES:
        write_feed(conn, user_id, record)
        return
    table = TABLES[kind]
    mapping = conn.execute(
        "SELECT * FROM folder_sync_mapping WHERE key=? AND user_id=?", (record["key"], user_id)
    ).fetchone()
    row = (
        conn.execute(
            f"SELECT * FROM {table} WHERE user_id=? AND id=?", (user_id, mapping["local_id"])
        ).fetchone()
        if mapping
        else None
    )
    if row is None and kind == "paper":
        literature_id = str(fields.get("library/literature_paper_id") or "").strip()
        if literature_id:
            candidate = conn.execute(
                """SELECT * FROM paper_items
                WHERE user_id=? AND literature_paper_id=? ORDER BY id LIMIT 1""",
                (user_id, literature_id),
            ).fetchone()
            existing_mapping = (
                conn.execute(
                    """SELECT * FROM folder_sync_mapping
                    WHERE user_id=? AND kind='paper' AND local_id=?""",
                    (user_id, candidate["id"]),
                ).fetchone()
                if candidate is not None
                else None
            )
            if candidate is not None:
                row = candidate
                if existing_mapping is None:
                    conn.execute(
                        "INSERT INTO folder_sync_mapping VALUES (?,?,?,?,?)",
                        (record["key"], user_id, kind, row["id"], record["identity"]),
                    )
                elif record["key"] < existing_mapping["key"]:
                    # Two independently seeded projections can have different
                    # portable identities. Both devices choose the same key;
                    # the next capture emits a tombstone for the losing key.
                    conn.execute(
                        """UPDATE folder_sync_mapping SET key=?,identity=?
                        WHERE key=? AND user_id=?""",
                        (
                            record["key"],
                            record["identity"],
                            existing_mapping["key"],
                            user_id,
                        ),
                    )
    if row is None and fields.get("_deleted"):
        return
    created = row is None
    if row is None:
        local_id = conn.execute(
            f"INSERT INTO {table}(user_id,title,status) VALUES (?,?,?)",
            (
                user_id,
                fields.get("library/title") or "Untitled",
                fields.get("library/status") or ("reading" if kind == "book" else "to_read"),
            ),
        ).lastrowid
        conn.execute(
            "INSERT OR REPLACE INTO folder_sync_mapping VALUES (?,?,?,?,?)",
            (
                record["key"],
                user_id,
                kind,
                local_id,
                record["identity"],
            ),
        )
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (local_id,)).fetchone()
    columns = BOOK_FIELDS if kind == "book" else PAPER_FIELDS
    values = {
        name: fields.get("library/" + name) for name in columns if "library/" + name in fields
    }
    values["title"] = values.get("title") or row["title"]
    if kind == "book" and "notes" in values:
        from on1y.books.models import parse_cached_path

        values["notes"] = portable_notes(values["notes"])
        if path := parse_cached_path(row["notes"]):
            values["notes"] = (values["notes"] or "") + "\ncached: " + path
    values.update(
        {
            "user_note_html": fields.get("meta/user_note_html"),
            "importance": fields.get("meta/importance"),
            "theme_slug": fields.get("theme_slug"),
            "tags_json": encode(
                sorted(f[4:] for f, v in fields.items() if f.startswith("tag/") and v)
            ),
        }
    )
    if kind == "paper" and values.get("ai_summary_json"):
        values["ai_summary_status"] = "ok"
    for name in ("authors_json", "links_json", "zotero_collections_json"):
        if name in values:
            values[name] = values[name] or "[]"
    if kind == "paper":
        _queue_literature_updates(conn, user_id, row, fields, values, created=created)
    conn.execute(
        f"UPDATE {table} SET {','.join(name + '=?' for name in values)},"
        "updated_at=datetime('now') WHERE id=? AND user_id=?",
        (*values.values(), row["id"], user_id),
    )
    raw = conn.execute(
        "SELECT url FROM raw_items WHERE id=? AND user_id=?", (row["raw_id"], user_id)
    ).fetchone()
    if raw:
        url = raw["url"]
    elif kind == "paper":
        from on1y.papers.knowledge_sync import paper_canonical_url
        from on1y.papers.models import paper_from_row

        fresh = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row["id"],)).fetchone()
        url = paper_canonical_url(paper_from_row(fresh))
    else:
        from on1y.books.knowledge_sync import shelf_canonical_url
        from on1y.books.models import shelf_item_from_row

        fresh = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row["id"],)).fetchone()
        url = shelf_canonical_url(shelf_item_from_row(fresh))
    raw_fields = {
        k: v for k, v in fields.items() if not k.startswith("library/") and k != "attachment"
    }
    raw_fields.update(platform=kind, raw_title=values["title"])
    # Old shelf rows may have no shared search entry yet.
    raw_fields.setdefault(
        "body_text", values.get("abstract") or values.get("summary") or values["title"]
    )
    write_feed(
        conn,
        user_id,
        {"kind": "item", "identity": url, "fields": raw_fields},
        library_platform=kind,
    )
    raw = conn.execute(
        "SELECT * FROM raw_items WHERE url=? AND user_id=?", (url, user_id)
    ).fetchone()
    if raw:
        meta = loads_meta(raw["source_meta"])
        meta.update(
            {
                "book_shelf" if kind == "book" else "paper_library": True,
                "shelf_item_id" if kind == "book" else "paper_item_id": row["id"],
            }
        )
        conn.execute("UPDATE raw_items SET source_meta=? WHERE id=?", (encode(meta), raw["id"]))
        conn.execute(f"UPDATE {table} SET raw_id=? WHERE id=?", (raw["id"], row["id"]))


def bind_attachment(conn: sqlite3.Connection, user_id: int, key: str, path: Path) -> None:
    mapping = conn.execute(
        "SELECT * FROM folder_sync_mapping WHERE key=? AND user_id=?", (key, user_id)
    ).fetchone()
    if not mapping:
        return
    if mapping["kind"] == "paper":
        conn.execute(
            "UPDATE paper_items SET pdf_path=? WHERE id=? AND user_id=?",
            (str(path), mapping["local_id"], user_id),
        )
    else:
        row = conn.execute(
            "SELECT notes FROM book_shelf_items WHERE id=? AND user_id=?",
            (mapping["local_id"], user_id),
        ).fetchone()
        if row:
            notes = (portable_notes(row["notes"]) or "") + "\ncached: " + str(path)
            conn.execute(
                "UPDATE book_shelf_items SET notes=?,cached_format=? WHERE id=? AND user_id=?",
                (notes, path.suffix.lstrip("."), mapping["local_id"], user_id),
            )
