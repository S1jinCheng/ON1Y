"""Extractor port — one implementation per platform or content type."""

from __future__ import annotations

from typing import Protocol

from on1y.models.extract import ExtractResult


class ExtractorPort(Protocol):
    @property
    def name(self) -> str:
        """Human-readable extractor id (e.g. youtube, article)."""
        ...

    def can_handle(self, url: str) -> bool:
        """Return True if this extractor should process the URL."""
        ...

    def extract(self, url: str) -> ExtractResult:
        """Fetch and normalize content; raise ExtractionError on hard failure."""
        ...
