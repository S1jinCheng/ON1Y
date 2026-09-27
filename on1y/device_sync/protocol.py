"""Versioned, allow-listed wire format. Never serialize arbitrary source_meta."""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL_VERSION = 1
MAX_BODY = 8 * 1024 * 1024
META_FIELDS = {
    "user_note_html",
    "annotated_body_html",
    "starred",
    "importance",
    "read_at",
    "last_opened_at",
    "author",
    "author_name",
    "author_url",
    "published_at",
    "description",
    "selected_text",
    "clip_title",
}
RAW_FIELDS = {
    "platform",
    "source",
    "raw_title",
    "body_text",
    "content_type",
    "extract_status",
    "ingested_at",
    "theme_slug",
    "theme_source",
}
DISTILL_FIELDS = {
    "summary",
    "key_points",
    "topics",
    "distill_status",
    "model",
    "prompt_version",
    "reader_text",
}
THEME_FIELDS = {"name_zh", "name_en", "description_zh", "description_en", "sort_order"}


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_key(kind: str, identity: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"on1y:personal:v1:{kind}:{identity}"))


def allowed_field(kind: str, field: str) -> bool:
    if field == "_deleted":
        return True
    if kind == "theme":
        return field in THEME_FIELDS
    return (
        field in RAW_FIELDS
        or (field.startswith("meta/") and field[5:] in META_FIELDS)
        or (field.startswith("distill/") and field[8:] in DISTILL_FIELDS)
        or (field.startswith("tag/") and 0 < len(field[4:]) <= 200)
    )


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(min_length=1, max_length=80)
    kind: Literal["item", "theme"]
    identity: str = Field(min_length=1, max_length=4096)
    patch: dict[str, Any] = Field(min_length=1, max_length=1024)
    base: dict[str, int]

    @model_validator(mode="after")
    def validate_patch(self) -> Operation:
        if set(self.base) != set(self.patch) or any(v < 0 for v in self.base.values()):
            raise ValueError("every changed field needs a nonnegative base revision")
        for field, value in self.patch.items():
            if not allowed_field(self.kind, field):
                raise ValueError(f"unsupported sync field: {field}")
            enums = {
                "source": {
                    "rss",
                    "bilibili_feed",
                    "youtube_feed",
                    "manual",
                    "chrome",
                    "api",
                    "telegram",
                },
                "content_type": {"video", "article", "unknown"},
                "extract_status": {"ok", "partial", "failed"},
                "distill/distill_status": {"ok", "failed"},
            }
            if (
                field in enums
                and value is not None
                and (not isinstance(value, str) or value not in enums[field])
            ):
                raise ValueError("unsupported enum value")
            if field == "_deleted" and not isinstance(value, bool):
                raise ValueError("_deleted must be boolean")
            if field.startswith("tag/") and value is not None and value is not True:
                raise ValueError("tag membership must be true or null")
            if field in {"sort_order", "meta/importance"}:
                if value is not None and (type(value) is not int or abs(value) > 2**31 - 1):
                    raise ValueError("invalid integer field")
            elif field == "meta/starred":
                if value is not None and not isinstance(value, bool):
                    raise ValueError("starred must be boolean")
            elif field in {"distill/key_points", "distill/topics"}:
                if value is not None and (
                    not isinstance(value, list) or any(not isinstance(x, str) for x in value)
                ):
                    raise ValueError("invalid summary list")
            elif (
                field != "_deleted"
                and not field.startswith("tag/")
                and value is not None
                and not isinstance(value, str)
            ):
                raise ValueError("text field must be string or null")
        return self
