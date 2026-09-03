"""Per-user books module settings (cache path, acquire strategy)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)

BookFormat = Literal["epub", "pdf", "mobi"]
AcquireStrategy = Literal["match_first", "format_first"]
DEFAULT_ZLIB_BASE = "https://zh.z-lib.help"
DEFAULT_ALLOWED_FORMATS: list[BookFormat] = ["epub", "pdf", "mobi"]


class BookSettings(BaseModel):
    version: int = 4
    cache_dir: str | None = None
    folder_sync_enabled: bool = False
    zlib_base_url: str = DEFAULT_ZLIB_BASE
    acquire_strategy: AcquireStrategy = "match_first"
    preferred_format: BookFormat = "epub"
    allowed_formats: list[BookFormat] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_FORMATS))
    format_filter: BookFormat | None = None  # legacy single-format
    format_filters: list[BookFormat] = Field(default_factory=list)
    annas_secret_key: str | None = None
    # legacy alias — migrated to preferred_format on load
    default_format: BookFormat | None = None

    @field_validator("format_filters")
    @classmethod
    def _clean_format_filters(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            fmt = str(raw).lower()
            if fmt not in ("epub", "pdf", "mobi") or fmt in seen:
                continue
            seen.add(fmt)
            cleaned.append(fmt)
        return cleaned

    @field_validator("allowed_formats")
    @classmethod
    def _non_empty_formats(cls, value: list[str]) -> list[str]:
        cleaned = [str(f).lower() for f in value if str(f).lower() in ("epub", "pdf", "mobi")]
        return cleaned or list(DEFAULT_ALLOWED_FORMATS)

    @model_validator(mode="before")
    @classmethod
    def _migrate_default_format(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if data.get("preferred_format") is None and data.get("default_format"):
            data["preferred_format"] = data["default_format"]
        if not data.get("allowed_formats"):
            data["allowed_formats"] = list(DEFAULT_ALLOWED_FORMATS)
        if not data.get("acquire_strategy"):
            data["acquire_strategy"] = "match_first"
        if data.get("format_filters") is None:
            legacy = data.get("format_filter")
            data["format_filters"] = [legacy] if legacy else []
        return data


def user_books_settings_path(user_id: int) -> Path:
    books_dir = user_dir(user_id) / "books"
    books_dir.mkdir(parents=True, exist_ok=True)
    return books_dir / "settings.json"


def load_book_settings(user_id: int) -> BookSettings:
    path = user_books_settings_path(user_id)
    if not path.is_file():
        payload = BookSettings()
        save_book_settings(user_id, payload)
        return payload
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BookSettings.model_validate(data)
    except Exception:
        logger.warning("Invalid books settings %s; resetting defaults", path)
        payload = BookSettings()
        save_book_settings(user_id, payload)
        return payload


def save_book_settings(user_id: int, payload: BookSettings) -> None:
    path = user_books_settings_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = payload.model_dump()
    dumped.pop("default_format", None)
    path.write_text(
        json.dumps(dumped, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
