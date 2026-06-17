"""Read / unread state stored in raw_items.source_meta."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def read_at_from_meta(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    raw = meta.get("read_at")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def is_read_meta(meta: dict[str, Any] | None) -> bool:
    return read_at_from_meta(meta) is not None


def unread_sql(alias: str = "r") -> str:
    """SQL fragment: row is unread."""
    col = f"json_extract({alias}.source_meta, '$.read_at')"
    return f"({col} IS NULL OR TRIM(COALESCE({col}, '')) = '')"
