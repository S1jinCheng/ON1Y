"""Persist and reload Economist EPUB previews (SQLite + local EPUB cache)."""

from __future__ import annotations

import logging
from typing import Any

from on1y.config import Settings, get_settings
from on1y.hotlist.constants import HOTLIST_ECONOMIST
from on1y.hotlist.economist_urls import resolve_economist_epub_url, strip_legacy_economist_body
from on1y.hotlist.epub_preview import build_economist_preview, economist_epub_cache_path
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.ports.storage import StoragePort

logger = logging.getLogger(__name__)

PLATFORM_ECONOMIST = "economist"


def preview_is_complete(body_text: str | None, meta: dict[str, Any] | None) -> bool:
    """True when summary/body already extracted from EPUB (no re-sync needed)."""
    meta = meta or {}
    if int(meta.get("preview_chars") or 0) >= 200:
        return True
    if meta.get("epub_preview_ok") is True:
        return True
    body = strip_legacy_economist_body(body_text or "")
    if len(body) < 200:
        return False
    if body.startswith("EPUB") and "下载" in body[:20]:
        return False
    return True


def _distilled_summary(storage: StoragePort, raw_id: int) -> str:
    detail = storage.get_distilled_detail(raw_id)
    if not detail:
        return ""
    return str(detail.get("summary") or "").strip()


def ensure_economist_preview(
    storage: StoragePort,
    raw_id: int,
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> bool:
    """
    Ensure raw_items + distilled hold EPUB-derived summary and body.
    Uses data/economist/{edition_date}.epub cache; network only if cache missing.
    Returns True if preview is available after this call.
    """
    settings = settings or get_settings()
    raw = storage.get_raw_by_id(raw_id)
    if raw is None or str(raw.platform) != PLATFORM_ECONOMIST:
        return False

    meta = dict(raw.source_meta or {})
    edition_date = str(meta.get("edition_date") or meta.get("heat_text") or "").strip()
    epub_url = resolve_economist_epub_url(str(raw.url), meta)
    if not edition_date or not epub_url:
        return False

    if not force and preview_is_complete(raw.body_text, meta):
        return True

    cached = economist_epub_cache_path(settings, edition_date)
    if not force and not cached.is_file():
        logger.info(
            "Economist %s: no EPUB cache at %s; run hot-list sync once",
            edition_date,
            cached,
        )
        return preview_is_complete(raw.body_text, meta)

    try:
        preview_meta = build_economist_preview(epub_url, edition_date, settings=settings)
    except Exception as exc:
        logger.warning("Economist preview build failed raw_id=%s: %s", raw_id, exc)
        return preview_is_complete(raw.body_text, meta)

    body_text = str(preview_meta.get("body_text") or "")
    summary = str(preview_meta.get("summary") or "")
    excerpt = str(preview_meta.get("excerpt") or "")
    meta.update(
        {
            "epub_url": epub_url,
            "edition_date": edition_date,
            "chapter_count": preview_meta.get("chapter_count"),
            "preview_chars": preview_meta.get("preview_chars"),
            "epub_preview_ok": bool(body_text.strip() or preview_meta.get("chapters")),
            "epub_cached": cached.is_file(),
        }
    )

    storage.upsert_raw_item(
        RawItemCreate(
            url=epub_url,
            platform=PLATFORM_ECONOMIST,
            source=SourceType.RSS,
            raw_title=raw.raw_title,
            body_text=body_text,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta=meta,
        )
    )
    if summary or body_text:
        storage.upsert_distilled(
            raw_id=raw_id,
            summary=summary or raw.raw_title or edition_date,
            key_points=list(preview_meta.get("chapters") or [])[:12],
            topics=[],
            model=None,
            prompt_version="hotlist-v1",
            status="ok",
            error=None,
            reader_text=body_text,
        )
    return preview_is_complete(body_text, meta)


def list_synced_edition_dates(storage: StoragePort, *, limit: int = 120) -> set[str]:
    if hasattr(storage, "list_hotlist_dates"):
        dates = storage.list_hotlist_dates(  # type: ignore[attr-defined]
            hotlist_source=HOTLIST_ECONOMIST, limit=limit
        )
        return {str(d) for d in dates if d}
    return set()
