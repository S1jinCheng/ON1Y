"""Book shelf CRUD (per-user)."""

from __future__ import annotations

from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.books.cover import normalize_cover_url
from on1y.books.models import (
    BookShelfCreate,
    BookShelfItem,
    BookShelfUpdate,
    shelf_item_from_row,
)
from on1y.utils.json_util import dumps_json


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        name = str(raw).strip().lstrip("#")
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def count_shelf_items(storage: SqliteStorage, user_id: int) -> int:
    conn = storage._connect()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM book_shelf_items WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def list_shelf_items(
    storage: SqliteStorage,
    user_id: int,
    *,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[BookShelfItem]:
    conn = storage._connect()
    where = ["user_id = ?"]
    params: list[Any] = [user_id]
    if status and status in ("reading", "read"):
        where.append("status = ?")
        params.append(status)
    sql = f"""
        SELECT * FROM book_shelf_items
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC, id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return [shelf_item_from_row(row) for row in rows]


def get_shelf_item(storage: SqliteStorage, user_id: int, item_id: int) -> BookShelfItem | None:
    conn = storage._connect()
    row = conn.execute(
        "SELECT * FROM book_shelf_items WHERE user_id = ? AND id = ?",
        (user_id, item_id),
    ).fetchone()
    return shelf_item_from_row(row) if row else None


def create_shelf_item(
    storage: SqliteStorage,
    user_id: int,
    payload: BookShelfCreate,
) -> BookShelfItem:
    conn = storage._connect()
    links_json = dumps_json([link.model_dump() for link in payload.links])
    tags_json = dumps_json(_normalize_tags(payload.tags))
    cur = conn.execute(
        """
        INSERT INTO book_shelf_items (
            user_id, title, author, translator, publisher, cover_url, summary,
            status, links_json, notes, cached_format, tags_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            payload.title.strip(),
            (payload.author or "").strip() or None,
            (payload.translator or "").strip() or None,
            (payload.publisher or "").strip() or None,
            (normalize_cover_url(payload.cover_url) or "").strip() or None,
            (payload.summary or "").strip() or None,
            payload.status,
            links_json,
            (payload.notes or "").strip() or None,
            (payload.cached_format or "").strip().lower() or None,
            tags_json,
        ),
    )
    conn.commit()
    item = get_shelf_item(storage, user_id, int(cur.lastrowid))
    assert item is not None
    return item


def update_shelf_item(
    storage: SqliteStorage,
    user_id: int,
    item_id: int,
    payload: BookShelfUpdate,
) -> BookShelfItem | None:
    existing = get_shelf_item(storage, user_id, item_id)
    if existing is None:
        return None
    title = payload.title.strip() if payload.title is not None else existing.title
    author = existing.author
    if payload.author is not None:
        author = payload.author.strip() or None
    translator = existing.translator
    if payload.translator is not None:
        translator = payload.translator.strip() or None
    publisher = existing.publisher
    if payload.publisher is not None:
        publisher = payload.publisher.strip() or None
    cover_url = existing.cover_url
    if payload.cover_url is not None:
        cover_url = normalize_cover_url(payload.cover_url.strip()) or None
    summary = existing.summary
    if payload.summary is not None:
        summary = payload.summary.strip() or None
    status = payload.status if payload.status is not None else existing.status
    links = payload.links if payload.links is not None else existing.links
    notes = existing.notes
    if payload.notes is not None:
        notes = payload.notes.strip() or None
    user_note_html = existing.user_note_html
    if payload.user_note_html is not None:
        user_note_html = payload.user_note_html.strip() or None
    importance = existing.importance
    if payload.importance is not None:
        importance = payload.importance
    theme_slug = existing.theme_slug
    if payload.theme_slug is not None:
        theme_slug = payload.theme_slug.strip() or None
    tags = existing.tags
    if payload.tags is not None:
        tags = _normalize_tags(payload.tags)
    cached_format = existing.cached_format
    if payload.cached_format is not None:
        cached_format = payload.cached_format.strip().lower() or None
    links_json = dumps_json([link.model_dump() for link in links])
    tags_json = dumps_json(tags)
    conn = storage._connect()
    conn.execute(
        """
        UPDATE book_shelf_items
        SET title = ?, author = ?, translator = ?, publisher = ?, cover_url = ?, summary = ?,
            status = ?, links_json = ?, notes = ?, user_note_html = ?, importance = ?,
            theme_slug = ?, tags_json = ?, cached_format = ?,
            updated_at = datetime('now')
        WHERE user_id = ? AND id = ?
        """,
        (
            title,
            author,
            translator,
            publisher,
            cover_url,
            summary,
            status,
            links_json,
            notes,
            user_note_html,
            importance,
            theme_slug,
            tags_json,
            cached_format,
            user_id,
            item_id,
        ),
    )
    conn.commit()
    return get_shelf_item(storage, user_id, item_id)


def delete_shelf_item(storage: SqliteStorage, user_id: int, item_id: int) -> bool:
    conn = storage._connect()
    cur = conn.execute(
        "DELETE FROM book_shelf_items WHERE user_id = ? AND id = ?",
        (user_id, item_id),
    )
    conn.commit()
    return cur.rowcount > 0
