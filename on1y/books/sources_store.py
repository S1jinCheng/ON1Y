"""Per-user book source configuration (JSON file)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from on1y.books.builtin_sources import builtin_sources, merge_builtin_sources
from on1y.books.models import BookSource, BookSourcesFile
from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)

DEFAULT_SOURCES: list[BookSource] = builtin_sources()


def user_books_sources_path(user_id: int) -> Path:
    books_dir = user_dir(user_id) / "books"
    books_dir.mkdir(parents=True, exist_ok=True)
    return books_dir / "sources.json"


def _normalize_payload(payload: BookSourcesFile) -> BookSourcesFile:
    merged = merge_builtin_sources(payload.sources)
    return BookSourcesFile(version=payload.version, sources=merged)


def load_book_sources(user_id: int) -> BookSourcesFile:
    path = user_books_sources_path(user_id)
    if not path.is_file():
        payload = BookSourcesFile(sources=builtin_sources())
        save_book_sources(user_id, payload)
        return payload
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = BookSourcesFile.model_validate(data)
    except Exception:
        logger.warning("Invalid books sources file %s; resetting builtins", path)
        raw = BookSourcesFile(sources=builtin_sources())
    payload = _normalize_payload(raw)
    if payload.model_dump() != raw.model_dump():
        save_book_sources(user_id, payload)
    return payload


def save_book_sources(user_id: int, payload: BookSourcesFile) -> None:
    normalized = _normalize_payload(payload)
    path = user_books_sources_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def list_enabled_sources(user_id: int) -> list[BookSource]:
    payload = load_book_sources(user_id)
    return sorted(
        [s for s in payload.sources if s.enabled],
        key=lambda s: (s.sort_order, s.name),
    )
