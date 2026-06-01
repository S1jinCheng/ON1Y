"""Raw item models (Phase 1 knowledge archive — no LLM fields)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from on1y.models.enums import ContentType, ExtractStatus, SourceType


class RawItemCreate(BaseModel):
    """Input for upserting a processed URL into raw_items."""

    url: str
    platform: str
    source: SourceType
    raw_title: str | None = None
    body_text: str | None = None
    content_type: ContentType
    extract_status: ExtractStatus
    extract_error: str | None = None
    source_meta: dict[str, Any] = Field(default_factory=dict)


class RawItem(BaseModel):
    """Stored raw archive entry."""

    id: int
    url: str
    platform: str
    source: SourceType
    raw_title: str | None = None
    body_text: str | None = None
    content_type: ContentType
    extract_status: ExtractStatus
    extract_error: str | None = None
    word_count: int | None = None
    source_meta: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
