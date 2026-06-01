"""Extraction result contract returned by platform extractors."""

from __future__ import annotations

from pydantic import BaseModel

from on1y.models.enums import ContentType, ExtractStatus


class ExtractResult(BaseModel):
    """Normalized output from any extractor before persistence."""

    platform: str
    raw_title: str | None = None
    body_text: str
    content_type: ContentType
    extract_status: ExtractStatus
    extract_error: str | None = None
    author: str | None = None
    author_avatar: str | None = None
    author_url: str | None = None

    def word_count(self) -> int:
        return len(self.body_text.split())

    def truncated(self, max_chars: int) -> ExtractResult:
        if len(self.body_text) <= max_chars:
            return self
        return self.model_copy(
            update={
                "body_text": self.body_text[:max_chars],
                "extract_status": ExtractStatus.PARTIAL,
                "extract_error": (self.extract_error or "") + f" [truncated to {max_chars} chars]",
            }
        )
