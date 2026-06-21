"""Preview ebook candidates before download (no file I/O)."""

from __future__ import annotations

from typing import Any

from on1y.books.annas_api import AnnasArchiveClient
from on1y.books.edition_match import EditionHints
from on1y.books.settings_store import BookSettings, load_book_settings
from on1y.books.zlib_eapi import ZlibEapiClient, enrich_zlib_book_cover, zlib_book_candidate
from on1y.books.zlib_links import BOOK_FORMATS
from on1y.books.zlib_session import load_zlib_session
from on1y.exceptions import ConfigurationError

TOP_CANDIDATES_PER_FORMAT = 3


def preview_format_list(settings: BookSettings) -> list[str]:
    """Formats to preview: each gets top-N by popularity; empty = any format, single top-N."""
    raw: list[str] = []
    if settings.format_filters:
        raw = [str(f).lower() for f in settings.format_filters if str(f).lower() in BOOK_FORMATS]
    elif settings.format_filter and str(settings.format_filter).lower() in BOOK_FORMATS:
        raw = [str(settings.format_filter).lower()]
    order = {fmt: idx for idx, fmt in enumerate(BOOK_FORMATS)}
    return sorted(set(raw), key=lambda fmt: order.get(fmt, 99))


def _format_label(formats: list[str]) -> str:
    if not formats:
        return "任意格式"
    return " / ".join(fmt.upper() for fmt in formats)


def _search_zlib_books(
    client: ZlibEapiClient,
    query: str,
    *,
    title_fallback: str,
    fmt: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    books = client.search_popular(query, fmt=fmt, limit=limit)
    if not books and query != title_fallback.strip():
        books = client.search_popular(title_fallback, fmt=fmt, limit=limit)
    return books


def _zlib_preview_candidates(
    client: ZlibEapiClient,
    session_host: str,
    *,
    query: str,
    hints: EditionHints,
    formats: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()

    if not formats:
        books = _search_zlib_books(
            client,
            query,
            title_fallback=hints.title,
            fmt=None,
            limit=TOP_CANDIDATES_PER_FORMAT,
        )
        if not books:
            raise ConfigurationError(f"Z-Library 未找到「{hints.title}」的任意格式结果")
        for book in books[:TOP_CANDIDATES_PER_FORMAT]:
            enriched = enrich_zlib_book_cover(client, book, session_host)
            candidates.append(zlib_book_candidate(enriched, session_host))
        return candidates

    missing: list[str] = []
    for fmt in formats:
        books = _search_zlib_books(
            client,
            query,
            title_fallback=hints.title,
            fmt=fmt,
            limit=TOP_CANDIDATES_PER_FORMAT,
        )
        if not books:
            missing.append(fmt.upper())
            continue
        for book in books[:TOP_CANDIDATES_PER_FORMAT]:
            key = (book.get("id"), book.get("hash"))
            if key in seen:
                continue
            seen.add(key)
            enriched = enrich_zlib_book_cover(client, book, session_host)
            candidates.append(zlib_book_candidate(enriched, session_host))

    if not candidates:
        label = "、".join(missing) if missing else _format_label(formats)
        raise ConfigurationError(f"Z-Library 未找到「{hints.title}」的 {label} 结果")
    return candidates


def _annas_preview_candidates(
    client: AnnasArchiveClient,
    *,
    query: str,
    hints: EditionHints,
    formats: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_md5: set[str] = set()

    def add_rows(rows: list[tuple[str, str]], fmt: str | None) -> None:
        for md5, label in rows[:TOP_CANDIDATES_PER_FORMAT]:
            if md5 in seen_md5:
                continue
            seen_md5.add(md5)
            candidates.append(
                {
                    "source": "annas",
                    "format": fmt or _guess_annas_format(label),
                    "title": (label[:200] or hints.title).strip(),
                    "author": None,
                    "publisher": None,
                    "year": None,
                    "language": None,
                    "filesize": None,
                    "cover_url": None,
                    "md5": md5,
                    "label": label,
                }
            )

    if not formats:
        rows = client.search_candidates(query, None)
        if not rows and query != hints.title.strip():
            rows = client.search_candidates(hints.title, None)
        if not rows:
            raise ConfigurationError(f"安娜档案未找到「{hints.title}」的任意格式结果")
        add_rows(rows, None)
        return candidates

    missing: list[str] = []
    for fmt in formats:
        rows = client.search_candidates(query, fmt)
        if not rows and query != hints.title.strip():
            rows = client.search_candidates(hints.title, fmt)
        if not rows:
            missing.append(fmt.upper())
            continue
        add_rows(rows, fmt)

    if not candidates:
        label = "、".join(missing) if missing else _format_label(formats)
        raise ConfigurationError(f"安娜档案未找到「{hints.title}」的 {label} 结果")
    return candidates


def preview_ebook_candidates(
    user_id: int,
    *,
    hints: EditionHints,
    douban_cover_url: str | None = None,
    settings: BookSettings | None = None,
) -> dict[str, Any]:
    """Return top Z-Library results by popularity for user selection."""
    book_settings = settings or load_book_settings(user_id)
    formats = preview_format_list(book_settings)
    query = hints.search_query()

    zlib_errors: list[str] = []
    session = load_zlib_session(user_id)
    if session:
        try:
            client = ZlibEapiClient(session)
            if not client.verify():
                raise ConfigurationError("Z-Library Cookie 无效")
            candidates = _zlib_preview_candidates(
                client,
                session.host,
                query=query,
                hints=hints,
                formats=formats,
            )
            return {
                "ok": True,
                "source": "zlib",
                "search_query": query,
                "format_filter": formats[0] if len(formats) == 1 else None,
                "format_filters": formats,
                "total_candidates": len(candidates),
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
        candidates = _annas_preview_candidates(client, query=query, hints=hints, formats=formats)
        return {
            "ok": True,
            "source": "annas",
            "search_query": query,
            "format_filter": formats[0] if len(formats) == 1 else None,
            "format_filters": formats,
            "total_candidates": len(candidates),
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
