"""Background periodic subscription sync while `on1y serve` is running."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()


def start_auto_sync_loop() -> None:
    """Start daemon thread if ON1Y_AUTO_SYNC_ENABLED=true."""
    global _thread
    from on1y.config import get_settings

    settings = get_settings()
    if not settings.auto_sync_enabled:
        return
    if _thread is not None and _thread.is_alive():
        return

    _stop.clear()
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


def _run_auto_sync_tick(*, poll_only: bool = False) -> None:
    from on1y.auth.context import user_context
    from on1y.config import get_settings
    from on1y.subscriptions.sync_job import run_subscription_sync_blocking
    from on1y.user.accounts import UserStore

    settings = get_settings()
    from on1y.adapters.sqlite_storage import get_storage

    storage = get_storage()
    try:
        user_ids = UserStore(storage).list_active_user_ids()
    finally:
        storage.close()

    ingest = settings.auto_sync_ingest and not poll_only
    subtitle_limit = 0 if poll_only else settings.auto_sync_subtitle_limit
    distill_limit = 0 if poll_only else settings.auto_sync_distill_limit
    if poll_only:
        logger.info("Auto sync startup tick: poll only (no ingest)")

    for uid in user_ids:
        with user_context(uid):
            report = run_subscription_sync_blocking(
                platform=settings.auto_sync_platform,
                backfill=False,
                ingest=ingest,
                ingest_limit=settings.auto_sync_ingest_limit,
                subtitle_limit=subtitle_limit,
                distill_limit=distill_limit,
            )
            if report is None:
                logger.debug("Auto sync skipped for user %s: another sync running", uid)
            elif report:
                logger.info("Auto sync completed for user %s", uid)


def _loop() -> None:
    global _first_startup_tick
    from on1y.config import get_settings

    settings = get_settings()
    delay = settings.auto_sync_startup_delay_seconds
    if delay > 0:
        logger.info("Auto sync: waiting %ss before first tick (startup grace)", delay)
        if _stop.wait(timeout=delay):
            return

    while not _stop.is_set():
        try:
            poll_only = _first_startup_tick and settings.auto_sync_startup_poll_only
            _run_auto_sync_tick(poll_only=poll_only)
        except Exception:
            logger.exception("Auto subscription sync tick failed")
        finally:
            _first_startup_tick = False

        settings = get_settings()
        interval = settings.auto_sync_interval_minutes * 60
        if _stop.wait(timeout=interval):
            break
