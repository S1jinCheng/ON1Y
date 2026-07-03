"""Background Telegram export-folder sync while `on1y serve` is running."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import user_context
from on1y.ingestion.telegram_import import import_telegram_batch
from on1y.telegram.settings import any_telegram_sync_enabled, load_settings
from on1y.user.accounts import list_sync_user_ids

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_report": None,
    "last_error": None,
    "user_id": None,
}


def telegram_sync_status() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def start_telegram_sync_loop() -> None:
    global _thread
    from on1y.telegram.client import _agent_log

    enabled = any_telegram_sync_enabled()
    # #region agent log
    _agent_log(
        "B",
        "auto_sync.py:start_telegram_sync_loop",
        "start_telegram_sync_loop called",
        {"enabled": enabled, "thread_alive": _thread is not None and _thread.is_alive()},
    )
    # #endregion
    if not enabled:
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        name="on1y-telegram-sync",
        daemon=True,
    )
    _thread.start()
    logger.info("Telegram sync loop enabled")


def stop_telegram_sync_loop() -> None:
    _stop.set()


def run_telegram_sync_once(
    *,
    user_id: int | None = None,
    limit: int = 200,
    auto_distill: bool | None = None,
) -> dict[str, Any]:
    uid = user_id if user_id is not None else None
    storage = get_storage()
    try:
        if uid is not None:
            with user_context(uid):
                return import_telegram_batch(
                    storage, user_id=uid, limit=limit, auto_distill=auto_distill
                )
        return import_telegram_batch(storage, limit=limit, auto_distill=auto_distill)
    finally:
        storage.close()


def start_telegram_sync_manual(
    *,
    user_id: int,
    limit: int = 200,
    auto_distill: bool | None = None,
) -> dict[str, Any]:
    """Run one sync pass in a background thread; return immediately for the HTTP handler."""
    from on1y.telegram.client import _agent_log

    with _state_lock:
        if _state.get("running"):
            return {"started": False, "running": True, "message": "Telegram sync already running"}
    # #region agent log
    _agent_log(
        "E",
        "auto_sync.py:start_telegram_sync_manual",
        "manual telegram sync scheduled",
        {"user_id": user_id, "limit": limit, "auto_distill": auto_distill},
    )
    # #endregion

    def _runner() -> None:
        with user_context(user_id):
            with _state_lock:
                _state["running"] = True
                _state["started_at"] = datetime.now(timezone.utc).isoformat()
                _state["finished_at"] = None
                _state["user_id"] = user_id
                _state["last_error"] = None
            try:
                report = run_telegram_sync_once(
                    user_id=user_id, limit=limit, auto_distill=auto_distill
                )
                # #region agent log
                _agent_log(
                    "E",
                    "auto_sync.py:start_telegram_sync_manual",
                    "manual telegram sync finished",
                    {
                        "user_id": user_id,
                        "report": {
                            k: report.get(k)
                            for k in (
                                "reason",
                                "imported",
                                "skipped",
                                "failed",
                                "scanned",
                                "distilled",
                            )
                        },
                    },
                )
                # #endregion
                with _state_lock:
                    _state["last_report"] = report
                    _state["last_error"] = None
            except Exception as exc:  # noqa: BLE001
                logger.exception("Manual Telegram sync failed for user %s", user_id)
                # #region agent log
                _agent_log(
                    "E",
                    "auto_sync.py:start_telegram_sync_manual",
                    "manual telegram sync failed",
                    {"user_id": user_id, "error": str(exc)},
                )
                # #endregion
                with _state_lock:
                    _state["last_error"] = str(exc)
            finally:
                with _state_lock:
                    _state["running"] = False
                    _state["finished_at"] = datetime.now(timezone.utc).isoformat()

    threading.Thread(
        target=_runner,
        name="on1y-telegram-sync-manual",
        daemon=True,
    ).start()
    return {"started": True, "running": True, "message": "Telegram sync started"}


def _run_user_tick(user_id: int) -> dict[str, Any]:
    storage = get_storage()
    try:
        cfg = load_settings(user_id=user_id)
        if not cfg.enabled:
            return {"enabled": False, "reason": "disabled", "scanned": 0, "imported": 0, "failed": 0, "skipped": 0}
        return import_telegram_batch(
            storage,
            user_id=user_id,
            limit=200,
            auto_distill=cfg.auto_distill,
        )
    finally:
        storage.close()


def _loop() -> None:
    while not _stop.is_set():
        storage = get_storage()
        try:
            user_ids = list_sync_user_ids(storage, current_user_only=False)
        finally:
            storage.close()
        for uid in user_ids:
            with user_context(uid):
                with _state_lock:
                    _state["running"] = True
                    _state["started_at"] = datetime.now(timezone.utc).isoformat()
                    _state["finished_at"] = None
                    _state["user_id"] = uid
                try:
                    report = _run_user_tick(uid)
                    # #region agent log
                    from on1y.telegram.client import _agent_log

                    _agent_log(
                        "C",
                        "auto_sync.py:_loop",
                        "telegram sync tick finished",
                        {"user_id": uid, "report": {k: report.get(k) for k in ("reason", "imported", "skipped", "failed", "scanned", "sync_mode", "enabled")}},
                    )
                    # #endregion
                    with _state_lock:
                        _state["last_report"] = report
                        _state["last_error"] = None
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Telegram sync tick failed for user %s", uid)
                    with _state_lock:
                        _state["last_error"] = str(exc)
                finally:
                    with _state_lock:
                        _state["running"] = False
                        _state["finished_at"] = datetime.now(timezone.utc).isoformat()

        intervals: list[int] = []
        for uid in user_ids:
            with user_context(uid):
                cfg = load_settings(user_id=uid)
                if cfg.enabled:
                    intervals.append(max(15, int(cfg.interval_seconds)))
        interval = min(intervals) if intervals else 300
        if _stop.wait(timeout=interval):
            break
