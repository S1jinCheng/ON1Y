"""Video platforms: fast metadata ingest + async subtitle queue."""

from __future__ import annotations

import logging

from on1y.config import get_settings
from on1y.extract.subtitles import build_video_body
from on1y.extract.ytdlp_video import get_ytdlp_video_extractor
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItem, RawItemCreate
from on1y.pipeline.video_meta import (
    SUBTITLE_STATUS_PENDING,
    VIDEO_DESCRIPTION,
    with_subtitle_pending,
)
from on1y.ports.storage import StoragePort
from on1y.exceptions import DuplicateVideoError
from on1y.pipeline.video_author import enrich_video_source_meta
from on1y.utils.bilibili_url import normalize_bilibili_url
from on1y.utils.platform import PLATFORM_BILIBILI, YTDLP_VIDEO_PLATFORMS, detect_platform, normalize_url
from on1y.utils.video_dedup import find_youtube_duplicate, remove_bilibili_duplicate_of_youtube

logger = logging.getLogger(__name__)


def process_video_fast(
    storage: StoragePort,
    url: str,
    *,
    source: SourceType = SourceType.MANUAL,
    source_meta: dict | None = None,
) -> RawItem:
    """
    Phase A for yt-dlp video platforms: metadata-only ingest, enqueue subtitles.
    """
    normalized = normalize_url(url)
    platform = detect_platform(normalized)
    if platform == PLATFORM_BILIBILI:
        normalized = normalize_bilibili_url(normalized)
    if platform not in YTDLP_VIDEO_PLATFORMS:
        raise ValueError(f"not a yt-dlp video URL: {url}")

    settings = get_settings()
    extractor = get_ytdlp_video_extractor(platform)
    meta = extractor.fetch_metadata(normalized)

    if platform == PLATFORM_BILIBILI:
        dup_yt = find_youtube_duplicate(
            storage,
            title=meta.title,
            duration_sec=meta.duration_sec,
            description=meta.description,
        )
        if dup_yt is not None:
            remove_bilibili_duplicate_of_youtube(storage, normalized)
            raise DuplicateVideoError(
                f"Bilibili duplicate of YouTube raw_id={dup_yt}",
                url=normalized,
                preferred_raw_id=dup_yt,
            )

    body, _reason = build_video_body(
        title=meta.title,
        subtitle_text="",
        description=meta.description or None,
        langs_found=[],
    )
    if not body:
        raise extractor._fail(
            normalized,
            f"No title or description from {platform} metadata",
            platform=platform,
        )

    meta_dict = with_subtitle_pending(dict(source_meta or {}))
    if meta.description:
        meta_dict[VIDEO_DESCRIPTION] = meta.description[:50_000]
    meta_dict = enrich_video_source_meta(meta_dict, platform=platform, url=normalized)
    if meta.video_id:
        meta_dict["video_id"] = str(meta.video_id)
    if meta.duration_sec:
        meta_dict["duration_sec"] = int(meta.duration_sec)

    create = RawItemCreate(
        url=normalized,
        platform=platform,
        source=source,
        raw_title=meta.title,
        body_text=body[: settings.max_body_chars],
        content_type=ContentType.VIDEO,
        extract_status=ExtractStatus.PARTIAL,
        extract_error="awaiting_subtitles",
        source_meta=meta_dict,
    )
    raw = storage.upsert_raw_item(create)
    storage.enqueue_subtitle_job(raw.id, normalized)
    logger.info(
        "Video fast ingest platform=%s raw_id=%s subtitle_status=%s words=%s",
        platform,
        raw.id,
        SUBTITLE_STATUS_PENDING,
        raw.word_count,
    )
    return raw


def process_youtube_fast(
    storage: StoragePort,
    url: str,
    *,
    source: SourceType = SourceType.MANUAL,
    source_meta: dict | None = None,
) -> RawItem:
    """Backward-compatible alias."""
    return process_video_fast(storage, url, source=source, source_meta=source_meta)
