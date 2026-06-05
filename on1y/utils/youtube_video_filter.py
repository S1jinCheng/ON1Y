"""YouTube ingest filters — skip live streams, Shorts, and very short clips."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from on1y.utils.platform import is_youtube_url

if TYPE_CHECKING:
    from on1y.config import Settings
    from on1y.models.video_extract import VideoMetadata

_LIVE_PATH_RE = re.compile(r"youtube\.com/live/", re.IGNORECASE)
_SHORTS_PATH_RE = re.compile(r"youtube\.com/shorts/", re.IGNORECASE)


def is_youtube_live_url(url: str) -> bool:
    return bool(_LIVE_PATH_RE.search(url))


def is_youtube_shorts_url(url: str) -> bool:
    return bool(_SHORTS_PATH_RE.search(url))


def should_skip_youtube_url(url: str) -> bool:
    """Fast URL-only checks (RSS enqueue / before yt-dlp)."""
    if not is_youtube_url(url):
        return False
    return is_youtube_live_url(url) or is_youtube_shorts_url(url)


def live_flags_from_info(info: dict) -> tuple[str | None, bool, bool]:
    live_status = str(info.get("live_status") or "").strip() or None
    is_live = bool(info.get("is_live"))
    was_live = bool(info.get("was_live"))
    if not live_status:
        if is_live:
            live_status = "is_live"
        elif was_live:
            live_status = "was_live"
    return live_status, is_live, was_live


def youtube_ingest_reject_reason(
    url: str,
    meta: VideoMetadata,
    settings: Settings,
) -> str | None:
    """Return a short reason code when this YouTube item should not be ingested."""
    if not is_youtube_url(url):
        return None

    if settings.youtube_skip_shorts and (
        is_youtube_shorts_url(url) or _is_short_by_duration(meta.duration_sec, settings)
    ):
        return "youtube_shorts"

    if settings.youtube_skip_live:
        live_status = meta.live_status
        if meta.is_live or live_status in {"is_live", "is_upcoming"}:
            return "youtube_live"
        if settings.youtube_skip_live_replays and (
            meta.was_live or live_status in {"was_live", "post_live"}
        ):
            return "youtube_live_replay"

    min_dur = settings.youtube_min_duration_sec
    if min_dur > 0 and meta.duration_sec is not None and meta.duration_sec < min_dur:
        return "youtube_too_short"

    return None


def _is_short_by_duration(duration_sec: int | None, settings: Settings) -> bool:
    if duration_sec is None or duration_sec <= 0:
        return False
    # YouTube Shorts are <= 60s; use the same ceiling when skip_shorts is on.
    return duration_sec <= 60
