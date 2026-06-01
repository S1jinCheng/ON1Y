"""Enumerations shared across storage, ingestion, and extraction."""

from enum import StrEnum


class SourceType(StrEnum):
    RSS = "rss"
    BILIBILI_FEED = "bilibili_feed"
    YOUTUBE_FEED = "youtube_feed"
    MANUAL = "manual"
    CHROME = "chrome"
    API = "api"


class PendingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ContentType(StrEnum):
    VIDEO = "video"
    ARTICLE = "article"
    UNKNOWN = "unknown"


class ExtractStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
