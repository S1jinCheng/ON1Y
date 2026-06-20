"""Built-in book sources — fixed URLs, only enable/disable is user-configurable."""

from __future__ import annotations

from on1y.books.models import BookSource

ZLIB_BASE = "https://zh.z-lib.help"
ANNAS_BASE = "https://tw.annas-archive.gl"

BUILTIN_IDS = frozenset({"douban-fetch", "zlib-link", "annas-link"})

# Shown on edition cards; omit from search footer links.
CARD_ONLY_LINK_IDS = frozenset({"zlib-link"})


def builtin_sources() -> list[BookSource]:
    return [
        BookSource(
            id="douban-fetch",
            name="豆瓣",
            type="fetch",
            parser="douban_book",
            enabled=True,
            url_template="https://search.douban.com/book/subject_search?search_text={query}",
            sort_order=0,
        ),
        BookSource(
            id="zlib-link",
            name="Z-Library",
            type="link",
            enabled=True,
            url_template=f"{ZLIB_BASE}/s/{{query}}",
            sort_order=1,
        ),
        BookSource(
            id="annas-link",
            name="安娜档案",
            type="link",
            enabled=True,
            url_template=f"{ANNAS_BASE}/search?q={{query}}",
            sort_order=2,
        ),
    ]


def merge_builtin_sources(existing: list[BookSource]) -> list[BookSource]:
    """Keep user enable flags; always use built-in definitions (drops Open Library etc.)."""
    enabled_by_id = {s.id: s.enabled for s in existing}
    merged: list[BookSource] = []
    for source in builtin_sources():
        enabled = enabled_by_id.get(source.id, source.enabled)
        merged.append(source.model_copy(update={"enabled": enabled}))
    return merged
