"""Backfill subtitle jobs for video items ingested before decoupled pipeline."""

from __future__ import annotations

import logging

from on1y.pipeline.video_meta import with_subtitle_pending

from on1y.ports.storage import StoragePort

logger = logging.getLogger(__name__)


def backfill_video_subtitle_jobs(
    storage: StoragePort, *, platform: str | None = None
) -> int:
    """Enqueue subtitle fetch for video raw_items missing subtitle_status=ready."""
    from on1y.adapters.sqlite_storage import SqliteStorage

    if not isinstance(storage, SqliteStorage):
        raise TypeError("backfill requires SqliteStorage")

    rows = storage.list_video_raw_needing_subtitles(platform)
    enqueued = 0
    for raw_id, url in rows:
        raw = storage.get_raw_by_id(raw_id)
        if raw is None:
            continue
        storage.enqueue_subtitle_job(raw_id, url)
        meta = with_subtitle_pending(raw.source_meta)
        storage.update_raw_item_content(
            raw_id,
            body_text=raw.body_text,
            raw_title=raw.raw_title,
            extract_status=raw.extract_status,
            extract_error=raw.extract_error,
            source_meta=meta,
        )
        enqueued += 1
        logger.info("Backfill subtitle job raw_id=%s platform=%s", raw_id, raw.platform)
    return enqueued


def backfill_youtube_subtitle_jobs(storage: StoragePort) -> int:
    """Backward-compatible alias."""
    return backfill_video_subtitle_jobs(storage)
