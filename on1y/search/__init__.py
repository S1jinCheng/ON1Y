"""Full-text search for the knowledge archive."""

from on1y.search.fts import (
    delete_fts_row,
    index_raw_item,
    prepare_fts_query,
    rebuild_knowledge_fts,
    search_knowledge_fts,
)

__all__ = [
    "delete_fts_row",
    "index_raw_item",
    "prepare_fts_query",
    "rebuild_knowledge_fts",
    "search_knowledge_fts",
]
