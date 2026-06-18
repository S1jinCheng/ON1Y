"""Per-item importance rating (1–5 stars) stored in source_meta.importance."""

from __future__ import annotations

from typing import Any

_MIN_STARS = 1
_MAX_STARS = 5


def normalize_importance(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        stars = int(value)
    except (TypeError, ValueError):
        return None
    if _MIN_STARS <= stars <= _MAX_STARS:
        return stars
    return None


def importance_from_meta(meta: dict[str, Any] | None) -> int | None:
    if not meta:
        return None
    return normalize_importance(meta.get("importance"))


def importance_min_sql(alias: str = "r", *, minimum: int) -> str:
    minimum = max(_MIN_STARS, min(_MAX_STARS, int(minimum)))
    col = f"CAST(json_extract({alias}.source_meta, '$.importance') AS INTEGER)"
    return f"({col} IS NOT NULL AND {col} >= ?)"
