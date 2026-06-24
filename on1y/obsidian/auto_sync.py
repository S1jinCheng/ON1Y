"""Background Obsidian inbox sync while `on1y serve` is running."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import user_context
from on1y.ingestion.obsidian_import import import_obsidian_batch
from on1y.obsidian.settings import any_obsidian_sync_enabled, load_settings
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


def obsidian_sync_status() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def start_obsidian_sync_loop() -> None:
    global _thread
    if not any_obsidian_sync_enabled():
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        name="on1y-obsidian-sync",
        daemon=True,
    )
    _thread.start()
    logger.info("Obsidian sync loop enabled")


def stop_obsidian_sync_loop() -> None:
    _stop.set()


def run_obsidian_sync_once(*, limit: int = 50, auto_distill: bool | None = None) -> dict[str, Any]:
    storage = get_storage()
    try:
        return import_obsidian_batch(
            storage,
            limit=limit,
            auto_distill=auto_distill,
        )
    finally:
        storage.close()


def _run_user_tick(user_id: int) -> dict[str, Any]:
    storage = get_storage()
    try:
        cfg = load_settings(user_id=user_id)
        if not cfg.enabled:
            return {"enabled": False, "reason": "disabled", "scanned": 0, "imported": 0, "failed": 0, "skipped": 0}
        report = import_obsidian_batch(
            storage,
            user_id=user_id,
            limit=100,
            auto_distill=cfg.auto_distill,
        )
        return report
    finally:
        storage.close()


def _loop() -> None:
    while not _stop.is_set():
        storage = get_storage()
        try:
            user_ids = list_sync_user_ids(storage, current_user_only=True)
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
                    with _state_lock:
                        _state["last_report"] = report
                        _state["last_error"] = None
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Obsidian sync tick failed for user %s", uid)
                    with _state_lock:
                        _state["last_error"] = str(exc)
                finally:
                    with _state_lock:
                        _state["running"] = False
                        _state["finished_at"] = datetime.now(timezone.utc).isoformat()

        interval = 60
        if user_ids:
            with user_context(user_ids[0]):
                cfg = load_settings(user_id=user_ids[0])
                interval = max(15, int(cfg.interval_seconds))
        if _stop.wait(timeout=interval):
            break
