"""Resolve bookshelf fields from Douban search vs picked download candidate."""

from __future__ import annotations

import re
from typing import Any

from on1y.books.edition_match import EditionHints, match_quality
from on1y.books.translator_match import candidate_blob, translator_matches_hint

from on1y.books.display_name import enrich_fields_from_candidate, parse_translator_from_text


def edition_aligns_with_douban(hints: EditionHints, candidate: dict[str, Any]) -> bool:
    """True when the picked file likely matches the Douban edition the user searched."""
    blob = candidate_blob(candidate)
    if hints.translator and not translator_matches_hint(hints.translator, candidate):
        return False
    if hints.translator:
        return True
    return match_quality(hints, blob) != "low"


def parse_translator_from_candidate(candidate: dict[str, Any]) -> str | None:
    return parse_translator_from_text(
        candidate.get("title"),
        candidate.get("author"),
        candidate.get("translator"),
    )


def _display_title(hints: EditionHints, candidate: dict[str, Any], *, aligned: bool) -> str:
    cand_title = str(candidate.get("title") or "").strip()
    base = (hints.title or "").strip()
    if aligned:
        return base or cand_title
    if base and base in cand_title:
        return base
    return cand_title[:500] if cand_title else base


def _mismatch_summary(hints: EditionHints, candidate: dict[str, Any]) -> str:
    picked = str(candidate.get("title") or "").strip()
    author = str(candidate.get("author") or "").strip()
    parts = ["所选版本来自 Z-Library"]
    if picked:
        parts.append(f"：{picked[:300]}")
    if author:
        parts.append(f"（{author}）")
    parts.append("。")
    if hints.translator:
        parts.append(f"与豆瓣检索译者「{hints.translator.strip()}」不一致，未采用豆瓣简介。")
    else:
        parts.append("与豆瓣检索条目不完全一致，未采用豆瓣简介。")
    return "".join(parts)[:4000]


def resolve_shelf_metadata(
    hints: EditionHints,
    candidate: dict[str, Any] | None,
    *,
    cover_url: str | None = None,
) -> dict[str, Any]:
    """Build shelf row fields: Douban edition when aligned, else picked file metadata."""
    if not candidate:
        return {
            "title": hints.title.strip(),
            "author": hints.author,
            "translator": hints.translator,
            "publisher": hints.publisher,
            "summary": None,
            "cover_url": cover_url,
            "douban_enrich": True,
            "match_quality": "high",
            "notes_extra": "",
        }

    blob = candidate_blob(candidate)
    quality = match_quality(hints, blob, candidate=candidate)
    aligned = edition_aligns_with_douban(hints, candidate)

    if aligned:
        title_out, author_out, translator_out, publisher_out, language = enrich_fields_from_candidate(
            title=_display_title(hints, candidate, aligned=True),
            author=hints.author or candidate.get("author"),
            translator=hints.translator or parse_translator_from_candidate(candidate),
            publisher=hints.publisher or candidate.get("publisher"),
            candidate=candidate,
        )
        return {
            "title": title_out,
            "author": author_out,
            "translator": translator_out,
            "publisher": publisher_out,
            "language": language,
            "summary": None,
            "cover_url": cover_url,
            "douban_enrich": True,
            "match_quality": quality,
            "notes_extra": "",
        }

    parsed_tr = parse_translator_from_candidate(candidate)
    title_out, author_out, translator_out, publisher_out, language = enrich_fields_from_candidate(
        title=_display_title(hints, candidate, aligned=False),
        author=candidate.get("author") or hints.author,
        translator=parsed_tr,
        publisher=candidate.get("publisher"),
        candidate=candidate,
    )
    notes_extra = (
        "douban_enrich: false\n"
        f"match_quality: {quality}\n"
        f"picked_title: {str(candidate.get('title') or '')[:300]}\n"
    )
    if hints.translator:
        notes_extra += f"douban_ref_translator: {hints.translator.strip()}\n"

    return {
        "title": title_out,
        "author": author_out,
        "translator": translator_out,
        "publisher": publisher_out,
        "language": language,
        "summary": _mismatch_summary(hints, candidate),
        "cover_url": cover_url,
        "douban_enrich": False,
        "match_quality": quality,
        "notes_extra": notes_extra,
    }


def douban_enrich_allowed(*, notes: str | None) -> bool:
    if not notes:
        return True
    if re.search(r"douban_enrich:\s*false", notes, re.IGNORECASE):
        return False
    return True
