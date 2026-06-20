"""Sync shelf rows into raw_items for shared tags, FTS, and recommendations."""

from __future__ import annotations

import logging

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.books.cover import normalize_cover_url
from on1y.books.enrich import douban_url_from_links
from on1y.books.models import BookShelfItem
from on1y.books.shelf import get_shelf_item
from on1y.books.tags import BOOK_SHELF_TAG_PROMPT_VERSION, distill_book_shelf_tags
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.utils.json_util import dumps_json

logger = logging.getLogger(__name__)

BOOK_DISTILL_PROMPT_VERSION = "book-shelf-v1"


def shelf_canonical_url(item: BookShelfItem) -> str:
    douban = douban_url_from_links(item.links)
    if douban:
        return douban
    return f"on1y://books/shelf/{item.id}"


def _set_shelf_raw_id(storage: SqliteStorage, user_id: int, item_id: int, raw_id: int) -> None:
    conn = storage._connect()
    conn.execute(
        "UPDATE book_shelf_items SET raw_id = ? WHERE user_id = ? AND id = ?",
        (raw_id, user_id, item_id),
    )
    conn.commit()


def _sync_tags_json(storage: SqliteStorage, user_id: int, item_id: int, raw_id: int) -> None:
    names = storage.get_item_tag_names(raw_id)
    conn = storage._connect()
    conn.execute(
        """
        UPDATE book_shelf_items
        SET tags_json = ?, updated_at = datetime('now')
        WHERE user_id = ? AND id = ?
        """,
        (dumps_json(names), user_id, item_id),
    )
    conn.commit()


def ensure_shelf_knowledge(
    storage: SqliteStorage,
    user_id: int,
    item: BookShelfItem,
) -> BookShelfItem:
    """Ensure a shelf book has raw_item + distilled summary for library recommendations."""
    cover = normalize_cover_url(item.cover_url)
    body = (item.summary or "").strip() or item.title.strip()
    summary = (item.summary or "").strip()
    if summary and len(summary) > 400:
        summary = summary[:400].rstrip() + "…"
    if not summary:
        summary = item.title.strip()

    meta = {
        "author": item.author or "",
        "translator": item.translator or "",
        "cover_image": cover or "",
        "shelf_item_id": item.id,
        "book_shelf": True,
    }

    raw = storage.upsert_raw_item(
        RawItemCreate(
            url=shelf_canonical_url(item),
            platform="book",
            source=SourceType.MANUAL,
            raw_title=item.title.strip(),
            body_text=body,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta=meta,
        )
    )
    raw_id = int(raw.id)
    if item.raw_id != raw_id:
        _set_shelf_raw_id(storage, user_id, item.id, raw_id)

    storage.upsert_distilled(
        raw_id=raw_id,
        summary=summary,
        key_points=[],
        topics=[],
        model=None,
        prompt_version=BOOK_DISTILL_PROMPT_VERSION,
        status="ok",
        error=None,
    )

    refreshed = get_shelf_item(storage, user_id, item.id)
    assert refreshed is not None
    item = refreshed

    _sync_tags_json(storage, user_id, item.id, raw_id)
    updated = get_shelf_item(storage, user_id, item.id)
    return updated or item


def maybe_auto_tag_shelf_item(
    storage: SqliteStorage,
    user_id: int,
    item: BookShelfItem,
) -> BookShelfItem:
    if item.raw_id is None:
        return item
    if item.tags:
        return item
    try:
        distill_book_shelf_tags(storage, item.raw_id, item)
    except Exception as exc:
        logger.info("Book shelf auto-tag skipped for %s: %s", item.id, exc)
        return item
    _sync_tags_json(storage, user_id, item.id, item.raw_id)
    return get_shelf_item(storage, user_id, item.id) or item


def prepare_shelf_item(
    storage: SqliteStorage,
    user_id: int,
    item: BookShelfItem,
    *,
    auto_tag: bool = True,
) -> BookShelfItem:
    from on1y.books.enrich import enrich_shelf_item_from_douban

    item = enrich_shelf_item_from_douban(storage, user_id, item)
    item = ensure_shelf_knowledge(storage, user_id, item)
    if auto_tag:
        item = maybe_auto_tag_shelf_item(storage, user_id, item)
    return item


def sync_shelf_tags_manual(
    storage: SqliteStorage,
    user_id: int,
    item_id: int,
    tags: list[str],
) -> None:
    item = get_shelf_item(storage, user_id, item_id)
    if item is None:
        return
    if item.raw_id is None:
        item = ensure_shelf_knowledge(storage, user_id, item)
    raw_id = item.raw_id
    if raw_id is None:
        return
    storage.set_item_classification(raw_id, tags=tags, source="manual")
    storage.merge_source_meta(
        raw_id,
        {"book_shelf_tags_version": BOOK_SHELF_TAG_PROMPT_VERSION},
    )
    _sync_tags_json(storage, user_id, item_id, raw_id)
