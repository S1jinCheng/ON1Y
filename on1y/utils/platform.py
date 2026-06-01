"""URL platform detection (used by extractors and metadata)."""

from __future__ import annotations

from urllib.parse import urlparse

PLATFORM_YOUTUBE = "youtube"
PLATFORM_BILIBILI = "bilibili"
PLATFORM_ZHIHU = "zhihu"
PLATFORM_XIAOHONGSHU = "xiaohongshu"
PLATFORM_TWITTER = "twitter"
PLATFORM_GITHUB = "github"
PLATFORM_GENERIC = "generic"

# Platforms using yt-dlp with decoupled metadata + subtitle pipeline
YTDLP_VIDEO_PLATFORMS = frozenset({PLATFORM_YOUTUBE, PLATFORM_BILIBILI})


def is_ytdlp_video_platform(platform: str) -> bool:
    return platform in YTDLP_VIDEO_PLATFORMS


def detect_platform(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    if "youtube.com" in host or "youtu.be" in host:
        return PLATFORM_YOUTUBE
    if "bilibili.com" in host or "b23.tv" in host:
        return PLATFORM_BILIBILI
    if "zhihu.com" in host or "zhuanlan.zhihu.com" in host:
        return PLATFORM_ZHIHU
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return PLATFORM_XIAOHONGSHU
    if "twitter.com" in host or "x.com" in host or "mobile.twitter.com" in host:
        return PLATFORM_TWITTER
    if "github.com" in host:
        return PLATFORM_GITHUB
    return PLATFORM_GENERIC


def normalize_url(url: str) -> str:
    """Strip fragments and trailing slashes for deduplication."""
    parsed = urlparse(url.strip())
    normalized = parsed._replace(fragment="")
    return normalized.geturl().rstrip("/")


def is_zhihu_url(url: str) -> bool:
    return detect_platform(url) == PLATFORM_ZHIHU


def is_youtube_url(url: str) -> bool:
    return detect_platform(url) == PLATFORM_YOUTUBE


def pending_url_platform_clause(platform: str) -> tuple[str, tuple[str, ...]]:
    """Return SQL WHERE fragment and params for filtering pending_urls by platform."""
    if platform == PLATFORM_ZHIHU:
        return (
            "(url LIKE ? OR url LIKE ? OR url LIKE ?)",
            ("%zhihu.com%", "%zhuanlan.zhihu.com%", "%www.zhihu.com%"),
        )
    if platform == PLATFORM_YOUTUBE:
        return (
            "(url LIKE ? OR url LIKE ?)",
            ("%youtube.com%", "%youtu.be%"),
        )
    if platform == PLATFORM_BILIBILI:
        return (
            "(url LIKE ? OR url LIKE ?)",
            ("%bilibili.com%", "%b23.tv%"),
        )
    return ("url LIKE ?", (f"%{platform}%",))
