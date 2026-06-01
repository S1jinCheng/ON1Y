"""source_meta keys for decoupled video ingest (YouTube, Bilibili, …)."""

from __future__ import annotations

SUBTITLE_STATUS = "subtitle_status"
SUBTITLE_STATUS_PENDING = "pending"
SUBTITLE_STATUS_READY = "ready"
SUBTITLE_STATUS_FAILED = "failed"
VIDEO_DESCRIPTION = "video_description"
# legacy key from YouTube-only phase
YOUTUBE_DESCRIPTION = VIDEO_DESCRIPTION


def with_subtitle_pending(meta: dict | None) -> dict:
    out = dict(meta or {})
    out[SUBTITLE_STATUS] = SUBTITLE_STATUS_PENDING
    return out


def with_subtitle_ready(meta: dict | None) -> dict:
    out = dict(meta or {})
    out[SUBTITLE_STATUS] = SUBTITLE_STATUS_READY
    return out


def with_subtitle_failed(meta: dict | None, error: str) -> dict:
    out = dict(meta or {})
    out[SUBTITLE_STATUS] = SUBTITLE_STATUS_FAILED
    out["subtitle_error"] = error[:500]
    return out


def is_subtitle_ready(meta: dict | None) -> bool:
    return (meta or {}).get(SUBTITLE_STATUS) == SUBTITLE_STATUS_READY


def get_stored_description(meta: dict | None) -> str:
    if not meta:
        return ""
    return str(meta.get(VIDEO_DESCRIPTION) or meta.get("youtube_description") or "")
