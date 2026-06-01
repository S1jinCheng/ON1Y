"""Subtitle fetch job models (YouTube Phase 1 pipeline)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from on1y.models.enums import PendingStatus


class PendingSubtitle(BaseModel):
    id: int
    raw_id: int
    url: str
    status: PendingStatus
    attempts: int = 0
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
