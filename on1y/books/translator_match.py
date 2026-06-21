"""Fuzzy translator matching between Douban hints and download candidates."""

from __future__ import annotations

import re
from typing import Any

from on1y.books.display_name import parse_translator_from_text
from on1y.books.edition_match import candidate_text

_PUNCT_RE = re.compile(r"[/／,，、;；|]+")
_TRAILING_YI_RE = re.compile(r"\s*译\s*$")
_TRAILING_DENG_RE = re.compile(r"等\s*$")
_SPACE_RE = re.compile(r"\s+")
_PUBLISHER_RE = re.compile(r"出版社|出版集团|出版公司|书局|书社|Press|Publishing", re.I)


def _looks_like_publisher(text: str | None) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _PUBLISHER_RE.search(t):
        return True
    if re.fullmatch(r"\d{4}([-/年]\d{1,2})?", t):
        return True
    return False


def _norm(text: str | None) -> str:
    return _SPACE_RE.sub("", (text or "").strip().lower())


def candidate_blob(candidate: dict[str, Any]) -> str:
    return candidate_text(
        str(candidate.get("title") or ""),
        {
            "author": candidate.get("author"),
            "publisher": candidate.get("publisher"),
            "year": candidate.get("year"),
            "language": candidate.get("language"),
        },
    )


def _clean_token(text: str) -> str:
    token = (text or "").strip()
    token = _TRAILING_YI_RE.sub("", token)
    token = _TRAILING_DENG_RE.sub("", token).strip()
    return token


def extract_translator_tokens(translator: str | None) -> list[str]:
    if not translator or not str(translator).strip():
        return []
    raw = str(translator).strip()
    parts = [p.strip() for p in _PUNCT_RE.split(raw) if p.strip()]
    if not parts:
        parts = [raw]
    tokens: list[str] = []
    for part in parts:
        cleaned = _clean_token(part)
        if len(cleaned) >= 2:
            tokens.append(cleaned)
    return tokens


def _tokens_overlap(left: str, right: str) -> bool:
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    # 唐日松 vs 唐日松等
    if len(a) >= 2 and a in b:
        return True
    if len(b) >= 2 and b in a:
        return True
    return False


def translator_matches_hint(hint: str | None, candidate: dict[str, Any]) -> bool:
    """True when Douban translator hint is compatible with the picked file metadata."""
    if not hint or not str(hint).strip():
        return True

    hint_raw = str(hint).strip()
    if _looks_like_publisher(hint_raw):
        return True

    blob = candidate_blob(candidate)
    blob_norm = _norm(blob)
    hint_norm = _norm(hint_raw)

    if hint_norm in blob_norm:
        return True

    for token in extract_translator_tokens(hint_raw):
        if _norm(token) in blob_norm:
            return True

    parsed = parse_translator_from_text(
        candidate.get("title"),
        candidate.get("author"),
        candidate.get("publisher"),
    )
    if parsed:
        if _tokens_overlap(hint_raw, parsed):
            return True
        for token in extract_translator_tokens(hint_raw):
            if _tokens_overlap(token, parsed):
                return True

    return False
