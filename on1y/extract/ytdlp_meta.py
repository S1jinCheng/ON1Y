"""Shared yt-dlp metadata helpers."""

from __future__ import annotations

from typing import Any

from on1y.models.video_extract import VideoMetadata

_YT_VIDEO_THUMB = "/vi/"


def youtube_channel_avatar_url(channel_id: str | None) -> str | None:
    cid = (channel_id or "").strip()
    if not cid:
        return None
    return f"https://unavatar.io/youtube/{cid}"


def video_metadata_from_info(info: dict[str, Any] | None) -> VideoMetadata:
    if not isinstance(info, dict):
        return VideoMetadata(title=None, description="")
    uploader = str(info.get("uploader") or info.get("channel") or "").strip() or None
    uploader_url = str(info.get("uploader_url") or info.get("channel_url") or "").strip() or None
    channel_id = str(info.get("channel_id") or "").strip() or None
    uploader_avatar = _uploader_avatar_from_info(info) or youtube_channel_avatar_url(channel_id)
    duration = info.get("duration")
    duration_sec = int(duration) if isinstance(duration, (int, float)) and duration > 0 else None
    return VideoMetadata(
        title=info.get("title"),
        description=(info.get("description") or "")[:50_000],
        video_id=info.get("id"),
        uploader=uploader,
        uploader_url=uploader_url,
        uploader_avatar=uploader_avatar,
        cover_image=_cover_from_info(info),
        channel_id=channel_id,
        duration_sec=duration_sec,
    )


def _uploader_avatar_from_info(info: dict[str, Any]) -> str | None:
    for key in ("uploader_thumbnail", "channel_thumbnail", "uploader_avatar", "channel_avatar"):
        value = info.get(key)
        if value:
            url = str(value).strip()
            if _YT_VIDEO_THUMB not in url:
                return url
    return None


def _cover_from_info(info: dict[str, Any]) -> str | None:
    thumb = info.get("thumbnail")
    if thumb:
        return str(thumb).strip()
    thumbs = info.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        url = thumbs[-1].get("url") if isinstance(thumbs[-1], dict) else None
        if url:
            return str(url).strip()
    return None
