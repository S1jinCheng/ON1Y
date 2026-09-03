"""Run ingest, subtitle fetch, and LLM distill concurrently on separate queues."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

IDLE_POLL_SECONDS = 0.5
IDLE_ROUNDS_TO_STOP = 24  # ~12s idle after workers drain in-flight jobs
STALE_PROCESSING_MINUTES = 10


def _open_storage():
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.config import get_settings

    storage = SqliteStorage(get_settings().db_path)
    storage.initialize()
    return storage


def _pipeline_has_work(
    storage: Any,
    *,
    platforms: list[str],
    distill_enabled: bool,
) -> bool:
    from on1y.distill.prompts import PROMPT_VERSION

    for platform in platforms:
        if storage.count_pending_for_platform(platform) > 0:
            return True
        if storage.count_pending_for_platform(platform, status="processing") > 0:
            return True
    sub_counts = storage.count_subtitles_by_status()
    if int(sub_counts.get("pending", 0)) > 0:
        return True
    if int(sub_counts.get("processing", 0)) > 0:
        return True
    if distill_enabled:
        if storage.count_raw_ids_needing_distill(prompt_version=PROMPT_VERSION, platform=None) > 0:
            return True
    return False


def _ingest_worker(
    *,
    user_id: int,
    platforms: list[str],
    batch_size: int,
    stop_event: threading.Event,
    stats: dict[str, Any],
    stats_lock: threading.Lock,
) -> None:
    from on1y.auth.context import user_context
    from on1y.pipeline.zhihu_catchup import run_zhihu_catchup
    from on1y.sync.full_sync import _pipeline_ingest_batch
    from on1y.sync.progress import get_cold_start_progress

    storage = _open_storage()
    progress = get_cold_start_progress()
    try:
        with user_context(user_id):
            while not stop_event.is_set():
                did_work = False
                for platform in platforms:
                    if stop_event.is_set():
                        break
                    if storage.count_pending_for_platform(platform) <= 0:
                        continue
                    if platform == "zhihu":
                        result = run_zhihu_catchup(
                            storage,
                            ingest_per_round=batch_size,
                            max_rounds=1,
                        )
                    elif platform == "twitter":
                        from on1y.pipeline.twitter_catchup import run_twitter_catchup

                        result = run_twitter_catchup(
                            storage,
                            ingest_per_round=batch_size,
                            max_rounds=1,
                        )
                    else:
                        result = _pipeline_ingest_batch(
                            storage,
                            platform=platform,
                            limit=batch_size,
                            progress=progress,
                        )
                    processed = int(result.get("processed", 0))
                    failed = int(result.get("failed", 0))
                    if processed or failed:
                        did_work = True
                        with stats_lock:
                            plat = stats["ingest"].setdefault(
                                platform, {"processed": 0, "failed": 0}
                            )
                            plat["processed"] += processed
                            plat["failed"] += failed
                if not did_work:
                    time.sleep(IDLE_POLL_SECONDS)
    finally:
        storage.close()


def _subtitle_worker(
    *,
    user_id: int,
    batch_size: int,
    stop_event: threading.Event,
    stats: dict[str, Any],
    stats_lock: threading.Lock,
) -> None:
    from on1y.auth.context import user_context
    from on1y.pipeline.subtitle_worker import run_subtitle_batch
    from on1y.extract.youtube_rate_limit import youtube_subtitle_pause_remaining

    storage = _open_storage()
    try:
        with user_context(user_id):
            while not stop_event.is_set():
                result = run_subtitle_batch(
                    storage,
                    batch_size,
                    platform=None,
                    auto_distill=False,
                )
                if result.get("paused"):
                    time.sleep(min(30.0, max(1.0, youtube_subtitle_pause_remaining())))
                    continue
                processed = int(result.get("processed", 0))
                failed = int(result.get("failed", 0))
                if processed == 0 and failed == 0:
                    time.sleep(IDLE_POLL_SECONDS)
                    continue
                with stats_lock:
                    stats["subtitles"]["processed"] += processed
                    stats["subtitles"]["failed"] += failed
    finally:
        storage.close()


def _distill_worker(
    *,
    user_id: int,
    batch_size: int,
    stop_event: threading.Event,
    stats: dict[str, Any],
    stats_lock: threading.Lock,
) -> None:
    from on1y.auth.context import user_context
    from on1y.distill.processor import distill_raw_item, list_distill_candidate_ids
    from on1y.sync.progress import get_cold_start_progress

    storage = _open_storage()
    progress = get_cold_start_progress()
    try:
        with user_context(user_id):
            while not stop_event.is_set():
                ids = list_distill_candidate_ids(storage, limit=batch_size, platform=None)
                if not ids:
                    time.sleep(IDLE_POLL_SECONDS)
                    continue
                for raw_id in ids:
                    if stop_event.is_set():
                        break
                    raw = storage.get_raw_by_id(raw_id)
                    title = (getattr(raw, "raw_title", None) if raw else None) or f"#{raw_id}"
                    plat = (raw.platform if raw else None) or "unknown"
                    try:
                        distill_raw_item(storage, raw_id)
                        with stats_lock:
                            stats["distill"]["distilled"] += 1
                        progress and progress.log_item(
                            phase="pipeline",
                            title=title,
                            platform=plat,
                            status="distilled",
                        )
                    except Exception as exc:
                        with stats_lock:
                            stats["distill"]["failed"] += 1
                        progress and progress.log_item(
                            phase="pipeline",
                            title=title,
                            platform=plat,
                            status="failed",
                            detail=str(exc),
                        )
    finally:
        storage.close()


def _reclaim_stale_processing(storage: Any) -> dict[str, int]:
    """Reset orphaned processing rows left by killed workers."""
    reclaimed = {"pending_urls": 0, "pending_subtitles": 0}
    reclaim = getattr(storage, "reclaim_stale_processing_jobs", None)
    if callable(reclaim):
        try:
            out = reclaim(older_than_minutes=STALE_PROCESSING_MINUTES)
            if isinstance(out, dict):
                reclaimed.update(out)
        except Exception:
            logger.debug("reclaim_stale_processing_jobs failed", exc_info=True)
    return reclaimed


def run_parallel_pipeline(
    storage: Any,
    *,
    user_id: int,
    platforms: list[str],
    batch_size: int = 25,
    timer: Any | None = None,
    use_ai_summary: bool = True,
    poll_active: threading.Event | None = None,
) -> dict[str, Any]:
    """Ingest, subtitles, and distill run on three threads until all queues drain."""
    from on1y.auth.context import user_context
    from on1y.llm.settings import resolve_llm_settings
    from on1y.sync.progress import get_cold_start_progress
    from on1y.sync.timing import SyncTimer, rollup_phase_totals

    with user_context(user_id):
        reclaimed = _reclaim_stale_processing(storage)
    if reclaimed.get("pending_urls") or reclaimed.get("pending_subtitles"):
        logger.info("Reclaimed stale processing jobs: %s", reclaimed)

    phase_timer = timer or SyncTimer()
    progress = get_cold_start_progress()
    progress and progress.set_phase("pipeline", detail="拉取、字幕与 AI 摘要并行处理")

    distill_enabled = use_ai_summary and resolve_llm_settings(user_id=user_id).api_key_set
    stop_event = threading.Event()
    stats_lock = threading.Lock()
    totals: dict[str, Any] = {
        "mode": "parallel",
        "ingest": {},
        "subtitles": {"processed": 0, "failed": 0},
        "distill": {"distilled": 0, "failed": 0, "enabled": distill_enabled},
    }

    workers: list[threading.Thread] = [
        threading.Thread(
            target=_ingest_worker,
            kwargs={
                "user_id": user_id,
                "platforms": platforms,
                "batch_size": batch_size,
                "stop_event": stop_event,
                "stats": totals,
                "stats_lock": stats_lock,
            },
            name="on1y-pipeline-ingest",
            daemon=True,
        ),
        threading.Thread(
            target=_subtitle_worker,
            kwargs={
                "user_id": user_id,
                "batch_size": batch_size,
                "stop_event": stop_event,
                "stats": totals,
                "stats_lock": stats_lock,
            },
            name="on1y-pipeline-subtitles",
            daemon=True,
        ),
    ]
    if distill_enabled:
        workers.append(
            threading.Thread(
                target=_distill_worker,
                kwargs={
                    "user_id": user_id,
                    "batch_size": max(3, batch_size // 5),
                    "stop_event": stop_event,
                    "stats": totals,
                    "stats_lock": stats_lock,
                },
                name="on1y-pipeline-distill",
                daemon=True,
            )
        )

    started = time.perf_counter()
    with phase_timer.span("pipeline.parallel"):
        for worker in workers:
            worker.start()

        idle_rounds = 0
        probe = _open_storage()
        try:
            with user_context(user_id):
                while idle_rounds < IDLE_ROUNDS_TO_STOP:
                    has_work = _pipeline_has_work(
                        probe,
                        platforms=platforms,
                        distill_enabled=distill_enabled,
                    )
                    if has_work:
                        idle_rounds = 0
                    elif poll_active is not None and poll_active.is_set():
                        # Subscription poll still running; new URLs may arrive soon.
                        idle_rounds = 0
                    else:
                        idle_rounds += 1
                    if idle_rounds >= IDLE_ROUNDS_TO_STOP:
                        break
                    time.sleep(IDLE_POLL_SECONDS)
        finally:
            probe.close()

        stop_event.set()
        for worker in workers:
            worker.join(timeout=120.0)
            if worker.is_alive():
                logger.warning("Pipeline worker %s did not exit cleanly", worker.name)

    totals["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    _set_progress_phases(phase_timer, progress)
    return totals


def _set_progress_phases(phase_timer: Any, progress: Any | None) -> None:
    from on1y.sync.full_sync import _set_sync_progress
    from on1y.sync.timing import rollup_phase_totals

    _set_sync_progress(phase="pipeline", phases_ms=rollup_phase_totals(phase_timer.spans_ms))
