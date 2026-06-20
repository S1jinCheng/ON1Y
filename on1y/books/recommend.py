"""Related books on shelf — tag + title/summary overlap, no LLM."""

from __future__ import annotations

import re
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.books.models import BookShelfItem
from on1y.books.shelf import get_shelf_item, list_shelf_items

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _item_tags(item: BookShelfItem) -> set[str]:
    return {t.strip().lower() for t in item.tags if t.strip()}


def find_related_shelf_books(
    storage: SqliteStorage,
    user_id: int,
    item_id: int,
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    source = get_shelf_item(storage, user_id, item_id)
    if source is None:
        return []
    source_tags = _item_tags(source)
    source_blob = " ".join(
        part
        for part in [source.title, source.author or "", source.translator or "", source.summary or ""]
        if part
    )
    source_tokens = _tokens(source_blob)

    scored: list[tuple[float, BookShelfItem]] = []
    for candidate in list_shelf_items(storage, user_id, limit=500):
        if candidate.id == item_id:
            continue
        score = 0.0
        tag_overlap = source_tags & _item_tags(candidate)
        score += len(tag_overlap) * 4.0
        if source.theme_slug and candidate.theme_slug == source.theme_slug:
            score += 2.0
        blob = " ".join(
            part
            for part in [
                candidate.title,
                candidate.author or "",
                candidate.translator or "",
                candidate.summary or "",
            ]
            if part
        )
        overlap = source_tokens & _tokens(blob)
        score += min(len(overlap), 8) * 0.5
        if score <= 0:
            continue
        scored.append((score, candidate))

    scored.sort(key=lambda row: (-row[0], row[1].updated_at))
    out: list[dict[str, Any]] = []
    for _score, item in scored[:limit]:
        out.append(
            {
                "id": item.id,
                "title": item.title,
                "author": item.author,
                "translator": item.translator,
                "cover_url": item.cover_url,
                "summary": (item.summary or "")[:200] or None,
                "tags": item.tags[:6],
                "status": item.status,
            }
        )
    return out
