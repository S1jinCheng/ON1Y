"""SQL fragments for hot-list rows (separate from theme feed)."""

from __future__ import annotations


def hotlist_source_expr(table_alias: str = "r") -> str:
    return f"COALESCE(json_extract({table_alias}.source_meta, '$.hotlist_source'), '')"


def is_hotlist_row_sql(table_alias: str = "r") -> str:
    return f"{hotlist_source_expr(table_alias)} != ''"


def is_book_shelf_row_sql(table_alias: str = "r") -> str:
    """True when row is a bookshelf shadow entry (not subscription feed)."""
    return (
        f"COALESCE({table_alias}.platform, '') = 'book' "
        f"OR COALESCE(json_extract({table_alias}.source_meta, '$.book_shelf'), '') "
        "IN ('1', 'true', 'True')"
    )


def is_paper_library_row_sql(table_alias: str = "r") -> str:
    """True when row is a paper-library shadow entry (not subscription feed)."""
    return (
        f"COALESCE({table_alias}.platform, '') = 'paper' "
        f"OR COALESCE(json_extract({table_alias}.source_meta, '$.paper_library'), '') "
        "IN ('1', 'true', 'True')"
    )


def is_feed_row_sql(table_alias: str = "r") -> str:
    return (
        f"{hotlist_source_expr(table_alias)} = '' "
        f"AND NOT ({is_book_shelf_row_sql(table_alias)}) "
        f"AND NOT ({is_paper_library_row_sql(table_alias)})"
    )


def is_feed_row_meta(meta: dict[str, object] | None, *, platform: str | None = None) -> bool:
    """True when *meta* belongs to subscription/feed, not hot-list or bookshelf."""
    if str((meta or {}).get("hotlist_source") or "").strip():
        return False
    if (meta or {}).get("book_shelf"):
        return False
    if (platform or "").strip().lower() == "book":
        return False
    if (meta or {}).get("paper_library"):
        return False
    return (platform or "").strip().lower() != "paper"
