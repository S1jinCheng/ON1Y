"""Drain video pending_urls (YouTube / Bilibili) without touching Zhihu queue."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from on1y.adapters.sqlite_storage import SqliteStorage, get_storage
from on1y.pipeline.backfill import backfill_video_subtitle_jobs
from on1y.pipeline.subtitle_worker import run_subtitle_batch
from on1y.pipeline.worker import run_worker_batch
from on1y.utils.platform import PLATFORM_BILIBILI, PLATFORM_YOUTUBE, YTDLP_VIDEO_PLATFORMS

logger = logging.getLogger(__name__)


def _video_pending_count(storage: SqliteStorage) -> int:
    total = 0
    for platform in YTDLP_VIDEO_PLATFORMS:
        total += storage.count_pending_for_platform(platform)
    return total


def _subtitle_round_for_platform(platform: str, batch_size: int) -> dict[str, int]:
    storage = get_storage()
    try:
        pending = storage.count_pending_subtitles_for_platform(platform)
        if pending <= 0:
            return {"processed": 0, "failed": 0}
        return run_subtitle_batch(storage, min(batch_size, pending), platform=platform)
    finally:
        storage.close()


def run_video_catchup(
    storage: SqliteStorage,
    *,
    ingest_per_round: int = 5,
    subtitle_per_round: int = 3,
    max_rounds: int = 500,
    pause_seconds: float = 2.0,
    parallel_subtitles: bool = True,
) -> dict[str, object]:
    """Process YouTube/Bilibili ingest + subtitle queues until empty."""
    totals: dict[str, object] = {
        "ingest_processed": 0,
        "ingest_failed": 0,
        "subtitle_processed": 0,
        "subtitle_failed": 0,
        "rounds": 0,
        "by_platform": {p: {"processed": 0, "failed": 0} for p in YTDLP_VIDEO_PLATFORMS},
    }

    for round_num in range(1, max_rounds + 1):
        pending = _video_pending_count(storage)
        subs_pending = sum(
            storage.count_pending_subtitles_for_platform(p) for p in YTDLP_VIDEO_PLATFORMS
        )
        if pending == 0 and subs_pending == 0:
            totals["rounds"] = round_num - 1
            break

        logger.info(
            "Video catchup round %s: video_pending=%s subtitle_pending=%s",
            round_num,
            pending,
            subs_pending,
        )

        if pending > 0:
            per_platform = max(1, ingest_per_round // len(YTDLP_VIDEO_PLATFORMS))
            for platform in (PLATFORM_BILIBILI, PLATFORM_YOUTUBE):
                if storage.count_pending_for_platform(platform) <= 0:
                    continue
                result = run_worker_batch(storage, per_platform, platform=platform)
                totals["ingest_processed"] = int(totals["ingest_processed"]) + result["processed"]
                totals["ingest_failed"] = int(totals["ingest_failed"]) + result["failed"]
                plat = totals["by_platform"][platform]
                plat["processed"] = int(plat["processed"]) + result["processed"]
                plat["failed"] = int(plat["failed"]) + result["failed"]

        if round_num % 3 == 0:
            for platform in YTDLP_VIDEO_PLATFORMS:
                backfill_video_subtitle_jobs(storage, platform=platform)

        subs_pending = sum(
            storage.count_pending_subtitles_for_platform(p) for p in YTDLP_VIDEO_PLATFORMS
        )
        if subs_pending > 0:
            per_platform_batch = max(1, subtitle_per_round // len(YTDLP_VIDEO_PLATFORMS))
            if parallel_subtitles:
                with ThreadPoolExecutor(max_workers=len(YTDLP_VIDEO_PLATFORMS)) as pool:
                    futures = {
                        pool.submit(_subtitle_round_for_platform, platform, per_platform_batch): platform
                        for platform in YTDLP_VIDEO_PLATFORMS
                        if storage.count_pending_subtitles_for_platform(platform) > 0
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        totals["subtitle_processed"] = int(totals["subtitle_processed"]) + result[
                            "processed"
                        ]
                        totals["subtitle_failed"] = int(totals["subtitle_failed"]) + result["failed"]
            else:
                for platform in YTDLP_VIDEO_PLATFORMS:
                    pending_plat = storage.count_pending_subtitles_for_platform(platform)
                    if pending_plat <= 0:
                        continue
                    subs = run_subtitle_batch(
                        storage,
                        min(per_platform_batch, pending_plat),
                        platform=platform,
                    )
                    totals["subtitle_processed"] = int(totals["subtitle_processed"]) + subs["processed"]
                    totals["subtitle_failed"] = int(totals["subtitle_failed"]) + subs["failed"]

        totals["rounds"] = round_num
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    totals["queue_video_pending"] = {
        p: storage.count_pending_for_platform(p) for p in YTDLP_VIDEO_PLATFORMS
    }
    totals["queue_subtitles"] = {
        p: storage.count_pending_subtitles_for_platform(p) for p in YTDLP_VIDEO_PLATFORMS
    }
    return totals
