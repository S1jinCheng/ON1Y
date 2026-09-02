"""Shared types for yt-dlp video extractors (YouTube, Bilibili, …)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoMetadata:
    title: str | None
    description: str
    video_id: str | None = None
    uploader: str | None = None
    uploader_url: str | None = None
    uploader_avatar: str | None = None
    cover_image: str | None = None
    channel_id: str | None = None
    duration_sec: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    upload_timestamp: int | None = None
    live_status: str | None = None
    is_live: bool = False
    was_live: bool = False


@dataclass(frozen=True)
class VideoSubtitlePayload:
    title: str | None
    description: str
    subtitle_text: str
    langs_found: list[str]
    partial_reason: str | None
