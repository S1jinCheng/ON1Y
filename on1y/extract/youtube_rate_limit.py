"""Process-local pacing and circuit breaker for YouTube subtitle requests."""

from __future__ import annotations

import logging
import threading
import time

from on1y.config import get_settings

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_PAUSE_UNTIL = 0.0


def wait_for_youtube_subtitle_request() -> None:
    """Wait for the next allowed YouTube subtitle request."""
    global _LAST_REQUEST_AT

    settings = get_settings()
    interval = max(0.0, float(settings.youtube_subtitle_min_interval_seconds))
    while True:
        with _LOCK:
            now = time.monotonic()
            wait_seconds = max(
                _LAST_REQUEST_AT + interval - now,
                _PAUSE_UNTIL - now,
                0.0,
            )
            if wait_seconds <= 0:
                _LAST_REQUEST_AT = now
                return
        logger.info("YouTube subtitle request delayed %.0fs by rate limiter", wait_seconds)
        time.sleep(min(wait_seconds, 30.0))


def pause_youtube_subtitles(seconds: float) -> None:
    """Pause new YouTube subtitle jobs after a rate-limit response."""
    global _PAUSE_UNTIL

    with _LOCK:
        _PAUSE_UNTIL = max(_PAUSE_UNTIL, time.monotonic() + max(0.0, seconds))


def youtube_subtitle_pause_remaining() -> float:
    with _LOCK:
        return max(0.0, _PAUSE_UNTIL - time.monotonic())
