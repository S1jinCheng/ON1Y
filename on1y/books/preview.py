"""Preview ebook candidates before download (no file I/O)."""

from __future__ import annotations

from typing import Any

from on1y.books.annas_api import AnnasArchiveClient
from on1y.books.edition_match import EditionHints
from on1y.books.settings_store import BookSettings, load_book_settings
from on1y.books.zlib_eapi import ZlibEapiClient, zlib_book_candidate
from on1y.books.zlib_session import load_zlib_session
from on1y.exceptions import ConfigurationError

TOP_CANDIDATES = 3


def _format_filter(settings: BookSettings) -> str | None:
    value = settings.format_filter
    if value and str(value).lower() in ("epub", "pdf", "mobi"):
        return str(value).lower()
    return None


def preview_ebook_candidates(
    user_id: int,
    *,
    hints: EditionHints,
    douban_cover_url: str | None = None,
    settings: BookSettings | None = None,
) -> dict[str, Any]:
    """Return top Z-Library results by popularity for user selection."""
    book_settings = settings or load_book_settings(user_id)
    fmt_filter = _format_filter(book_settings)
    query = hints.search_query()

    zlib_errors: list[str] = []
    session = load_zlib_session(user_id)
    if session:
        try:
            client = ZlibEapiClient(session)
            if not client.verify():
                raise ConfigurationError("Z-Library Cookie 无效")
            books = client.search_popular(query, fmt=fmt_filter, limit=TOP_CANDIDATES)
            if not books and query != hints.title.strip():
                books = client.search_popular(hints.title, fmt=fmt_filter, limit=TOP_CANDIDATES)
            if not books:
                label = fmt_filter.upper() if fmt_filter else "任意格式"
                raise ConfigurationError(f"Z-Library 未找到「{hints.title}」的 {label} 结果")
            candidates = [
                zlib_book_candidate(book, session.host, douban_cover=douban_cover_url)
                for book in books[:TOP_CANDIDATES]
            ]
            return {
                "ok": True,
                "source": "zlib",
                "search_query": query,
                "format_filter": fmt_filter,
                "total_candidates": len(books),
                "douban": {
                    "title": hints.title,
                    "author": hints.author,
                    "translator": hints.translator,
                    "publisher": hints.publisher,
                    "isbn": hints.isbn,
                    "cover_url": douban_cover_url,
                },
                "candidates": candidates,
            }
        except ConfigurationError as exc:
            zlib_errors.append(str(exc))
    else:
        zlib_errors.append("未配置 Z-Library Cookie（需 remix_userid / remix_userkey）")

    try:
        client = AnnasArchiveClient()
        rows = client.search_candidates(query, fmt_filter)
        if not rows and query != hints.title.strip():
            rows = client.search_candidates(hints.title, fmt_filter)
        if not rows:
            label = fmt_filter.upper() if fmt_filter else "任意格式"
            raise ConfigurationError(f"安娜档案未找到「{hints.title}」的 {label} 结果")
        candidates = []
        for md5, label in rows[:TOP_CANDIDATES]:
            candidates.append(
                {
                    "source": "annas",
                    "format": fmt_filter or _guess_annas_format(label),
                    "title": (label[:200] or hints.title).strip(),
                    "author": None,
                    "publisher": None,
                    "year": None,
                    "language": None,
                    "filesize": None,
                    "cover_url": douban_cover_url,
                    "md5": md5,
                    "label": label,
                }
            )
        return {
            "ok": True,
            "source": "annas",
            "search_query": query,
            "format_filter": fmt_filter,
            "total_candidates": len(rows),
            "douban": {
                "title": hints.title,
                "author": hints.author,
                "translator": hints.translator,
                "publisher": hints.publisher,
                "isbn": hints.isbn,
                "cover_url": douban_cover_url,
            },
            "candidates": candidates,
        }
    except ConfigurationError as annas_exc:
        parts = ["Z-Library："] + zlib_errors + [f"安娜档案：{annas_exc}"]
        raise ConfigurationError("；".join(parts)) from annas_exc


def _guess_annas_format(label: str) -> str:
    lowered = (label or "").lower()
    for fmt in ("epub", "pdf", "mobi"):
        if fmt in lowered:
            return fmt
    return "epub"
