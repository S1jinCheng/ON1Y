"""Download ebooks via Z-Library eapi, then Anna's Archive API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from on1y.books.annas_api import AnnasArchiveClient, download_from_annas
from on1y.books.edition_match import EditionHints
from on1y.books.settings_store import BookSettings, load_book_settings
from on1y.books.zlib_eapi import ZlibEapiClient, download_from_zlib_eapi
from on1y.books.zlib_links import BOOK_FORMATS
from on1y.books.zlib_session import load_zlib_session
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def _resolve_format_filter(settings: BookSettings, fmt: str | None) -> str | None:
    if fmt and fmt in BOOK_FORMATS:
        return fmt.lower()
    if settings.format_filters:
        if len(settings.format_filters) == 1:
            return str(settings.format_filters[0]).lower()
        return None
    value = settings.format_filter
    if value and str(value).lower() in BOOK_FORMATS:
        return str(value).lower()
    return None


def download_ebook_by_candidate(
    user_id: int,
    *,
    hints: EditionHints,
    candidate: dict[str, Any],
    settings: BookSettings | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Download a previously previewed candidate."""
    book_settings = settings or load_book_settings(user_id)
    source = str(candidate.get("source") or "").strip().lower()
    fmt = str(candidate.get("format") or book_settings.preferred_format or "epub").lower()

    if source == "zlib":
        session = load_zlib_session(user_id)
        if not session:
            raise ConfigurationError("未配置 Z-Library Cookie（需 remix_userid / remix_userkey）")
        book_id = candidate.get("book_id")
        book_hash = candidate.get("book_hash")
        if not book_id or not book_hash:
            raise ConfigurationError("Z-Library 候选信息不完整")
        client = ZlibEapiClient(session)
        if not client.verify():
            raise ConfigurationError("Z-Library Cookie 无效，请在设置中重新导入 remix_userid / remix_userkey")
        _filename, data = client.download_bytes(book_id, book_hash)
        meta = {
            "matched_title": str(candidate.get("title") or hints.title),
            "matched_author": candidate.get("author"),
            "search_query": hints.search_query(),
            "format": fmt,
        }
        return data, "zlib", meta

    if source == "annas":
        md5 = str(candidate.get("md5") or "").strip().lower()
        if not md5:
            raise ConfigurationError("安娜档案候选信息不完整")
        annas_client = AnnasArchiveClient()
        label = str(candidate.get("label") or candidate.get("title") or hints.title)
        meta = {
            "matched_title": label[:200],
            "matched_author": None,
            "search_query": hints.search_query(),
            "md5": md5,
            "format": fmt,
        }
        errors: list[str] = []
        secret_key = book_settings.annas_secret_key
        if secret_key and secret_key.strip():
            try:
                url = annas_client.fast_download_url(md5, secret_key)
                return annas_client.download_file(url), "annas", meta
            except ConfigurationError as exc:
                errors.append(str(exc))
        for url in annas_client.partner_download_urls(md5):
            try:
                return annas_client.download_file(url), "annas", meta
            except ConfigurationError as exc:
                errors.append(str(exc))
                logger.debug("Anna partner download failed %s: %s", url, exc)
        hint = "；".join(errors[:2]) if errors else "无可用镜像"
        raise ConfigurationError(
            f"安娜档案下载失败（{hint}）。"
            "可在设置 → 图书填写安娜档案会员 Secret Key 以使用 fast_download API"
        )

    raise ConfigurationError("未知的电子书来源")


def download_ebook_bytes(
    user_id: int,
    *,
    hints: EditionHints,
    fmt: str | None = None,
    settings: BookSettings | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Return file bytes, source label (zlib | annas), and metadata."""
    book_settings = settings or load_book_settings(user_id)
    resolved_fmt = _resolve_format_filter(book_settings, fmt)

    zlib_errors: list[str] = []
    session = load_zlib_session(user_id)
    if session:
        try:
            data, meta = download_from_zlib_eapi(session, hints=hints, fmt=resolved_fmt)
            if resolved_fmt:
                meta["format"] = resolved_fmt
            return data, "zlib", meta
        except ConfigurationError as exc:
            zlib_errors.append(str(exc))
            logger.info("Z-Library eapi failed for %r: %s", hints.title, exc)
    else:
        zlib_errors.append("未配置 Z-Library Cookie（需 remix_userid / remix_userkey）")

    try:
        data, meta = download_from_annas(
            hints=hints,
            fmt=resolved_fmt,
            secret_key=book_settings.annas_secret_key,
        )
        return data, "annas", meta
    except ConfigurationError as annas_exc:
        parts = ["Z-Library："] + zlib_errors + [f"安娜档案：{annas_exc}"]
        raise ConfigurationError("；".join(parts)) from annas_exc


def download_ebook_to_path(
    user_id: int,
    *,
    hints: EditionHints,
    fmt: str | None,
    dest: Path,
    settings: BookSettings | None = None,
) -> tuple[str, dict[str, Any], str]:
    """Download to dest if missing; returns source, metadata, resolved format."""
    book_settings = settings or load_book_settings(user_id)
    resolved_fmt = _resolve_format_filter(book_settings, fmt)
    ext = resolved_fmt or "epub"

    if dest.is_file() and dest.stat().st_size > 1024:
        actual_ext = dest.suffix.lstrip(".") or ext
        return "cache", {
            "matched_title": hints.title,
            "matched_author": hints.author,
            "search_query": hints.search_query(),
            "from_cache": True,
            "format": actual_ext,
        }, actual_ext

    data, source, meta = download_ebook_bytes(
        user_id,
        hints=hints,
        fmt=resolved_fmt,
        settings=book_settings,
    )
    actual_fmt = str(meta.get("format") or ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    meta["format"] = actual_fmt
    return source, meta, actual_fmt
