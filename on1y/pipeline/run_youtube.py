"""End-to-end YouTube pipeline: ingest → subtitles → distill."""

from __future__ import annotations

import logging

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.config import get_settings
from on1y.distill.processor import distill_raw_item, list_undistilled_raw_ids
from on1y.pipeline.subtitle_worker import run_subtitle_batch
from on1y.pipeline.worker import run_worker_batch

logger = logging.getLogger(__name__)


def run_youtube_pipeline(
    storage: SqliteStorage,
    *,
    ingest_limit: int = 10,
    subtitle_limit: int = 10,
    distill_limit: int = 5,
) -> dict[str, object]:
    """
    Run three phases in order (each respects its limit).
    Use after `on1y rss poll` to drain YouTube-heavy queues.
    """
    ingest = run_worker_batch(storage, ingest_limit)
    subtitles = run_subtitle_batch(storage, subtitle_limit)
    distilled_ok = 0
    distilled_failed = 0
    if distill_limit > 0:
        ids = list_undistilled_raw_ids(storage, limit=distill_limit)
        for raw_id in ids:
            try:
                distill_raw_item(storage, raw_id)
                distilled_ok += 1
            except Exception as exc:
                distilled_failed += 1
                logger.error("Distill failed raw_id=%s: %s", raw_id, exc)
    return {
        "ingest": ingest,
        "subtitles": subtitles,
        "distilled": distilled_ok,
        "distill_failed": distilled_failed,
    }
