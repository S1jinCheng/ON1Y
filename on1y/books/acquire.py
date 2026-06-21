"""Download ebooks via API (Z-Library eapi → Anna's Archive) and optional Kindle delivery."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from on1y.books.builtin_sources import ZLIB_BASE
from on1y.books.download import download_ebook_by_candidate, download_ebook_to_path
from on1y.books.edition_match import EditionHints
from on1y.books.file_validate import validate_ebook_bytes
from on1y.books.models import BookLink, BookShelfCreate, BookShelfItem
from on1y.books.settings_store import BookSettings, load_book_settings
from on1y.books.zlib_links import BOOK_FORMATS, build_edition_links, zlib_search_url
from on1y.exceptions import ConfigurationError
from on1y.user.paths import resolve_books_cache_dir
from on1y.user.profile import kindle_delivery_address, load_user_profile

logger = logging.getLogger(__name__)

KINDLE_EMAIL_MAX_BYTES = 50 * 1024 * 1024

_SAFE_CHARS = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)


def _safe_filename(
    title: str,
    ext: str,
    *,
    translator: str | None = None,
    full_label: str | None = None,
) -> str:
    if full_label and full_label.strip():
        stem = _SAFE_CHARS.sub("_", full_label.strip()).strip("_")
    else:
        stem = _SAFE_CHARS.sub("_", (title or "book").strip()).strip("_")
        if translator and translator.strip():
            tr = _SAFE_CHARS.sub("_", translator.strip()).strip("_")[:40]
            if tr:
                stem = f"{stem}_{tr}"
    stem = stem[:180] or "book"
    suffix = ext if ext.startswith(".") else f".{ext}"
    return f"{stem}{suffix}"


def _zlib_book_format_from_ext(ext: str) -> str:
    key = str(ext or "").lower().lstrip(".")
    if key in BOOK_FORMATS:
        return key
    return "epub"


def download_book_file(
    user_id: int,
    *,
    hints: EditionHints,
    fmt: str | None,
    cache_dir: Path,
    settings: BookSettings | None = None,
    candidate: dict[str, Any] | None = None,
    file_label: str | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    """Download ebook to cache_dir; returns path, source, and match metadata."""
    book_settings = settings or load_book_settings(user_id)
    ext_guess = str(
        fmt or (candidate or {}).get("format") or book_settings.preferred_format or "epub"
    ).lower()
    dest = cache_dir / _safe_filename(
        hints.title, ext_guess, translator=hints.translator, full_label=file_label
    )

    if candidate:
        source = str(candidate.get("source") or "").strip().lower()
        actual_fmt = str(candidate.get("format") or ext_guess).lower()
        final_dest = cache_dir / _safe_filename(
            hints.title, actual_fmt, translator=hints.translator, full_label=file_label
        )
        final_dest.parent.mkdir(parents=True, exist_ok=True)

        if source == "zlib":
            from on1y.books.zlib_eapi import ZlibEapiClient
            from on1y.books.zlib_session import load_zlib_session

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
            dl_meta = client.download_to_path(book_id, book_hash, final_dest)
            actual_fmt = _zlib_book_format_from_ext(dl_meta.get("extension") or actual_fmt)
            if final_dest.suffix.lstrip(".").lower() != actual_fmt:
                renamed = final_dest.with_suffix(f".{actual_fmt}")
                if not renamed.is_file():
                    final_dest.rename(renamed)
                final_dest = renamed
            meta = {
                "matched_title": str(candidate.get("title") or hints.title),
                "matched_author": candidate.get("author"),
                "search_query": hints.search_query(),
                "format": actual_fmt,
            }
            source_label = "zlib"
        else:
            data, source_label, meta = download_ebook_by_candidate(
                user_id,
                hints=hints,
                candidate=candidate,
                settings=book_settings,
            )
            actual_fmt = str(meta.get("format") or ext_guess)
            final_dest = cache_dir / _safe_filename(
                hints.title, actual_fmt, translator=hints.translator, full_label=file_label
            )
            final_dest.parent.mkdir(parents=True, exist_ok=True)
            final_dest.write_bytes(data)

        validation = validate_ebook_bytes(final_dest.read_bytes(), actual_fmt)
        if not validation.get("ok"):
            final_dest.unlink(missing_ok=True)
            detail = validation.get("detail") or "文件校验失败"
            raise ConfigurationError(f"下载的文件可能损坏：{detail}")
        meta["validation"] = validation
        meta["format"] = actual_fmt
        return final_dest, source_label, meta

    source, meta, actual_fmt = download_ebook_to_path(
        user_id,
        hints=hints,
        fmt=fmt,
        dest=dest,
        settings=book_settings,
    )
    final_dest = cache_dir / _safe_filename(
        hints.title, actual_fmt, translator=hints.translator, full_label=file_label
    )
    if final_dest != dest and dest.is_file() and not final_dest.is_file():
        dest.rename(final_dest)
    elif final_dest != dest and dest.is_file() and final_dest.is_file():
        dest.unlink(missing_ok=True)
    path = final_dest if final_dest.is_file() else dest
    if not path.is_file():
        raise ConfigurationError("下载失败")
    validation = validate_ebook_bytes(path.read_bytes(), actual_fmt)
    if not validation.get("ok"):
        detail = validation.get("detail") or "文件校验失败"
        raise ConfigurationError(f"下载的文件可能损坏：{detail}")
    meta["validation"] = validation
    meta["format"] = actual_fmt
    return path, source, meta


def resolve_shelf_cached_path(
    user_id: int,
    item: BookShelfItem,
) -> Path | None:
    from on1y.books.cache_files import list_cached_ebooks
    from on1y.books.models import parse_cached_path

    path_str = item.local_path or parse_cached_path(item.notes)
    if path_str:
        path = Path(path_str)
        if path.is_file():
            return path
    files = list_cached_ebooks(user_id, item.title, notes=item.notes)
    if not files:
        return None
    path = Path(files[0]["path"])
    return path if path.is_file() else None


def send_shelf_book_to_kindle(
    user_id: int,
    storage: Any,
    item_id: int,
) -> dict[str, Any]:
    from on1y.books.shelf import get_shelf_item

    from on1y.books.display_name import format_book_label_from_shelf

    item = get_shelf_item(storage, user_id, item_id)
    if item is None:
        raise ConfigurationError("书架条目不存在")
    local_path = resolve_shelf_cached_path(user_id, item)
    if local_path is None:
        raise ConfigurationError("未找到本地缓存文件，请先下载电子书")
    kindle_sent, kindle_status, kindle_detail = maybe_send_kindle(
        user_id,
        local_path,
        title=format_book_label_from_shelf(item),
    )
    from on1y.books.kindle_notes import merge_kindle_status
    from on1y.books.models import BookShelfUpdate
    from on1y.books.shelf import update_shelf_item

    updated = update_shelf_item(
        storage,
        user_id,
        item_id,
        BookShelfUpdate(notes=merge_kindle_status(item.notes, kindle_status, kindle_detail)),
    )
    return {
        "ok": True,
        "kindle_sent": kindle_sent,
        "kindle_status": kindle_status,
        "kindle_detail": kindle_detail,
        "shelf_item": updated.model_dump() if updated else None,
    }


def maybe_send_kindle(user_id: int, local_path: Path, *, title: str) -> tuple[bool, str, str | None]:
    """Return (sent, status, detail) where status is sent|skipped|failed."""
    profile = load_user_profile(user_id)
    kindle_to = kindle_delivery_address(profile)
    kindle = profile.get("kindle") if isinstance(profile.get("kindle"), dict) else {}
    if not kindle_to:
        return False, "skipped", "未配置 Kindle 收件邮箱"
    if not kindle.get("enabled", True):
        return False, "skipped", "Kindle 推送已关闭"
    size_bytes = local_path.stat().st_size
    if size_bytes > KINDLE_EMAIL_MAX_BYTES:
        mb = size_bytes / (1024 * 1024)
        return (
            False,
            "skipped",
            f"文件约 {mb:.0f}MB，超过 Kindle 邮件上限（50MB），已仅保存到本地",
        )
    try:
        from on1y.delivery.kindle import send_book_to_kindle

        send_book_to_kindle(local_path, to_address=kindle_to, subject=title[:200])
        return True, "sent", None
    except Exception as exc:
        logger.warning("Kindle send failed for %r: %s", title, exc)
        return False, "failed", str(exc)


def preview_acquire_book(
    user_id: int,
    *,
    title: str,
    author: str | None,
    translator: str | None = None,
    publisher: str | None = None,
    isbn: str | None = None,
    douban_url: str | None = None,
    douban_cover_url: str | None = None,
    fmt: str | None = None,
) -> dict[str, Any]:
    """Search and return the best candidate for user confirmation."""
    from on1y.books.preview import preview_ebook_candidates

    cover = (douban_cover_url or "").strip() or None
    if not cover and douban_url:
        try:
            from on1y.books.cover import normalize_cover_url
            from on1y.books.detail import load_book_detail

            detail = load_book_detail(user_id, douban_url.strip())
            if detail is not None:
                cover = normalize_cover_url(detail.cover_url)
        except Exception:
            cover = cover or None

    hints = EditionHints(
        title=title,
        author=author,
        translator=translator,
        publisher=publisher,
        isbn=isbn,
    )
    return preview_ebook_candidates(
        user_id,
        hints=hints,
        douban_cover_url=cover,
    )


def acquire_book(
    user_id: int,
    storage: Any,
    *,
    title: str,
    author: str | None,
    translator: str | None = None,
    publisher: str | None = None,
    isbn: str | None = None,
    douban_url: str | None,
    fmt: str | None = None,
    add_to_shelf: bool = True,
    candidate: dict[str, Any] | None = None,
    shelf_item_id: int | None = None,
) -> dict[str, Any]:
    """Download ebook to cache, optionally add shelf item and send to Kindle."""
    from on1y.books.models import BookShelfUpdate
    from on1y.books.shelf import create_shelf_item, get_shelf_item, update_shelf_item

    settings: BookSettings = load_book_settings(user_id)
    cache_dir = resolve_books_cache_dir(user_id, settings.cache_dir)
    hints = EditionHints(
        title=title,
        author=author,
        translator=translator,
        publisher=publisher,
        isbn=isbn,
    )
    from on1y.books.cover import normalize_cover_url
    from on1y.books.display_name import format_book_label
    from on1y.books.shelf_metadata import resolve_shelf_metadata

    resolved_meta: dict[str, Any] | None = None
    kindle_label = format_book_label(
        title=title,
        author=author,
        translator=translator,
        publisher=publisher,
    )
    file_label: str | None = None
    if isinstance(candidate, dict):
        cover_for_meta = normalize_cover_url(str(candidate.get("cover_url") or "").strip() or None)
        resolved_meta = resolve_shelf_metadata(hints, candidate, cover_url=cover_for_meta)
        kindle_label = format_book_label(
            title=str(resolved_meta.get("title") or title),
            author=resolved_meta.get("author"),
            translator=resolved_meta.get("translator"),
            publisher=resolved_meta.get("publisher"),
            language=resolved_meta.get("language"),
        )
        file_label = kindle_label

    local_path, source, match_meta = download_book_file(
        user_id,
        hints=hints,
        fmt=fmt,
        cache_dir=cache_dir,
        settings=settings,
        candidate=candidate,
        file_label=file_label,
    )
    book_fmt = str(match_meta.get("format") or fmt or settings.preferred_format or "epub").lower()

    kindle_sent, kindle_status, kindle_detail = maybe_send_kindle(user_id, local_path, title=kindle_label)

    shelf_item: BookShelfItem | None = None
    shelf_title = title
    resolved_quality = match_meta.get("match_quality")
    if add_to_shelf:
        meta = resolved_meta
        if meta is None:
            cover_url: str | None = None
            if isinstance(candidate, dict):
                cover_url = normalize_cover_url(str(candidate.get("cover_url") or "").strip() or None)
            meta = resolve_shelf_metadata(hints, candidate if isinstance(candidate, dict) else None, cover_url=cover_url)
        shelf_title = str(meta["title"] or title).strip() or title
        resolved_quality = meta.get("match_quality") or resolved_quality

        if douban_url:
            links = build_edition_links(
                title=shelf_title,
                douban_url=douban_url,
                zlib_base_url=ZLIB_BASE,
            )
            if not meta.get("douban_enrich"):
                links = [
                    BookLink(label="豆瓣（检索参考）", url=douban_url),
                    *[link for link in links if link.label != "豆瓣"],
                ]
        else:
            links = [
                BookLink(label=book_fmt.upper(), url=zlib_search_url(shelf_title, book_fmt, base_url=ZLIB_BASE))
            ]
        notes = (
            f"cached: {local_path}\n"
            f"source: {source}\n"
            f"match: {meta.get('match_quality', match_meta.get('match_quality', 'unknown'))}"
        )
        extra = str(meta.get("notes_extra") or "").strip()
        if extra:
            notes += f"\n{extra}"
        from on1y.books.kindle_notes import merge_kindle_status

        notes = merge_kindle_status(notes, kindle_status, kindle_detail)
        if shelf_item_id:
            existing = get_shelf_item(storage, user_id, shelf_item_id)
            if existing is None:
                raise ConfigurationError("书架条目不存在")
            shelf_item = update_shelf_item(
                storage,
                user_id,
                shelf_item_id,
                BookShelfUpdate(
                    title=shelf_title,
                    author=meta.get("author"),
                    translator=meta.get("translator"),
                    publisher=meta.get("publisher"),
                    cover_url=normalize_cover_url(meta.get("cover_url")),
                    summary=meta.get("summary"),
                    notes=notes,
                    cached_format=book_fmt,
                ),
            )
        else:
            shelf_item = create_shelf_item(
                storage,
                user_id,
                BookShelfCreate(
                    title=shelf_title,
                    author=meta.get("author"),
                    translator=meta.get("translator"),
                    publisher=meta.get("publisher"),
                    cover_url=normalize_cover_url(meta.get("cover_url")),
                    summary=meta.get("summary"),
                    links=links,
                    notes=notes,
                    cached_format=book_fmt,
                ),
            )
        try:
            from on1y.books.knowledge_sync import prepare_shelf_item

            shelf_item = prepare_shelf_item(storage, user_id, shelf_item)
        except Exception as exc:
            logger.warning("Shelf sync after acquire failed for %r: %s", shelf_title, exc)

    validation = match_meta.get("validation") or {}
    size_bytes = int(validation.get("size_bytes") or local_path.stat().st_size)

    return {
        "ok": True,
        "format": book_fmt,
        "local_path": str(local_path),
        "source": source,
        "kindle_sent": kindle_sent,
        "kindle_status": kindle_status,
        "kindle_detail": kindle_detail,
        "matched_title": shelf_title if add_to_shelf else match_meta.get("matched_title"),
        "matched_author": match_meta.get("matched_author"),
        "match_quality": resolved_quality,
        "search_query": match_meta.get("search_query"),
        "file_size_bytes": size_bytes,
        "validation_ok": bool(validation.get("ok", True)),
        "validation_detail": validation.get("detail"),
        "acquire_strategy": settings.acquire_strategy,
        "shelf_item": shelf_item.model_dump() if shelf_item else None,
    }
