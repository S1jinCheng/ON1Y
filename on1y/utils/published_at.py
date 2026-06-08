"""Parse original publish time from source_meta."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


def published_at_from_meta(meta: dict[str, Any] | None) -> datetime | None:
    meta = meta or {}
    for key in ("published", "published_at", "entry_published", "upload_date", "pubdate"):
        parsed = _parse_published_value(meta.get(key))
        if parsed is not None:
            return parsed
    return None


def published_at_iso(meta: dict[str, Any] | None) -> str | None:
    dt = published_at_from_meta(meta)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_published_value(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.isdigit():
        if len(text) == 8:
            try:
                return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
