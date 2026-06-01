"""Resolve yt-dlp video extractors and shared fetch API."""

from __future__ import annotations

from on1y.extract.base import BaseExtractor
from on1y.models.video_extract import VideoMetadata, VideoSubtitlePayload
from on1y.utils.platform import PLATFORM_BILIBILI, PLATFORM_YOUTUBE, YTDLP_VIDEO_PLATFORMS


class YtdlpVideoExtractor(BaseExtractor):
    """Protocol: metadata + subtitle phases for decoupled ingest."""

    def fetch_metadata(self, url: str) -> VideoMetadata:
        raise NotImplementedError

    def fetch_subtitles(self, url: str) -> VideoSubtitlePayload:
        raise NotImplementedError


def get_ytdlp_video_extractor(platform: str) -> YtdlpVideoExtractor:
    if platform not in YTDLP_VIDEO_PLATFORMS:
        raise ValueError(f"not a yt-dlp video platform: {platform}")
    if platform == PLATFORM_YOUTUBE:
        from on1y.extract.youtube import YouTubeExtractor

        return YouTubeExtractor()
    if platform == PLATFORM_BILIBILI:
        from on1y.extract.bilibili import BilibiliExtractor

        return BilibiliExtractor()
    raise ValueError(f"no extractor for platform: {platform}")
