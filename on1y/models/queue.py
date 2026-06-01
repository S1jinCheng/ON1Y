"""Queue models for the ingestion pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from on1y.models.enums import PendingStatus, SourceType


class QueueEnqueue(BaseModel):
    """Payload produced by any trigger (RSS, manual, browser, API)."""

    url: HttpUrl | str
    source: SourceType
    source_meta: dict[str, Any] = Field(default_factory=dict)

    def url_str(self) -> str:
        return str(self.url)


class PendingUrl(BaseModel):
    """Row from pending_urls."""

    id: int
    url: str
    source: SourceType
    source_meta: dict[str, Any] = Field(default_factory=dict)
    status: PendingStatus
    attempts: int = 0
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
