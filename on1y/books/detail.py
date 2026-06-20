"""Fetch book edition detail and acquisition links."""

from __future__ import annotations

from on1y.books.builtin_sources import ZLIB_BASE
from on1y.books.models import BookWorkDetail
from on1y.books.providers.parsers.douban_book import fetch_douban_subject
from on1y.books.settings_store import load_book_settings
from on1y.books.sources_store import list_enabled_sources
from on1y.books.zlib_links import build_edition_links, build_source_browse_links


def load_book_detail(user_id: int, url: str) -> BookWorkDetail | None:
    detail = fetch_douban_subject(url)
    if detail is None:
        return None
    enabled = list_enabled_sources(user_id)
    annas_on = any(s.id == "annas-link" and s.enabled for s in enabled)
    zlib_on = any(s.id == "zlib-link" and s.enabled for s in enabled)
    book_settings = load_book_settings(user_id)
    zlib_base = book_settings.zlib_base_url or ZLIB_BASE
    detail.acquisition_links = build_edition_links(
        title=detail.title,
        douban_url=detail.url,
        author=detail.author,
        translator=detail.translator,
        zlib_base_url=zlib_base,
        annas_enabled=annas_on,
        zlib_enabled=zlib_on,
    )
    detail.source_links = build_source_browse_links(
        title=detail.title,
        douban_url=detail.url,
        author=detail.author,
        translator=detail.translator,
        zlib_base_url=zlib_base,
        annas_enabled=annas_on,
        zlib_enabled=zlib_on,
    )
    return detail
