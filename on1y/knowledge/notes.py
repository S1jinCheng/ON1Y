"""User notes on knowledge items (source_meta.user_note_html)."""

from __future__ import annotations

from typing import Any

from on1y.hotlist.sql import is_feed_row_sql
from on1y.utils.html_text import html_to_plain_text


def note_html_from_meta(meta: dict[str, Any] | None) -> str:
    if not meta:
        return ""
    return str(meta.get("user_note_html") or "").strip()


def has_user_note(meta: dict[str, Any] | None) -> bool:
    return bool(html_to_plain_text(note_html_from_meta(meta)))


def has_note_sql(alias: str = "r") -> str:
    """SQL fragment: row has non-empty user note (best-effort HTML strip)."""
    col = f"json_extract({alias}.source_meta, '$.user_note_html')"
    stripped = (
        f"TRIM(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE({col}, ''), "
        "'<p>', ''), '</p>', ''), '<br>', ''), '<div>', ''), '</div>', ''), '&nbsp;', ' '))"
    )
    return f"({col} IS NOT NULL AND LENGTH({stripped}) > 0)"


def notes_collection_clause(alias: str = "r") -> str:
    # Paper library entries are intentionally absent from the main feed, but their
    # reading notes still belong in the shared Notes collection.
    visible_source = (
        f"({is_feed_row_sql(alias)} OR "
        f"COALESCE(json_extract({alias}.source_meta, '$.paper_library'), 0) = 1)"
    )
    return f"{alias}.deleted_at IS NULL AND {visible_source} AND {has_note_sql(alias)}"
