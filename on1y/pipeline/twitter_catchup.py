"""Drain Twitter pending_urls with rate-limited Playwright batches."""

from __future__ import annotations

import logging

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.pipeline.twitter_worker import run_twitter_worker_batch
from on1y.utils.platform import PLATFORM_TWITTER

logger = logging.getLogger(__name__)


def run_twitter_catchup(
    storage: SqliteStorage,
    *,
    ingest_per_round: int = 1,
    max_rounds: int = 500,
    stop_on_antibot: bool = True,
) -> dict[str, object]:
    totals: dict[str, object] = {
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "rounds": 0,
        "antibot_stopped": False,
    }

    for round_num in range(1, max_rounds + 1):
        pending = storage.count_pending_for_platform(PLATFORM_TWITTER)
        if pending == 0:
            totals["rounds"] = round_num - 1
            break

        logger.info("Twitter catchup round %s: pending=%s", round_num, pending)
        result = run_twitter_worker_batch(storage, ingest_per_round)
        totals["processed"] = int(totals["processed"]) + int(result["processed"])
        totals["failed"] = int(totals["failed"]) + int(result["failed"])
        totals["skipped"] = int(totals["skipped"]) + int(result["skipped"])
        totals["rounds"] = round_num

        if result["antibot_stopped"]:
            totals["antibot_stopped"] = True
            if stop_on_antibot:
                break

        if result["processed"] == 0 and result["failed"] == 0:
            break

    totals["queue_pending"] = storage.count_pending_for_platform(PLATFORM_TWITTER)
    return totals
