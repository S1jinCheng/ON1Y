"""Background periodic subscription sync while `on1y serve` is running."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_backlog_thread: threading.Thread | None = None
_stop = threading.Event()
_scheduler_lock = threading.Lock()
_scheduler: dict[str, Any] = {
    "enabled": False,
    "thread_alive": False,
    "next_subscription_tick_at": None,
    "startup_delay_seconds": 0,
}


def auto_sync_scheduler_status() -> dict[str, Any]:
    with _scheduler_lock:
        out = dict(_scheduler)
    out["thread_alive"] = bool(_thread is not None and _thread.is_alive())
    return out


def start_auto_sync_loop() -> None:
    """Start daemon thread if ON1Y_AUTO_SYNC_ENABLED=true."""
    global _thread
    from on1y.config import get_settings

    from on1y.sync_settings.settings import any_auto_sync_enabled

    if not any_auto_sync_enabled():
        return
    settings = get_settings()
    if _thread is not None and _thread.is_alive():
        return

    _stop.clear()
    with _scheduler_lock:
        _scheduler["enabled"] = True
        _scheduler["startup_delay_seconds"] = settings.auto_sync_startup_delay_seconds
    global _backlog_thread
    if _backlog_thread is None or not _backlog_thread.is_alive():
        _backlog_thread = threading.Thread(
            target=_drain_backlog_once,
            name="on1y-auto-sync-backlog",
            daemon=True,
        )
        _backlog_thread.start()
    _thread = threading.Thread(
        target=_loop,
        name="on1y-auto-sync",
        daemon=True,
    )
    _thread.start()
    interval = settings.auto_sync_interval_minutes
    logger.info(
        "Auto subscription sync enabled (every %s min, platform=%s)",
        interval,
        settings.auto_sync_platform,
    )


def stop_auto_sync_loop() -> None:
    _stop.set()


_first_startup_tick = True
_backlog_drained_on_startup = False
_backlog_lock = threading.Lock()


def _drain_backlog_once() -> None:
    """Process existing ingest/subtitle/distill queues immediately on serve start."""
    global _backlog_drained_on_startup
    with _backlog_lock:
        if _backlog_drained_on_startup:
            return
        _backlog_drained_on_startup = True
    try:
        _drain_backlog_for_users()
    except Exception:
        logger.exception("Immediate startup backlog drain failed")
        with _backlog_lock:
            _backlog_drained_on_startup = False


def _drain_backlog_for_users() -> None:
    from on1y.auth.context import user_context
    from on1y.subscriptions.sync_job import (
        run_backlog_pipeline_blocking,
        subscription_sync_status,
        user_has_pipeline_backlog,
    )
    from on1y.sync_settings.settings import resolve_settings
    from on1y.user.accounts import list_sync_user_ids

    from on1y.adapters.sqlite_storage import get_storage

    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage, current_user_only=True)
    finally:
        storage.close()
    if not user_ids:
        logger.warning("Auto sync skipped: no active logged-in user for backlog drain")
        return

    for uid in user_ids:
        with user_context(uid):
            settings = resolve_settings(user_id=uid)
            if not settings.auto_sync_enabled:
                continue
            if not user_has_pipeline_backlog(user_id=uid):
                continue
            if subscription_sync_status().get("running"):
                logger.debug("Skip backlog drain for user %s: sync already running", uid)
                continue
            logger.info("Auto sync: draining pipeline backlog for user %s", uid)
            report = run_backlog_pipeline_blocking(
                user_id=uid,
                pipeline_batch_size=settings.auto_sync_pipeline_batch_size,
                mode="auto",
            )
            if report:
                from on1y.sync.auto_sync_state import write_last_auto_sync_at

                write_last_auto_sync_at(user_id=uid)
                logger.info("Backlog drain completed for user %s", uid)


def _run_auto_sync_tick(*, poll_only: bool = False) -> None:
    from on1y.auth.context import user_context
    from on1y.config import get_settings
    from on1y.subscriptions.sync_job import (
        AUTO_SYNC_GAP_BACKFILL_MAX_DAYS,
        run_subscription_sync_blocking,
    )
    from on1y.sync.auto_sync_state import (
        should_backfill_after_gap,
        write_last_auto_sync_at,
    )
    from on1y.user.accounts import list_sync_user_ids

    from on1y.sync_settings.settings import resolve_settings

    from on1y.adapters.sqlite_storage import get_storage

    settings = get_settings()
    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage, current_user_only=True)
    finally:
        storage.close()
    if not user_ids:
        logger.warning("Auto sync tick skipped: no active logged-in user")
        return

    ingest = settings.auto_sync_ingest and not poll_only
    if poll_only:
        logger.info("Auto sync startup tick: poll only (no ingest)")

    for uid in user_ids:
        with user_context(uid):
            user_settings = resolve_settings(user_id=uid)
            if not user_settings.auto_sync_enabled:
                continue
            backfill = False if poll_only else should_backfill_after_gap(user_id=uid)
            if backfill:
                logger.info("Auto sync catch-up backfill for user %s (missed day gap)", uid)
            report = run_subscription_sync_blocking(
                platform=user_settings.auto_sync_platform,
                backfill=backfill,
                backfill_max_days=AUTO_SYNC_GAP_BACKFILL_MAX_DAYS if backfill else None,
                ingest=ingest,
                pipeline_batch_size=user_settings.auto_sync_pipeline_batch_size,
                user_id=uid,
                mode="auto",
            )
            if report is None:
                logger.debug("Auto sync skipped for user %s: another sync running", uid)
            elif report:
                logger.info("Auto sync completed for user %s", uid)
                if not poll_only:
                    write_last_auto_sync_at(user_id=uid)


def _loop() -> None:
    global _first_startup_tick, _backlog_drained_on_startup
    from on1y.config import get_settings
    from on1y.sync_settings.settings import resolve_settings

    settings = get_settings()
    delay = settings.auto_sync_startup_delay_seconds
    if delay > 0:
        next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        with _scheduler_lock:
            _scheduler["next_subscription_tick_at"] = next_at.isoformat()
        logger.info(
            "Auto sync: waiting %ss before first subscription poll (startup grace)",
            delay,
        )
        if _stop.wait(timeout=delay):
            with _scheduler_lock:
                _scheduler["next_subscription_tick_at"] = None
            return
        with _scheduler_lock:
            _scheduler["next_subscription_tick_at"] = None

    _drain_backlog_once()

    while not _stop.is_set():
        try:
            tick_settings = resolve_settings()
            poll_only = _first_startup_tick and tick_settings.auto_sync_startup_poll_only
            _run_auto_sync_tick(poll_only=poll_only)
        except Exception:
            logger.exception("Auto subscription sync tick failed")
        finally:
            _first_startup_tick = False

        from on1y.sync_settings.settings import resolve_settings

        settings = resolve_settings()
        interval = settings.auto_sync_interval_minutes * 60
        if _stop.wait(timeout=interval):
            break
