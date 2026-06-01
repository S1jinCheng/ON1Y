"""Background subscription sync job state."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

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


def start_subscription_sync_job(
    *,
    platform: str = "bilibili",
    backfill: bool = False,
    ingest: bool = False,
    ingest_limit: int = 10,
    subtitle_limit: int = 10,
    distill_limit: int = 10,
) -> dict[str, Any]:
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

    def _run() -> None:
        from on1y.adapters.sqlite_storage import get_storage
        from on1y.pipeline.video_enrich import run_video_enrich_pipeline
        from on1y.subscriptions import sync_subscriptions

        report: dict[str, Any] | None = None
        error: str | None = None
        storage = get_storage()
        try:
            report = sync_subscriptions(
                storage,
                platform=platform,
                sync_config=platform in {"bilibili", "all"},
                poll=platform in {"bilibili", "all"},
                backfill=backfill,
                sync_hotlist=platform in {"zhihu", "all"},
            )
            if ingest and platform in {"bilibili", "all"}:
                report["enrich"] = run_video_enrich_pipeline(
                    storage,
                    platform="bilibili",
                    ingest_limit=ingest_limit,
                    subtitle_limit=subtitle_limit,
                    distill_limit=distill_limit,
                )
            elif ingest:
                from on1y.pipeline.worker import run_worker_batch

                report["ingest"] = run_worker_batch(storage, ingest_limit)
            logger.info("Background subscription sync finished: %s", report)
        except Exception as exc:
            error = str(exc)
            logger.exception("Background subscription sync failed")
        finally:
            storage.close()
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
