"""Aggregate external book search across user-configured sources."""

from __future__ import annotations

from urllib.parse import quote

from on1y.books.builtin_sources import CARD_ONLY_LINK_IDS
from on1y.books.models import BookEditionHit, BookSearchHit, BookSource
from on1y.books.providers.parsers.douban_book import search_douban_books
from on1y.books.sources_store import list_enabled_sources


def _expand_link(source: BookSource, query: str) -> BookSearchHit:
    encoded = quote(query.strip())
    url = source.url_template.replace("{query}", encoded)
    return BookSearchHit(
        source_id=source.id,
        source_name=source.name,
        query=query.strip(),
        url=url,
        kind="link",
    )


def search_books(
    user_id: int,
    query: str,
    *,
    source_ids: list[str] | None = None,
) -> tuple[list[BookEditionHit], list[BookSearchHit]]:
    text = (query or "").strip()
    if not text:
        return [], []
    enabled = list_enabled_sources(user_id)
    allowed = {sid.strip() for sid in source_ids if sid.strip()} if source_ids else None
    if allowed is not None:
        enabled = [s for s in enabled if s.id in allowed]

    editions: list[BookEditionHit] = []
    links: list[BookSearchHit] = []

    douban_ids = {"douban-fetch", "douban-link"}
    run_douban = allowed is None or bool(douban_ids & allowed)
    if run_douban and any(s.id in douban_ids and s.enabled for s in list_enabled_sources(user_id)):
        editions = search_douban_books(text)

    for source in enabled:
        if source.type != "link":
            continue
        if source.id in ("douban-link",) or source.id in CARD_ONLY_LINK_IDS:
            continue
        links.append(_expand_link(source, text))

    return editions, links
