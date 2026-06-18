"""Background loop: generate evening digest at 22:00 Asia/Shanghai."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta
from typing import Any

from on1y.stats.timezone_util import stats_timezone

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()


def start_evening_digest_loop() -> None:
    global _thread
    from on1y.config import get_settings

    if not get_settings().evening_digest_enabled:
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="on1y-evening-digest", daemon=True)
    _thread.start()
    logger.info(
        "Evening digest enabled (hour=%s, timezone=Asia/Shanghai)",
        get_settings().evening_digest_hour,
    )


def stop_evening_digest_loop() -> None:
    _stop.set()


def _digest_hour() -> int:
    from on1y.config import get_settings

    return int(get_settings().evening_digest_hour)


def _today_run_at(now: datetime, hour: int) -> datetime:
    return datetime.combine(now.date(), time(hour, 0, 0), tzinfo=now.tzinfo)


def _seconds_until(target: datetime, now: datetime) -> float:
    return max(0.0, (target - now).total_seconds())


def run_evening_digest_tick(
    *,
    user_id: int | None = None,
    force_day: str | None = None,
) -> list[dict[str, Any]]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.config import get_settings
    from on1y.digest.evening import build_evening_digest, load_evening_digest
    from on1y.user.accounts import list_sync_user_ids

    settings = get_settings()
    tz = stats_timezone()
    now = datetime.now(tz)
    digest_day = force_day or now.date().isoformat()

    if force_day is None and now.hour < settings.evening_digest_hour:
        return [{"skipped": True, "reason": "before_digest_hour", "digest_date": digest_day}]

    storage = get_storage()
    try:
        user_ids = [user_id] if user_id is not None else list_sync_user_ids(storage)
    finally:
        storage.close()

    reports: list[dict[str, Any]] = []
    for uid in user_ids:
        with user_context(uid):
            if load_evening_digest(uid, digest_day) is not None:
                reports.append({"user_id": uid, "skipped": True, "digest_date": digest_day})
                continue
            storage = get_storage()
            try:
                doc = build_evening_digest(
                    storage,
                    day=digest_day,
                    force=False,
                    user_id=uid,
                )
                reports.append(
                    {
                        "user_id": uid,
                        "digest_date": doc.get("digest_date"),
                        "generated": True,
                        "has_llm": bool(doc.get("llm_summary")),
                    }
                )
                logger.info(
                    "Evening digest generated user=%s date=%s llm=%s",
                    uid,
                    digest_day,
                    bool(doc.get("llm_summary")),
                )
            finally:
                storage.close()
    return reports


def _run_startup_catchup() -> None:
    """Backfill today (if past digest hour) and archive yesterday if missing."""
    tz = stats_timezone()
    now = datetime.now(tz)
    hour = _digest_hour()
    today = now.date().isoformat()
    yesterday = (now.date() - timedelta(days=1)).isoformat()

    if now.hour >= hour:
        reports = run_evening_digest_tick(force_day=today)
        if any(r.get("generated") for r in reports):
            logger.info("Evening digest startup catch-up for today %s", today)

    reports = run_evening_digest_tick(force_day=yesterday)
    if any(r.get("generated") for r in reports):
        logger.info("Evening digest archived yesterday %s", yesterday)


def _loop() -> None:
    hour = _digest_hour()
    tz = stats_timezone()

    _run_startup_catchup()

    while not _stop.is_set():
        now = datetime.now(tz)
        today_run = _today_run_at(now, hour)

        if now >= today_run:
            run_evening_digest_tick(force_day=now.date().isoformat())
            next_run = today_run + timedelta(days=1)
        else:
            next_run = today_run

        wait = _seconds_until(next_run, datetime.now(tz))
        if wait > 0:
            logger.debug("Evening digest sleeping %.0fs until %s", wait, next_run.isoformat())
            if _stop.wait(timeout=wait):
                break

        if not _stop.is_set():
            day = datetime.now(tz).date().isoformat()
            run_evening_digest_tick(force_day=day)
