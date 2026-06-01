"""Phase 2 — distilled archive and graph edges."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DistilledItem(BaseModel):
    id: int
    raw_id: int
    summary: str | None = None
    key_points: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    distill_status: str = "ok"
    distill_error: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    distilled_at: datetime | None = None


class Tag(BaseModel):
    id: int
    name: str
    slug: str
    parent_id: int | None = None


class ItemRelation(BaseModel):
    id: int
    from_raw_id: int
    to_raw_id: int
    relation_type: str
    confidence: float | None = None
    note: str | None = None
    source: str = "llm"


class LlmDistillResult(BaseModel):
    """Structured output expected from the exclusive-theme classification prompt."""

    summary: str = ""
    theme: str = ""
    themes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reader_text: str | None = None
    key_points: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("theme", mode="before")
    @classmethod
    def normalize_theme(cls, value: object) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        return ""

    @field_validator("themes", mode="before")
    @classmethod
    def normalize_themes(cls, value: object) -> list[str]:
        if not value:
            return []
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip().lower())
        return out

    def resolved_theme_slug(self) -> str:
        if self.theme.strip():
            return self.theme.strip().lower()
        if self.themes:
            return self.themes[0]
        return ""

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> list[str]:
        if not value:
            return []
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    out.append(name.strip())
        return out
