"""Drain historical queues: fast ingest all pending URLs + fetch all subtitles."""

from __future__ import annotations

import logging
import time

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.pipeline.backfill import backfill_video_subtitle_jobs
from on1y.pipeline.subtitle_worker import run_subtitle_batch
from on1y.pipeline.worker import run_worker_batch

logger = logging.getLogger(__name__)


def run_catchup(
    storage: SqliteStorage,
    *,
    ingest_batch: int = 20,
    subtitle_batch: int = 10,
    max_rounds: int = 500,
    pause_seconds: float = 1.0,
) -> dict[str, object]:
    """
    Loop until pending_urls and pending_subtitles queues are empty (or max_rounds).
    Does NOT run LLM distill.
    """
    backfilled = backfill_video_subtitle_jobs(storage)
    totals = {
        "ingest_processed": 0,
        "ingest_failed": 0,
        "subtitle_processed": 0,
        "subtitle_failed": 0,
        "rounds": 0,
        "backfill_initial": backfilled,
    }

    for round_num in range(1, max_rounds + 1):
        pending = storage.count_pending_by_status().get("pending", 0)
        subs_pending = storage.count_subtitles_by_status().get("pending", 0)

        if pending == 0 and subs_pending == 0:
            totals["rounds"] = round_num - 1
            break

        logger.info(
            "Catchup round %s: pending_urls=%s pending_subtitles=%s",
            round_num,
            pending,
            subs_pending,
        )

        if pending > 0:
            ingest = run_worker_batch(storage, min(ingest_batch, pending))
            totals["ingest_processed"] += ingest["processed"]
            totals["ingest_failed"] += ingest["failed"]

        if round_num % 3 == 0:
            backfill_video_subtitle_jobs(storage)

        subs_pending = storage.count_subtitles_by_status().get("pending", 0)
        if subs_pending > 0:
            subs = run_subtitle_batch(storage, min(subtitle_batch, subs_pending))
            totals["subtitle_processed"] += subs["processed"]
            totals["subtitle_failed"] += subs["failed"]

        totals["rounds"] = round_num

        if pause_seconds > 0:
            time.sleep(pause_seconds)

    totals["queue_pending"] = storage.count_pending_by_status()
    totals["queue_subtitles"] = storage.count_subtitles_by_status()
    totals["raw_count"] = storage.count_raw_items()
    return totals
