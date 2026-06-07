"""One-click full sync: all 收藏夹 + recent subscription dynamics, then ingest/distill."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.ingestion.bilibili_collections import backfill_bilibili_collections
from on1y.ingestion.bilibili_subscriptions import (
    poll_bilibili_dynamic_updates,
    sync_bilibili_up_config,
)
from on1y.ingestion.collections_sync import COLLECTIONS_PLATFORMS, parse_collections_platforms
from on1y.ingestion.zhihu_collections import backfill_zhihu_collections
from on1y.ingestion.youtube_collections import sync_youtube_collections
from on1y.ports.storage import StoragePort
from on1y.subscriptions.feeds_refresh import refresh_youtube_feeds, refresh_zhihu_follow_feeds
from on1y.subscriptions.rss_sync import sync_rss_subscriptions

logger = logging.getLogger(__name__)

# YouTube / Zhihu RSS cold-start backfill cap per feed.
VIDEOS_PER_FEED = 3
INGEST_BATCH_SIZE = 25
MAX_PIPELINE_ROUNDS = 120
COLLECTIONS_EARLY_STOP = 999_999
# Cold start: scan full folders (config default is only 80).
COLD_START_COLLECTIONS_MAX_SCAN = 500

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_report": None,
    "last_timing": None,
    "timing_history_count": 0,
    "current_phase": None,
    "phases_ms": {},
    "progress": None,
    "error": None,
    "user_id": None,
}


def _set_sync_progress(
    *,
    phase: str | None = None,
    phases_ms: dict[str, float] | None = None,
    progress: dict[str, Any] | None = None,
    clear_phase: bool = False,
) -> None:
    with _lock:
        if clear_phase:
            _state["current_phase"] = None
        elif phase is not None:
            _state["current_phase"] = phase
        if phases_ms is not None:
            _state["phases_ms"] = dict(phases_ms)
        if progress is not None:
            _state["progress"] = progress


def _on_cold_start_progress(snapshot: dict[str, Any]) -> None:
    _set_sync_progress(
        phase=str(snapshot.get("phase") or ""),
        progress=snapshot,
    )


def pipeline_bar_metrics(*, user_id: int) -> dict[str, dict[str, int]]:
    """Per-user ingest / subtitle / distill progress for the sync panel."""
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.config import get_settings
    from on1y.distill.prompts import PROMPT_VERSION

    storage = SqliteStorage(get_settings().db_path)
    storage.initialize()
    try:
        with user_context(user_id):
            pending = storage.count_pending_by_status()
            ingest_done = int(pending.get("done", 0))
            ingest_total = sum(int(pending.get(k, 0)) for k in ("pending", "processing", "done", "failed"))

            sub = storage.count_subtitles_by_status()
            subtitle_done = int(sub.get("done", 0))
            subtitle_total = sum(
                int(sub.get(k, 0)) for k in ("pending", "processing", "done", "failed")
            )

            distill_done = storage.count_distilled_items()
            distill_remaining = storage.count_raw_ids_needing_distill(
                prompt_version=PROMPT_VERSION,
                platform=None,
            )
            distill_total = distill_done + distill_remaining
    finally:
        storage.close()

    return {
        "ingest": {
            "done": ingest_done,
            "total": max(ingest_total, ingest_done),
        },
        "subtitles": {
            "done": subtitle_done,
            "total": max(subtitle_total, subtitle_done),
        },
        "distill": {
            "done": distill_done,
            "total": max(distill_total, distill_done),
        },
    }


def full_sync_status() -> dict[str, Any]:
    from on1y.auth.context import get_current_user_id, user_context
    from on1y.distill.batch_job import distill_batch_status

    with _lock:
        st = dict(_state)
    bg = distill_batch_status()
    st["background_distill"] = bg
    st["distill_running"] = bool(bg.get("running"))
    st["active"] = bool(st.get("running")) or st["distill_running"]
    if st.get("running") and st.get("started_at"):
        try:
            started = datetime.fromisoformat(str(st["started_at"]).replace("Z", "+00:00"))
            elapsed_ms = round(
                (datetime.now(timezone.utc) - started).total_seconds() * 1000,
                1,
            )
            st["elapsed_ms"] = elapsed_ms
            progress = dict(st.get("progress") or {})
            progress["elapsed_ms"] = elapsed_ms
            if st.get("current_phase") and not progress.get("phase"):
                progress["phase"] = st["current_phase"]
            st["progress"] = progress
        except (TypeError, ValueError, OSError):
            pass

    uid = get_current_user_id()
    if uid is not None:
        try:
            with user_context(uid):
                bars = pipeline_bar_metrics(user_id=uid)
            if st.get("running") and st.get("user_id") == uid:
                counters = (st.get("progress") or {}).get("counters") or {}
                enqueued = int(counters.get("enqueued", 0))
                ingested_live = int(counters.get("ingested", 0))
                distilled_live = int(counters.get("distilled", 0))
                if enqueued > bars["ingest"]["total"]:
                    bars["ingest"]["total"] = enqueued
                if ingested_live > bars["ingest"]["done"]:
                    bars["ingest"]["done"] = ingested_live
                if distilled_live > bars["distill"]["done"]:
                    bars["distill"]["done"] = distilled_live
                    bars["distill"]["total"] = max(bars["distill"]["total"], distilled_live)
            st["pipeline_bars"] = bars
        except Exception:
            logger.debug("pipeline_bar_metrics failed for user %s", uid, exc_info=True)

    return st


def full_sync_timing_history(*, limit: int = 20) -> list[dict[str, Any]]:
    from on1y.sync.timing import list_timing_history

    return list_timing_history(limit=limit)


def _sync_collections_phase(
    storage: StoragePort,
    *,
    settings: Settings,
    platforms: list[str],
    timer: Any | None = None,
) -> dict[str, Any]:
    from on1y.sync.timing import SyncTimer

    phase_timer = timer or SyncTimer()
    max_scan = COLD_START_COLLECTIONS_MAX_SCAN
    report: dict[str, Any] = {"platforms": platforms, "enqueued_total": 0}

    from on1y.sync.progress import get_cold_start_progress

    progress = get_cold_start_progress()
    for name in COLLECTIONS_PLATFORMS:
        if name not in platforms:
            continue
        progress and progress.set_phase("collections", detail=f"同步收藏夹 · {name}")
        try:
            with phase_timer.span(f"collections.{name}"):
                if name == "bilibili":
                    platform_report = backfill_bilibili_collections(
                        storage,
                        max_scan_per_folder=max_scan,
                        early_stop_existing_streak=COLLECTIONS_EARLY_STOP,
                        settings=settings,
                    )
                elif name == "zhihu":
                    platform_report = backfill_zhihu_collections(
                        storage,
                        max_scan_per_collection=max_scan,
                        early_stop_existing_streak=COLLECTIONS_EARLY_STOP,
                        settings=settings,
                    )
                else:
                    platform_report = sync_youtube_collections(
                        storage,
                        include_watch_later=settings.youtube_collections_watch_later,
                        include_liked=settings.youtube_collections_liked,
                        max_items_per_playlist=max_scan,
                        early_stop_existing_streak=COLLECTIONS_EARLY_STOP,
                        settings=settings,
                    )
            report[name] = platform_report
            report["enqueued_total"] += int(platform_report.get("enqueued") or 0)
        except ConfigurationError as exc:
            logger.warning("Full sync collections %s: %s", name, exc)
            report[name] = {"error": str(exc), "cookie_error": True}

    return report


def _bilibili_dynamic_since_ts(*, days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return int(cutoff.timestamp())


def _sync_subscriptions_phase(
    storage: StoragePort,
    *,
    settings: Settings,
    videos_per_feed: int,
    bilibili_dynamic_days: int,
    timer: Any | None = None,
) -> dict[str, Any]:
    from on1y.sync.timing import SyncTimer

    phase_timer = timer or SyncTimer()
    report: dict[str, Any] = {
        "videos_per_feed": videos_per_feed,
        "bilibili_dynamic_days": bilibili_dynamic_days,
    }

    from on1y.sync.progress import get_cold_start_progress

    progress = get_cold_start_progress()
    if settings.bilibili_up_sync_enabled:
        bilibili: dict[str, Any] = {}
        try:
            dynamic_days = bilibili_dynamic_days
            since_ts = _bilibili_dynamic_since_ts(days=dynamic_days)
            progress and progress.set_phase(
                "subscriptions",
                detail=f"B 站关注动态（近 {dynamic_days} 天）",
            )
            with phase_timer.span("subscriptions.bilibili.config"):
                bilibili["config"] = sync_bilibili_up_config(settings=settings)
            with phase_timer.span("subscriptions.bilibili.dynamic"):
                bilibili["poll"] = poll_bilibili_dynamic_updates(
                    storage,
                    settings=settings,
                    backfill=True,
                    sync_since_ts=since_ts,
                    max_pages=settings.cold_start_bilibili_dynamic_max_pages,
                )
        except ConfigurationError as exc:
            bilibili["error"] = str(exc)
        report["bilibili"] = bilibili

    for rss_platform in ("youtube", "zhihu"):
        rss_report: dict[str, Any] = {}
        try:
            progress and progress.set_phase("subscriptions", detail=f"同步订阅 · {rss_platform}")
            if rss_platform == "youtube":
                if settings.youtube_auto_refresh_channels:
                    with phase_timer.span(f"subscriptions.{rss_platform}.config"):
                        rss_report["config"] = refresh_youtube_feeds(
                            settings=settings,
                            max_channels=settings.youtube_refresh_max_channels,
                        )
                with phase_timer.span(f"subscriptions.{rss_platform}.poll"):
                    rss_report["poll"] = sync_rss_subscriptions(
                        storage,
                        platform=rss_platform,
                        backfill=True,
                        max_items_per_feed=videos_per_feed,
                        settings=settings,
                    )
            elif settings.zhihu_follow_sync_mode == "api":
                with phase_timer.span(f"subscriptions.{rss_platform}.poll"):
                    from on1y.ingestion.zhihu_subscriptions import poll_zhihu_follow_activities

                    rss_report["poll"] = poll_zhihu_follow_activities(
                        storage,
                        settings=settings,
                        backfill=True,
                    )
            else:
                if settings.zhihu_auto_refresh_follows:
                    with phase_timer.span(f"subscriptions.{rss_platform}.config"):
                        rss_report["config"] = refresh_zhihu_follow_feeds(settings=settings)
                with phase_timer.span(f"subscriptions.{rss_platform}.poll"):
                    rss_report["poll"] = sync_rss_subscriptions(
                        storage,
                        platform=rss_platform,
                        backfill=True,
                        max_items_per_feed=videos_per_feed,
                        settings=settings,
                    )
        except Exception as exc:
            logger.exception("Full sync RSS %s failed", rss_platform)
            rss_report["error"] = str(exc)
        report[rss_platform] = rss_report

    return report


def _pipeline_ingest_batch(
    storage: StoragePort,
    *,
    platform: str,
    limit: int,
    progress: Any | None,
) -> dict[str, int]:
    from on1y.extract.registry import get_default_registry
    from on1y.pipeline.worker import _process_one_pending

    registry = get_default_registry()
    processed = 0
    failed = 0
    for _ in range(max(0, limit)):
        pending = storage.claim_next_pending_for_platform(platform)
        if pending is None:
            break
        meta = pending.source_meta if isinstance(pending.source_meta, dict) else {}
        title = str(meta.get("entry_title") or meta.get("title") or pending.url).strip()
        outcome = _process_one_pending(storage, pending, registry=registry)
        if outcome == "processed":
            processed += 1
            progress and progress.log_item(
                phase="pipeline",
                title=title,
                platform=platform,
                status="ingested",
                url=pending.url,
            )
        elif outcome == "failed":
            failed += 1
            progress and progress.log_item(
                phase="pipeline",
                title=title,
                platform=platform,
                status="failed",
                url=pending.url,
            )
    return {"processed": processed, "failed": failed}


def _pipeline_distill_batch(
    storage: StoragePort,
    *,
    platform: str,
    limit: int,
    progress: Any | None,
) -> dict[str, int]:
    from on1y.distill.processor import distill_raw_item, list_distill_candidate_ids
    from on1y.llm.settings import get_resolved_llm_settings

    if not get_resolved_llm_settings().api_key_set:
        return {"distilled": 0, "failed": 0, "skipped": limit}

    ids = list_distill_candidate_ids(storage, limit=limit, platform=platform)
    distilled = 0
    failed = 0
    for raw_id in ids:
        raw = storage.get_raw_by_id(raw_id)
        title = (getattr(raw, "raw_title", None) if raw else None) or f"#{raw_id}"
        plat = (raw.platform if raw else None) or platform
        try:
            distill_raw_item(storage, raw_id)
            distilled += 1
            progress and progress.log_item(
                phase="pipeline",
                title=title,
                platform=plat,
                status="distilled",
            )
        except Exception as exc:
            failed += 1
            progress and progress.log_item(
                phase="pipeline",
                title=title,
                platform=plat,
                status="failed",
                detail=str(exc),
            )
    return {"distilled": distilled, "failed": failed}


def _drain_ingest_pipeline(
    storage: StoragePort,
    *,
    platforms: list[str],
    batch_size: int = INGEST_BATCH_SIZE,
    max_rounds: int = MAX_PIPELINE_ROUNDS,
    timer: Any | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Ingest + subtitles + distill in parallel (three worker threads)."""
    from on1y.auth.context import get_current_user_id
    from on1y.sync.parallel_pipeline import run_parallel_pipeline

    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        uid = 1
    _ = max_rounds  # kept for API compat; parallel pipeline drains until queues empty
    return run_parallel_pipeline(
        storage,
        user_id=uid,
        platforms=platforms,
        batch_size=batch_size,
        timer=timer,
    )


def _drain_ingest_and_distill(
    storage: StoragePort,
    *,
    platforms: list[str],
    batch_size: int = INGEST_BATCH_SIZE,
    max_rounds: int = MAX_PIPELINE_ROUNDS,
    timer: Any | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias: cold start no longer blocks on distill."""
    return _drain_ingest_pipeline(
        storage,
        platforms=platforms,
        batch_size=batch_size,
        max_rounds=max_rounds,
        timer=timer,
    )


def _start_background_distill_after_cold_start(*, user_id: int) -> dict[str, Any]:
    from on1y.distill.batch_job import start_distill_batch_job
    from on1y.llm.settings import resolve_llm_settings

    if not resolve_llm_settings(user_id=user_id).api_key_set:
        logger.info("Skip post-cold-start distill for user %s: no LLM API key", user_id)
        return {"started": False, "running": False, "message": "未配置 LLM API Key"}
    return start_distill_batch_job(
        user_id=user_id,
        platform=None,
        batch_size=INGEST_BATCH_SIZE,
        max_items=10_000,
    )


def _execute_full_sync(
    *,
    user_id: int,
    videos_per_feed: int = VIDEOS_PER_FEED,
    bilibili_dynamic_days: int | None = None,
    started_at: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.subscriptions.sync_job import subscription_sync_status
    from on1y.sync.timing import (
        SyncTimer,
        append_timing_record,
        build_timing_record,
        format_duration_ms,
        list_timing_history,
        rollup_phase_totals,
    )

    if subscription_sync_status().get("running"):
        return None, "订阅同步正在进行中，请稍后再试"

    settings = get_settings()
    if bilibili_dynamic_days is None:
        bilibili_dynamic_days = settings.cold_start_bilibili_dynamic_days
    collection_platforms = parse_collections_platforms(settings.collections_sync_platforms)
    pipeline_platforms = ["bilibili", "youtube", "zhihu"]
    sync_started_at = started_at or datetime.now(timezone.utc).isoformat()
    timer = SyncTimer()

    report: dict[str, Any] = {
        "user_id": user_id,
        "videos_per_feed": videos_per_feed,
        "bilibili_dynamic_days": bilibili_dynamic_days,
    }
    storage = get_storage()
    from on1y.sync.progress import ColdStartProgress

    progress = ColdStartProgress(user_id=user_id, on_update=_on_cold_start_progress)
    try:
        with user_context(user_id):
            with progress.activate():
                progress.set_phase("starting", detail="准备初始同步")
                _set_sync_progress(phase="collections", phases_ms=rollup_phase_totals(timer.spans_ms))
                report["collections"] = _sync_collections_phase(
                    storage,
                    settings=settings,
                    platforms=collection_platforms,
                    timer=timer,
                )
                _set_sync_progress(
                    phase="subscriptions", phases_ms=rollup_phase_totals(timer.spans_ms)
                )
                report["subscriptions"] = _sync_subscriptions_phase(
                    storage,
                    settings=settings,
                    videos_per_feed=videos_per_feed,
                    bilibili_dynamic_days=bilibili_dynamic_days,
                    timer=timer,
                )
                _set_sync_progress(phase="pipeline", phases_ms=rollup_phase_totals(timer.spans_ms))
                report["pipeline"] = _drain_ingest_pipeline(
                    storage,
                    platforms=pipeline_platforms,
                    timer=timer,
                    user_id=user_id,
                )
                distill_stats = (report.get("pipeline") or {}).get("distill") or {}
                if distill_stats.get("enabled"):
                    progress.set_phase("done", detail="初始同步完成（含 AI 摘要）")
                    report["background_distill"] = {
                        "started": False,
                        "running": False,
                        "message": "摘要已在并行流水线中处理",
                        "distilled": distill_stats.get("distilled", 0),
                        "failed": distill_stats.get("failed", 0),
                    }
                else:
                    progress.set_phase("done", detail="入库完成（未配置 LLM，跳过摘要）")
                    report["background_distill"] = _start_background_distill_after_cold_start(
                        user_id=user_id
                    )

        finished_at = datetime.now(timezone.utc).isoformat()
        phase_totals = rollup_phase_totals(timer.spans_ms)
        timing = build_timing_record(
            user_id=user_id,
            started_at=sync_started_at,
            finished_at=finished_at,
            phases_ms=phase_totals,
            detail={
                "spans_ms": timer.spans_ms,
                "pipeline_rounds": report.get("pipeline", {}).get("rounds"),
                "pipeline_round_timings_ms": report.get("pipeline", {}).get("round_timings_ms"),
            },
        )
        report["timing"] = timing
        report["progress"] = progress.snapshot()
        append_timing_record(timing)
        try:
            from on1y.user.profile import patch_user_profile

            patch_user_profile(
                user_id=user_id,
                cold_start={
                    "last_completed_at": finished_at,
                    "onboarding_dismissed": True,
                },
            )
        except Exception:
            logger.exception("Failed to update cold_start profile for user %s", user_id)
        with _lock:
            _state["last_timing"] = timing
            _state["timing_history_count"] = len(list_timing_history(limit=100))
            _state["current_phase"] = "done"
            _state["phases_ms"] = phase_totals
            _state["progress"] = progress.snapshot()

        logger.info(
            "Full sync finished for user %s in %s (collections=%s subscriptions=%s pipeline=%s)",
            user_id,
            format_duration_ms(timing["total_ms"]),
            format_duration_ms(phase_totals.get("collections")),
            format_duration_ms(phase_totals.get("subscriptions")),
            format_duration_ms(phase_totals.get("pipeline")),
        )
        return report, None
    except Exception as exc:
        logger.exception("Full sync failed for user %s", user_id)
        _set_sync_progress(clear_phase=True)
        return report if report.get("collections") or report.get("subscriptions") else None, str(exc)
    finally:
        storage.close()


def run_full_sync_blocking(
    *,
    user_id: int,
    videos_per_feed: int = VIDEOS_PER_FEED,
    bilibili_dynamic_days: int | None = None,
) -> dict[str, Any] | None:
    with _lock:
        if _state["running"]:
            return None
        started_at = datetime.now(timezone.utc).isoformat()
        _state.update(
            {
                "running": True,
                "started_at": started_at,
                "finished_at": None,
                "last_report": None,
                "last_timing": None,
                "current_phase": "starting",
                "phases_ms": {},
                "progress": None,
                "error": None,
                "user_id": user_id,
            }
        )
    report, error = _execute_full_sync(
        user_id=user_id,
        videos_per_feed=videos_per_feed,
        bilibili_dynamic_days=bilibili_dynamic_days,
        started_at=started_at,
    )
    with _lock:
        _state["running"] = False
        _state["finished_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_report"] = report
        _state["error"] = error
        if not report:
            _state["current_phase"] = None
    return report


def _user_has_sync_cookies(user_id: int) -> bool:
    from on1y.user.paths import user_cookie_path

    return any(
        user_cookie_path(user_id, platform).is_file()
        for platform in ("bilibili", "youtube", "zhihu")
    )


def start_full_sync_job(
    *,
    user_id: int,
    videos_per_feed: int = VIDEOS_PER_FEED,
    bilibili_dynamic_days: int | None = None,
) -> dict[str, Any]:
    from on1y.subscriptions.sync_job import subscription_sync_status

    if not _user_has_sync_cookies(user_id):
        return {
            "started": False,
            "running": False,
            "message": "请先在设置 → Cookie 中配置至少一个平台（哔哩哔哩 / YouTube / 知乎）",
        }

    with _lock:
        if _state["running"]:
            return {
                "started": False,
                "running": True,
                "message": "初始同步已在进行中",
            }
    if subscription_sync_status().get("running"):
        return {
            "started": False,
            "running": False,
            "message": "订阅同步正在进行中，请稍后再试",
        }

    with _lock:
        if _state["running"]:
            return {"started": False, "running": True, "message": "初始同步已在进行中"}
        started_at = datetime.now(timezone.utc).isoformat()
        _state.update(
            {
                "running": True,
                "started_at": started_at,
                "finished_at": None,
                "last_report": None,
                "last_timing": None,
                "current_phase": "starting",
                "phases_ms": {},
                "error": None,
                "user_id": user_id,
            }
        )

    settings = get_settings()
    dynamic_days = (
        bilibili_dynamic_days
        if bilibili_dynamic_days is not None
        else settings.cold_start_bilibili_dynamic_days
    )

    def _run() -> None:
        report, error = _execute_full_sync(
            user_id=user_id,
            videos_per_feed=videos_per_feed,
            bilibili_dynamic_days=bilibili_dynamic_days,
            started_at=started_at,
        )
        with _lock:
            _state["running"] = False
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["last_report"] = report
            _state["error"] = error
            if not report:
                _state["current_phase"] = None

    threading.Thread(target=_run, daemon=True, name="on1y-full-sync").start()
    return {
        "started": True,
        "running": True,
        "message": (
            f"已开始初始同步（收藏夹 + B 站近 {dynamic_days} 天动态 + 入库；"
            f"AI 摘要后台进行）"
        ),
    }
