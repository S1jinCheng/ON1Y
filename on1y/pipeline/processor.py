"""Process a single URL: extract → persist raw_items."""

from __future__ import annotations

import logging
from typing import Any

from on1y.config import get_settings
from on1y.extract.registry import ExtractorRegistry, get_default_registry
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItem, RawItemCreate
from on1y.ports.storage import StoragePort
from on1y.utils.author_meta import author_meta_patch
from on1y.utils.platform import PLATFORM_ZHIHU, detect_platform, normalize_url

logger = logging.getLogger(__name__)


def process_url(
    storage: StoragePort,
    url: str,
    *,
    source: SourceType = SourceType.MANUAL,
    source_meta: dict | None = None,
    registry: ExtractorRegistry | None = None,
    preferred_body_text: str | None = None,
    preferred_title: str | None = None,
    preferred_source_meta: dict[str, Any] | None = None,
) -> RawItem:
    """
    Extract content from URL and upsert into raw_items.
    Does not modify pending_urls; the worker handles queue state separately.
    """
    settings = get_settings()
    registry = registry or get_default_registry()
    normalized = normalize_url(url)
    meta = source_meta or {}
    preferred_text = (preferred_body_text or "").strip()
    if preferred_source_meta:
        meta.update(preferred_source_meta)
    if preferred_text:
        platform = detect_platform(normalized)
        if preferred_title and preferred_title.strip():
            meta.setdefault("clip_title", preferred_title.strip())
        meta.setdefault("extract_strategy", "selected_text")
        create = RawItemCreate(
            url=normalized,
            platform=platform,
            source=source,
            raw_title=(preferred_title or "").strip() or None,
            body_text=preferred_text,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            extract_error=None,
            source_meta=meta,
        )
        raw = storage.upsert_raw_item(create)
        logger.info("Stored preferred-text raw_item id=%s url=%s", raw.id, normalized)
        from on1y.distill.processor import maybe_package_short_content

        maybe_package_short_content(storage, raw.id, raw.body_text)
        return raw

    from on1y.utils.platform import is_ytdlp_video_platform

    if is_ytdlp_video_platform(detect_platform(normalized)):
        from on1y.pipeline.video import process_video_fast

        return process_video_fast(
            storage,
            normalized,
            source=source,
            source_meta=meta,
        )

    logger.info("Extracting %s", normalized)
    result = registry.extract(normalized)
    result = result.truncated(settings.max_body_chars)
    platform = detect_platform(normalized)
    meta.update(
        author_meta_patch(
            author=result.author,
            author_avatar=result.author_avatar,
            author_url=result.author_url,
        )
    )
    if result.source_meta:
        meta.update(result.source_meta)
    if platform == PLATFORM_ZHIHU:
        from on1y.utils.zhihu_author import enrich_zhihu_author_meta
        from on1y.utils.zhihu_title import resolve_zhihu_title

        meta = enrich_zhihu_author_meta(meta, normalized)
        resolved_title = resolve_zhihu_title(normalized, result.raw_title, meta)
    else:
        resolved_title = result.raw_title
    if preferred_title and preferred_title.strip():
        resolved_title = preferred_title.strip()

    create = RawItemCreate(
        url=normalized,
        platform=platform,
        source=source,
        raw_title=resolved_title,
        body_text=result.body_text,
        content_type=result.content_type,
        extract_status=result.extract_status,
        extract_error=result.extract_error,
        source_meta=meta,
    )
    raw = storage.upsert_raw_item(create)
    logger.info(
        "Stored raw_item id=%s platform=%s status=%s words=%s",
        raw.id,
        raw.platform,
        raw.extract_status.value,
        raw.word_count,
    )
    from on1y.distill.processor import maybe_package_short_content

    maybe_package_short_content(storage, raw.id, raw.body_text)
    return raw
