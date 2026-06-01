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


def _loop() -> None:
    from on1y.config import get_settings
    from on1y.subscriptions.sync_job import run_subscription_sync_blocking

    while not _stop.is_set():
        settings = get_settings()
        interval = settings.auto_sync_interval_minutes * 60
        if _stop.wait(timeout=interval):
            break

        report = run_subscription_sync_blocking(
            platform=settings.auto_sync_platform,
            backfill=False,
            ingest=settings.auto_sync_ingest,
            ingest_limit=settings.auto_sync_ingest_limit,
            subtitle_limit=settings.auto_sync_subtitle_limit,
            distill_limit=settings.auto_sync_distill_limit,
        )
        if report is None:
            logger.debug("Auto sync skipped: another sync is running")
        elif report:
            logger.info("Auto sync completed")
