"""Enrich shelf rows from Douban metadata (no ebook / LLM)."""

from __future__ import annotations

import logging
import re

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.books.cover import normalize_cover_url
from on1y.books.detail import load_book_detail
from on1y.books.models import BookLink, BookShelfItem, BookShelfUpdate
from on1y.books.shelf import update_shelf_item

logger = logging.getLogger(__name__)

_DOUBAN_RE = re.compile(r"douban\.com/subject/\d+", re.I)


def douban_url_from_links(links: list[BookLink]) -> str | None:
    for link in links:
        if link.label == "豆瓣" or _DOUBAN_RE.search(link.url):
            return link.url.strip()
    return None


def enrich_shelf_item_from_douban(
    storage: SqliteStorage,
    user_id: int,
    item: BookShelfItem,
) -> BookShelfItem:
    """Fill missing cover/summary/translator from Douban page scrape."""
    from on1y.books.shelf_metadata import douban_enrich_allowed

    if not douban_enrich_allowed(notes=item.notes):
        return item
    if item.cover_url and item.summary and item.translator:
        return item
    douban_url = douban_url_from_links(item.links)
    if not douban_url:
        return item
    try:
        detail = load_book_detail(user_id, douban_url)
    except Exception as exc:
        logger.debug("Douban enrich failed for shelf %s: %s", item.id, exc)
        return item
    if detail is None:
        return item
    patch = BookShelfUpdate(
        cover_url=normalize_cover_url(item.cover_url or detail.cover_url),
        translator=item.translator if item.translator else detail.translator,
        publisher=item.publisher or detail.publisher,
        summary=item.summary or (detail.summary[:4000] if detail.summary else None),
        author=item.author or detail.author,
    )
    if (
        patch.cover_url == item.cover_url
        and patch.translator == item.translator
        and patch.publisher == item.publisher
        and patch.summary == item.summary
        and patch.author == item.author
    ):
        return item
    updated = update_shelf_item(storage, user_id, item.id, patch)
    return updated or item
