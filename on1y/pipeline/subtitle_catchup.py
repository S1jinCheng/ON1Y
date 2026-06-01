"""Platform-scoped subtitle catchup (YouTube and Bilibili in parallel)."""

from __future__ import annotations

import logging
import time

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.pipeline.backfill import backfill_video_subtitle_jobs
from on1y.pipeline.subtitle_worker import run_subtitle_batch

logger = logging.getLogger(__name__)


def run_subtitle_catchup(
    storage: SqliteStorage,
    platform: str,
    *,
    batch_size: int = 5,
    max_rounds: int = 500,
    pause_seconds: float = 2.0,
    backfill_every: int = 3,
) -> dict[str, object]:
    """Drain pending_subtitles for a single video platform."""
    totals: dict[str, object] = {
        "platform": platform,
        "processed": 0,
        "failed": 0,
        "backfill_enqueued": 0,
        "rounds": 0,
    }

    for round_num in range(1, max_rounds + 1):
        pending = storage.count_pending_subtitles_for_platform(platform)
        if pending == 0:
            totals["rounds"] = round_num - 1
            break

        logger.info(
            "%s subtitle catchup round %s: pending=%s",
            platform,
            round_num,
            pending,
        )

        if backfill_every > 0 and round_num % backfill_every == 1:
            enqueued = backfill_video_subtitle_jobs(storage, platform=platform)
            totals["backfill_enqueued"] = int(totals["backfill_enqueued"]) + enqueued

        result = run_subtitle_batch(
            storage,
            min(batch_size, pending),
            platform=platform,
        )
        totals["processed"] = int(totals["processed"]) + result["processed"]
        totals["failed"] = int(totals["failed"]) + result["failed"]
        totals["rounds"] = round_num

        if pause_seconds > 0:
            time.sleep(pause_seconds)

    totals["queue_pending"] = storage.count_pending_subtitles_for_platform(platform)
    return totals
