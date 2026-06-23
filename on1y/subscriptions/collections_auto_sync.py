"""Background collections (收藏夹) polling while `on1y serve` is running."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_state_lock = threading.Lock()
_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "user_id": None,
    "last_report": None,
    "last_error": None,
}


def collections_sync_status() -> dict:
    with _state_lock:
        return dict(_state)


def start_collections_sync_loop() -> None:
    global _thread
    from on1y.config import get_settings

    from on1y.sync_settings.settings import any_collections_sync_enabled

    if not any_collections_sync_enabled():
        return
    settings = get_settings()
    if _thread is not None and _thread.is_alive():
        return

    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        name="on1y-collections-sync",
        daemon=True,
    )
    _thread.start()
    logger.info(
        "Collections sync enabled (every %ss, platforms=%s)",
        settings.collections_sync_interval_seconds,
        settings.collections_sync_platforms,
    )


def stop_collections_sync_loop() -> None:
    _stop.set()


def _run_tick(*, ingest: bool) -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.config import get_settings
    from on1y.ingestion.collections_sync import sync_collections
    from on1y.user.accounts import list_sync_user_ids

    from on1y.sync_settings.settings import resolve_settings

    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage, current_user_only=True)
    finally:
        storage.close()
    if not user_ids:
        logger.warning("Collections sync tick skipped: no active logged-in user")
        return

    for uid in user_ids:
        with _state_lock:
            _state["user_id"] = uid
        with user_context(uid):
            settings = resolve_settings(user_id=uid)
            if not settings.collections_sync_enabled:
                continue
            storage = get_storage()
            try:
                report = sync_collections(
                    storage,
                    ingest=ingest and settings.collections_sync_ingest,
                    ingest_limit=settings.collections_sync_ingest_limit,
                    settings=settings,
                )
                with _state_lock:
                    _state["last_report"] = report
                    _state["last_error"] = None
                    _state["user_id"] = uid
                if report.get("enqueued_total"):
                    logger.info(
                        "Collections sync user=%s enqueued=%s",
                        uid,
                        report["enqueued_total"],
                    )
            except Exception as exc:
                logger.exception("Collections sync tick failed for user %s", uid)
                with _state_lock:
                    _state["last_error"] = str(exc)
                    _state["user_id"] = uid
            finally:
                storage.close()


def _loop() -> None:
    from on1y.config import get_settings

    settings = get_settings()
    delay = settings.collections_sync_startup_delay_seconds
    if delay > 0:
        logger.info("Collections sync: waiting %ss before first tick", delay)
        if _stop.wait(timeout=delay):
            return

    first = True
    while not _stop.is_set():
        with _state_lock:
            _state["running"] = True
            _state["started_at"] = datetime.now(timezone.utc).isoformat()
            _state["finished_at"] = None
        try:
            _run_tick(ingest=not first or not settings.collections_sync_startup_poll_only)
        except Exception:
            logger.exception("Collections sync tick failed")
        finally:
            with _state_lock:
                _state["running"] = False
                _state["finished_at"] = datetime.now(timezone.utc).isoformat()
            first = False

        from on1y.sync_settings.settings import resolve_settings

        settings = resolve_settings()
        interval = max(30, settings.collections_sync_interval_seconds)
        if _stop.wait(timeout=interval):
            break
