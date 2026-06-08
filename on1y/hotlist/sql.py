"""SQL fragments for hot-list rows (separate from theme feed)."""

from __future__ import annotations


def hotlist_source_expr(table_alias: str = "r") -> str:
    return f"COALESCE(json_extract({table_alias}.source_meta, '$.hotlist_source'), '')"


def is_hotlist_row_sql(table_alias: str = "r") -> str:
    return f"{hotlist_source_expr(table_alias)} != ''"


def is_feed_row_sql(table_alias: str = "r") -> str:
    return f"{hotlist_source_expr(table_alias)} = ''"


def is_feed_row_meta(meta: dict[str, object] | None) -> bool:
    """True when *meta* belongs to subscription/feed, not hot-list."""
    return not str((meta or {}).get("hotlist_source") or "").strip()
