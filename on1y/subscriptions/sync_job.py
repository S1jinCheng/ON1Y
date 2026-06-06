"""Background subscription sync job state."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SYNC_PLATFORM_ORDER = ("bilibili", "youtube", "zhihu")

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_report": None,
    "error": None,
}


def subscription_sync_status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def normalize_sync_platforms(
    *,
    platform: str = "all",
    platforms: list[str] | None = None,
) -> list[str]:
    allowed = set(SYNC_PLATFORM_ORDER)
    if platforms:
        out = [p for p in platforms if p in allowed]
        if not out:
            raise ValueError("platforms must include at least one of bilibili, youtube, zhihu")
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
) -> tuple[dict[str, Any] | None, str | None]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.distill.processor import run_distill_batch
    from on1y.pipeline.video_enrich import run_video_enrich_pipeline
    from on1y.pipeline.worker import run_worker_batch
    from on1y.subscriptions import sync_subscriptions

    if not use_ai_summary:
        distill_limit = 0

    combined: dict[str, Any] = {"platforms": platforms, "use_ai_summary": use_ai_summary}
    error: str | None = None
    storage = get_storage()
    try:
        for name in SYNC_PLATFORM_ORDER:
            if name not in platforms:
                continue
            platform_report = sync_subscriptions(
                storage,
                platform=name,
                sync_config=name == "bilibili",
                poll=True,
                backfill=backfill,
                sync_hotlist=sync_hotlist and name == "bilibili",
                refresh_feeds=refresh_feeds,
            )
            if ingest:
                if name == "bilibili":
                    platform_report["enrich"] = run_video_enrich_pipeline(
                        storage,
                        platform="bilibili",
                        ingest_limit=ingest_limit,
                        subtitle_limit=subtitle_limit,
                        distill_limit=distill_limit,
                        use_ai_summary=use_ai_summary,
                    )
                else:
                    platform_report["ingest"] = run_worker_batch(
                        storage, ingest_limit, platform=name
                    )
                    if use_ai_summary and distill_limit > 0:
                        platform_report["distill"] = run_distill_batch(
                            storage, distill_limit, platform=name
                        )
            combined[name] = platform_report
        logger.info("Subscription sync finished: %s", combined)
        return combined, None
    except Exception as exc:
        error = str(exc)
        logger.exception("Subscription sync failed")
        return combined if combined.get("platforms") else None, error
    finally:
        storage.close()


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
) -> dict[str, Any] | None:
    """Run sync in the current thread; return None if another sync is running."""
    targets = normalize_sync_platforms(platform=platform, platforms=platforms)
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
) -> dict[str, Any]:
    try:
        targets = normalize_sync_platforms(platform=platform, platforms=platforms)
    except ValueError as exc:
        return {"started": False, "running": False, "message": str(exc)}

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
            }
        )

    from on1y.auth.context import get_current_user_id, get_effective_user_id, user_context

    uid = user_id if user_id is not None else get_current_user_id()
    if uid is None:
        uid = get_effective_user_id()

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
