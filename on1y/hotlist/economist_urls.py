"""Resolve Economist edition download URLs (epub, not legacy pdf)."""

from __future__ import annotations

import re
from typing import Any

_LEGACY_EPUB_LINE = re.compile(r"^EPUB\s*下载[：:]\s*\S+\s*\n?", re.M | re.I)
_LEGACY_SECTIONS = re.compile(
    r"^##\s*(?:目录|正文预览)\s*\n(?:- .+\n|)*\n?",
    re.M | re.I,
)

from on1y.config import Settings, get_settings
from on1y.hotlist.github_economist import _edition_folder, _epub_url, _raw_base

_PDF_SUFFIX = re.compile(r"\.pdf$", re.I)


def resolve_economist_epub_url(
    url: str,
    meta: dict[str, Any] | None = None,
    *,
    settings: Settings | None = None,
) -> str:
    """Canonical EPUB download URL for a hot-list Economist row."""
    meta = meta or {}
    epub = str(meta.get("epub_url") or "").strip()
    if epub:
        return epub
    raw = str(url or "").strip()
    if _PDF_SUFFIX.search(raw):
        return _PDF_SUFFIX.sub(".epub", raw)
    if raw.endswith(".epub"):
        return raw
    edition = str(meta.get("edition_date") or meta.get("heat_text") or "").strip()
    if edition and re.match(r"^\d{4}-\d{2}-\d{2}$", edition):
        y, m, d = edition.split("-")
        folder = _edition_folder(y, m, d)
        return _epub_url(folder, raw_base=_raw_base(settings or get_settings()))
    return raw


def strip_legacy_economist_body(text: str) -> str:
    """Remove download URL and duplicate TOC headers from pre-refactor stored bodies."""
    cleaned = _LEGACY_EPUB_LINE.sub("", text or "")
    cleaned = _LEGACY_SECTIONS.sub("", cleaned)
    return cleaned.strip()
