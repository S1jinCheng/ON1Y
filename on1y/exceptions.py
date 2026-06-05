"""Domain-specific exceptions for clear error handling across layers."""

from __future__ import annotations


class On1yError(Exception):
    """Base exception for all On1y errors."""


class ConfigurationError(On1yError):
    """Invalid or missing configuration."""


class StorageError(On1yError):
    """Database or persistence failure."""


class ExtractionError(On1yError):
    """Content could not be extracted from a URL."""

    def __init__(self, message: str, *, url: str, platform: str | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.platform = platform


class NoExtractorError(ExtractionError):
    """No registered extractor matches the URL."""


class QueueEmptyError(On1yError):
    """No pending items available (not necessarily an error in polling loops)."""


class DuplicateVideoError(On1yError):
    """Video skipped because an equivalent item already exists on another platform."""

    def __init__(self, message: str, *, url: str, preferred_raw_id: int) -> None:
        super().__init__(message)
        self.url = url
        self.preferred_raw_id = preferred_raw_id


class SkippedVideoError(On1yError):
    """Video intentionally not ingested (live stream, Shorts, too short, etc.)."""

    def __init__(self, message: str, *, url: str, reason: str) -> None:
        super().__init__(message)
        self.url = url
        self.reason = reason
