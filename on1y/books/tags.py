"""LLM flat tags for shelf books (title + blurb only, no ebook body)."""

from __future__ import annotations

import logging
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.books.models import BookShelfItem

logger = logging.getLogger(__name__)

BOOK_SHELF_TAG_PROMPT_VERSION = "book-shelf-tags-v1"


def build_book_shelf_tag_system_prompt(*, locale: str) -> str:
    lang = "English" if locale.lower().startswith("en") else "Chinese"
    return f"""You label books on a personal bookshelf for browsing and discovery. Respond in {lang} only.

Return ONE JSON object (no markdown):
{{"tags": ["tag1", "tag2", "tag3", "tag4"]}}

Rules:
- 3-6 short flat tags (genre, topic, era, audience, classic/modern, etc.).
- Use title, author, translator, and summary/blurb only — never invent plot details.
- No author or translator names in tags; no hashtags; no duplicates.
- ALL tag strings must be in {lang}."""


def _build_user_prompt(item: BookShelfItem) -> str:
    parts = [f"Title: {item.title.strip()}"]
    if item.author and item.author.strip():
        parts.append(f"Author: {item.author.strip()}")
    if item.translator and item.translator.strip():
        parts.append(f"Translator: {item.translator.strip()}")
    if item.summary and item.summary.strip():
        parts.append(f"Summary: {item.summary.strip()[:1200]}")
    return "\n\n".join(parts)


def needs_book_shelf_tags(meta: dict[str, Any], *, force: bool = False) -> bool:
    if force:
        return True
    return meta.get("book_shelf_tags_version") != BOOK_SHELF_TAG_PROMPT_VERSION


def distill_book_shelf_tags(
    storage: SqliteStorage,
    raw_id: int,
    item: BookShelfItem,
    *,
    locale: str | None = None,
    force: bool = False,
) -> list[str]:
    from on1y.config import get_settings
    from on1y.exceptions import ConfigurationError
    from on1y.llm.client import get_llm_client

    settings = get_settings()
    raw = storage.get_raw_by_id(raw_id)
    if raw is None:
        raise ValueError(f"raw_item not found: {raw_id}")

    meta = dict(raw.source_meta or {})
    if not needs_book_shelf_tags(meta, force=force):
        return storage.get_item_tag_names(raw_id)

    lang = locale or settings.llm_locale
    client = get_llm_client()
    try:
        parsed = client.chat_json(
            build_book_shelf_tag_system_prompt(locale=lang),
            _build_user_prompt(item),
            max_tokens=256,
        )
    except ConfigurationError:
        raise
    except Exception as exc:
        logger.warning("Book shelf tag LLM failed raw_id=%s: %s", raw_id, exc)
        raise

    raw_tags = parsed.get("tags") if isinstance(parsed, dict) else None
    if not isinstance(raw_tags, list):
        raw_tags = []
    names: list[str] = []
    seen: set[str] = set()
    for entry in raw_tags:
        label = str(entry).strip().lstrip("#")
        if not label or label in seen:
            continue
        seen.add(label)
        names.append(label[:40])
        if len(names) >= 6:
            break

    if names:
        storage.merge_llm_tags(raw_id, names)

    storage.merge_source_meta(
        raw_id,
        {"book_shelf_tags_version": BOOK_SHELF_TAG_PROMPT_VERSION},
    )
    return storage.get_item_tag_names(raw_id)
