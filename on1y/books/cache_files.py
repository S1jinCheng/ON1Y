"""Locate cached ebook files for a shelf title."""

from __future__ import annotations

import re
from pathlib import Path

from on1y.books.acquire import _safe_filename
from on1y.books.settings_store import load_book_settings
from on1y.books.zlib_links import BOOK_FORMATS
from on1y.user.paths import resolve_books_cache_dir

_CACHED_RE = re.compile(r"cached:\s*(.+)", re.IGNORECASE)


def cached_paths_from_notes(notes: str | None) -> list[Path]:
    if not notes:
        return []
    paths: list[Path] = []
    for match in _CACHED_RE.finditer(notes):
        raw = (match.group(1) or "").strip()
        if raw:
            paths.append(Path(raw))
    return paths


def list_cached_ebooks(user_id: int, title: str, *, notes: str | None = None) -> list[dict[str, str]]:
    """Return local ebook files for a title (from notes + cache dir scan)."""
    settings = load_book_settings(user_id)
    cache_dir = resolve_books_cache_dir(user_id, settings.cache_dir)
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    def add(path: Path, fmt: str) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            return
        if resolved in seen or not path.is_file() or path.stat().st_size < 1024:
            return
        seen.add(resolved)
        out.append({"format": fmt, "path": resolved})

    for path in cached_paths_from_notes(notes):
        ext = path.suffix.lstrip(".").lower()
        if ext in BOOK_FORMATS:
            add(path, ext)

    for fmt in BOOK_FORMATS:
        add(cache_dir / _safe_filename(title, fmt), fmt)

    return out
