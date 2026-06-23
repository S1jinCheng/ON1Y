"""Background subscription sync job state."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SYNC_PLATFORM_ORDER = ("bilibili", "youtube", "zhihu", "twitter")

# Routine auto-sync gap backfill: cap lookback even if user sync_since is older.
AUTO_SYNC_GAP_BACKFILL_MAX_DAYS = 7

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_report": None,
    "error": None,
    "user_id": None,
    "mode": None,
    "backfill": False,
    "progress": None,
}


def subscription_sync_status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _on_subscription_progress(snapshot: dict[str, Any]) -> None:
    with _lock:
        _state["progress"] = snapshot


def normalize_sync_platforms(
    *,
    platform: str = "all",
    platforms: list[str] | None = None,
) -> list[str]:
    allowed = set(SYNC_PLATFORM_ORDER)
    if platforms:
        out = [p for p in platforms if p in allowed]
        if not out:
            raise ValueError("platforms must include at least one of bilibili, youtube, zhihu, twitter")
        return out
    if platform == "all":
        return list(SYNC_PLATFORM_ORDER)
    if platform not in allowed:
        raise ValueError(f"unsupported platform: {platform}")
    return [platform]


def _execute_subscription_sync(
    *,
    platforms: list[str],
    backfill: bool = False,
    ingest: bool = False,
    ingest_limit: int = 30,
    subtitle_limit: int = 30,
    distill_limit: int = 30,
    use_ai_summary: bool = True,
    sync_hotlist: bool = False,
    refresh_feeds: bool | None = None,
    user_id: int | None = None,
    pipeline_batch_size: int | None = None,
    backfill_max_days: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import get_current_user_id
    from on1y.subscriptions import sync_subscriptions
    from on1y.sync.parallel_pipeline import run_parallel_pipeline
    from on1y.sync.progress import ColdStartProgress, get_cold_start_progress
    from on1y.sync_settings.settings import resolve_settings

    _ = ingest_limit, subtitle_limit, distill_limit  # legacy API; parallel pipeline drains queues

    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        raise RuntimeError("Subscription sync requires user_id or active user context")
    batch_size = pipeline_batch_size or resolve_settings(user_id=uid).auto_sync_pipeline_batch_size

    combined: dict[str, Any] = {"platforms": platforms, "use_ai_summary": use_ai_summary}
    error: str | None = None
    storage = get_storage()
    progress = ColdStartProgress(user_id=uid, on_update=_on_subscription_progress)
    pipeline_holder: dict[str, Any] = {}
    pipeline_exc: list[BaseException] = []
    poll_active = threading.Event()
    pipeline_thread: threading.Thread | None = None
    try:
        with progress.activate():
            if ingest:
                poll_active.set()
                if user_has_pipeline_backlog(user_id=uid):
                    progress.log_step(
                        phase="pipeline",
                        title="并行处理积压",
                        detail="订阅拉取与入库/字幕/摘要同时进行",
                    )

                def _pipeline_runner() -> None:
                    try:
                        pipeline_holder["report"] = run_parallel_pipeline(
                            storage,
                            user_id=uid,
                            platforms=list(platforms),
                            batch_size=batch_size,
                            use_ai_summary=use_ai_summary,
                            poll_active=poll_active,
                        )
                    except BaseException as exc:
                        pipeline_exc.append(exc)

                pipeline_thread = threading.Thread(
                    target=_pipeline_runner,
                    name="on1y-subscription-pipeline",
                    daemon=True,
                )
                pipeline_thread.start()

            progress.set_phase("subscriptions", detail="订阅同步")
            for name in SYNC_PLATFORM_ORDER:
                if name not in platforms:
                    continue
                progress.set_phase("subscriptions", detail=f"同步 · {name}")
                platform_report = sync_subscriptions(
                    storage,
                    platform=name,
                    sync_config=name == "bilibili",
                    poll=True,
                    backfill=backfill,
                    sync_hotlist=False,
                    refresh_feeds=refresh_feeds,
                    backfill_max_days=backfill_max_days,
                    user_id=uid,
                )
                nested = platform_report.get(name)
                poll = (
                    nested.get("poll")
                    if isinstance(nested, dict) and isinstance(nested.get("poll"), dict)
                    else platform_report.get("poll")
                )
                if isinstance(poll, dict):
                    enqueued = int(poll.get("enqueued") or 0)
                    if enqueued > 0:
                        progress.log_step(
                            phase="subscriptions",
                            title=f"{name} +{enqueued}",
                            detail="新条目已入队",
                        )
                combined[name] = platform_report

            if ingest and pipeline_thread is not None:
                poll_active.clear()
                pipeline_thread.join(timeout=6 * 3600)
                if pipeline_thread.is_alive():
                    logger.warning("Pipeline still running after subscription poll finished")
                if pipeline_exc:
                    raise pipeline_exc[0]
                combined["pipeline"] = pipeline_holder.get("report") or {}
            progress.set_phase("done", detail="订阅同步完成")
        logger.info("Subscription sync finished: %s", combined)
        return combined, None
    except Exception as exc:
        error = str(exc)
        logger.exception("Subscription sync failed")
        live = get_cold_start_progress()
        if live is not None:
            live.log_error(phase="subscriptions", title="订阅同步失败", detail=str(exc))
        return combined if combined.get("platforms") else None, error
    finally:
        with _lock:
            _state["progress"] = progress.snapshot()
        storage.close()


def user_has_pipeline_backlog(*, user_id: int) -> bool:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.distill.prompts import PROMPT_VERSION

    storage = get_storage()
    try:
        pending = storage.count_pending_by_status()
        if int(pending.get("pending", 0)) > 0 or int(pending.get("processing", 0)) > 0:
            return True
        sub = storage.count_subtitles_by_status()
        if int(sub.get("pending", 0)) > 0 or int(sub.get("processing", 0)) > 0:
            return True
        if storage.count_raw_ids_needing_distill(
            prompt_version=PROMPT_VERSION,
            platform=None,
        ) > 0:
            return True
    finally:
        storage.close()
    return False


def _execute_backlog_pipeline(
    *,
    user_id: int,
    pipeline_batch_size: int | None = None,
    use_ai_summary: bool = True,
) -> dict[str, Any]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.sync.parallel_pipeline import run_parallel_pipeline
    from on1y.sync.progress import ColdStartProgress
    from on1y.sync_settings.settings import resolve_settings

    uid = user_id
    batch_size = pipeline_batch_size or resolve_settings(user_id=uid).auto_sync_pipeline_batch_size
    platforms = list(SYNC_PLATFORM_ORDER)
    storage = get_storage()
    progress = ColdStartProgress(user_id=uid, on_update=_on_subscription_progress)
    try:
        with progress.activate():
            progress.set_phase("pipeline", detail="消化积压（入库 / 字幕 / 摘要）")
            report = run_parallel_pipeline(
                storage,
                user_id=uid,
                platforms=platforms,
                batch_size=batch_size,
                use_ai_summary=use_ai_summary,
            )
            progress.set_phase("done", detail="积压处理完成")
        return {"pipeline": report, "platforms": platforms}
    finally:
        with _lock:
            _state["progress"] = progress.snapshot()
        storage.close()


def run_backlog_pipeline_blocking(
    *,
    user_id: int,
    pipeline_batch_size: int | None = None,
    use_ai_summary: bool = True,
    mode: str = "auto",
) -> dict[str, Any] | None:
    """Drain ingest/subtitle/distill queues without polling subscriptions."""
    with _lock:
        if _state["running"]:
            return None
        _state.update(
            {
                "running": True,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "last_report": None,
                "error": None,
                "user_id": user_id,
                "mode": mode,
                "backfill": False,
                "progress": None,
            }
        )

    report: dict[str, Any] | None = None
    error: str | None = None
    try:
        report = _execute_backlog_pipeline(
            user_id=user_id,
            pipeline_batch_size=pipeline_batch_size,
            use_ai_summary=use_ai_summary,
        )
    except Exception as exc:
        error = str(exc)
        logger.exception("Backlog pipeline failed")
    with _lock:
        _state["running"] = False
        _state["finished_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_report"] = report
        _state["error"] = error
    return report


def run_subscription_sync_blocking(
    *,
    platform: str = "all",
    platforms: list[str] | None = None,
    backfill: bool = False,
    ingest: bool = False,
    ingest_limit: int = 30,
    subtitle_limit: int = 30,
    distill_limit: int = 30,
    use_ai_summary: bool = True,
    sync_hotlist: bool = False,
    refresh_feeds: bool | None = None,
    user_id: int | None = None,
    mode: str | None = None,
    pipeline_batch_size: int | None = None,
    backfill_max_days: int | None = None,
) -> dict[str, Any] | None:
    """Run sync in the current thread; return None if another sync is running."""
    from on1y.auth.context import get_current_user_id

    targets = normalize_sync_platforms(platform=platform, platforms=platforms)
    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        raise RuntimeError("Subscription sync requires user_id or active user context")
    with _lock:
        if _state["running"]:
            return None
        _state.update(
            {
                "running": True,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "last_report": None,
                "error": None,
                "user_id": uid,
                "mode": mode,
                "backfill": backfill,
                "progress": None,
            }
        )

    report, error = _execute_subscription_sync(
        platforms=targets,
        backfill=backfill,
        ingest=ingest,
        ingest_limit=ingest_limit,
        subtitle_limit=subtitle_limit,
        distill_limit=distill_limit,
        use_ai_summary=use_ai_summary,
        sync_hotlist=sync_hotlist,
        refresh_feeds=refresh_feeds,
        user_id=uid,
        pipeline_batch_size=pipeline_batch_size,
        backfill_max_days=backfill_max_days,
    )
    with _lock:
        _state["running"] = False
        _state["finished_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_report"] = report
        _state["error"] = error
    return report


def start_subscription_sync_job(
    *,
    platform: str = "all",
    platforms: list[str] | None = None,
    backfill: bool = False,
    ingest: bool = False,
    ingest_limit: int = 30,
    subtitle_limit: int = 30,
    distill_limit: int = 30,
    use_ai_summary: bool = True,
    sync_hotlist: bool = False,
    refresh_feeds: bool | None = None,
    user_id: int | None = None,
    pipeline_batch_size: int | None = None,
    backfill_max_days: int | None = None,
) -> dict[str, Any]:
    try:
        targets = normalize_sync_platforms(platform=platform, platforms=platforms)
    except ValueError as exc:
        return {"started": False, "running": False, "message": str(exc)}

    from on1y.auth.context import get_current_user_id, user_context

    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        return {
            "started": False,
            "running": False,
            "message": "缺少用户上下文：请登录后重试",
        }

    with _lock:
        if _state["running"]:
            return {
                "started": False,
                "running": True,
                "message": "同步已在进行中",
            }
        _state.update(
            {
                "running": True,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "last_report": None,
                "error": None,
                "user_id": uid,
                "mode": "manual",
                "backfill": backfill,
                "progress": None,
            }
        )

    def _run() -> None:
        with user_context(uid):
            report, error = _execute_subscription_sync(
                platforms=targets,
                backfill=backfill,
                ingest=ingest,
                ingest_limit=ingest_limit,
                subtitle_limit=subtitle_limit,
                distill_limit=distill_limit,
                use_ai_summary=use_ai_summary,
                sync_hotlist=sync_hotlist,
                refresh_feeds=refresh_feeds,
                user_id=uid,
                pipeline_batch_size=pipeline_batch_size,
                backfill_max_days=backfill_max_days,
            )
        with _lock:
            _state["running"] = False
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            _state["last_report"] = report
            _state["error"] = error

    threading.Thread(target=_run, daemon=True, name="on1y-subscription-sync").start()
    return {
        "started": True,
        "running": True,
        "message": "已在后台开始同步",
    }
