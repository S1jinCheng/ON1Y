"""Chat archive collection (Telegram conversations in raw_items)."""

from __future__ import annotations


def chats_collection_clause(alias: str = "r") -> str:
    """SQL fragment: row belongs to the chats collection."""
    return (
        f"{alias}.deleted_at IS NULL AND "
        f"(LOWER({alias}.platform) = 'telegram' OR "
        f"COALESCE(json_extract({alias}.source_meta, '$.conversation'), 0) = 1)"
    )
