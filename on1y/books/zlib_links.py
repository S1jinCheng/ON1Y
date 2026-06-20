"""Z-Library search URLs and edition download link rows."""

from __future__ import annotations

from urllib.parse import quote

from on1y.books.builtin_sources import ANNAS_BASE, CARD_ONLY_LINK_IDS, ZLIB_BASE
from on1y.books.models import BookLink
from on1y.books.settings_store import DEFAULT_ZLIB_BASE

BOOK_FORMATS: tuple[str, ...] = ("epub", "pdf", "mobi")


def edition_search_query(
    title: str,
    *,
    author: str | None = None,
    translator: str | None = None,
) -> str:
    parts = [(title or "").strip()]
    if author and author.strip():
        parts.append(author.strip())
    if translator and translator.strip():
        parts.append(translator.strip())
    return " ".join(p for p in parts if p)


def zlib_general_search_url(query: str, *, base_url: str = ZLIB_BASE) -> str:
    text = (query or "").strip()
    base = (base_url or ZLIB_BASE or DEFAULT_ZLIB_BASE).rstrip("/")
    if not text:
        return base
    return f"{base}/s/{quote(text, safe='')}"


def zlib_search_url(
    title: str,
    fmt: str,
    *,
    author: str | None = None,
    translator: str | None = None,
    base_url: str = ZLIB_BASE,
) -> str:
    text = edition_search_query(title, author=author, translator=translator)
    base = (base_url or ZLIB_BASE or DEFAULT_ZLIB_BASE).rstrip("/")
    return f"{base}/s/{quote(text, safe='')}?extension={fmt}"


def annas_search_url(title: str, *, author: str | None = None, translator: str | None = None) -> str:
    text = edition_search_query(title, author=author, translator=translator)
    return f"{ANNAS_BASE}/search?q={quote(text, safe='')}"


def build_source_browse_links(
    *,
    title: str,
    douban_url: str,
    author: str | None = None,
    translator: str | None = None,
    zlib_base_url: str = ZLIB_BASE,
    annas_enabled: bool = True,
    zlib_enabled: bool = True,
) -> list[BookLink]:
    """豆瓣 + Z-Library + 安娜档案 browse links (detail panel)."""
    query = edition_search_query(title, author=author, translator=translator)
    links = [BookLink(label="豆瓣", url=douban_url)]
    if zlib_enabled:
        links.append(
            BookLink(
                label="Z-Library",
                url=zlib_general_search_url(query, base_url=zlib_base_url),
            )
        )
    if annas_enabled:
        links.append(
            BookLink(label="安娜档案", url=annas_search_url(title, author=author, translator=translator))
        )
    return links


def build_edition_links(
    *,
    title: str,
    douban_url: str,
    author: str | None = None,
    translator: str | None = None,
    zlib_base_url: str = ZLIB_BASE,
    annas_enabled: bool = True,
    zlib_enabled: bool = True,
) -> list[BookLink]:
    links = [BookLink(label="豆瓣", url=douban_url)]
    if zlib_enabled:
        for fmt in BOOK_FORMATS:
            links.append(
                BookLink(
                    label=fmt.upper(),
                    url=zlib_search_url(
                        title,
                        fmt,
                        author=author,
                        translator=translator,
                        base_url=zlib_base_url,
                    ),
                )
            )
    if annas_enabled:
        links.append(
            BookLink(
                label="安娜档案",
                url=annas_search_url(title, author=author, translator=translator),
            )
        )
    return links
