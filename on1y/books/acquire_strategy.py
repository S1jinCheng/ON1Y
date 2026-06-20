"""Pick ebook candidates across formats (match-first vs format-first)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from on1y.books.edition_match import EditionHints, candidate_text, match_quality, score_candidate
from on1y.books.zlib_links import BOOK_FORMATS

AcquireStrategy = Literal["match_first", "format_first"]


@dataclass(frozen=True)
class ZlibPick:
    book: dict[str, Any]
    fmt: str
    quality: str
    score: float


@dataclass(frozen=True)
class AnnasPick:
    md5: str
    label: str
    fmt: str
    quality: str
    score: float


def normalize_allowed_formats(formats: list[str] | None) -> list[str]:
    if not formats:
        return list(BOOK_FORMATS)
    out: list[str] = []
    for fmt in formats:
        key = str(fmt).lower().strip()
        if key in BOOK_FORMATS and key not in out:
            out.append(key)
    return out or list(BOOK_FORMATS)


def format_search_order(
    *,
    strategy: AcquireStrategy,
    preferred_format: str,
    allowed_formats: list[str],
) -> list[str]:
    allowed = normalize_allowed_formats(allowed_formats)
    preferred = preferred_format if preferred_format in allowed else allowed[0]
    if strategy == "format_first":
        return [preferred] + [f for f in allowed if f != preferred]
    return allowed


def _format_tiebreak(fmt: str, preferred: str) -> float:
    bonus = 1.0 if fmt == preferred else 0.0
    order = {"epub": 0.3, "pdf": 0.2, "mobi": 0.1}
    return bonus + order.get(fmt, 0.0)


def pick_zlib_candidate(
    books_by_fmt: dict[str, list[dict[str, Any]]],
    hints: EditionHints,
    *,
    strategy: AcquireStrategy,
    preferred_format: str,
    format_order: list[str],
) -> ZlibPick | None:
    if strategy == "format_first":
        for fmt in format_order:
            books = books_by_fmt.get(fmt) or []
            if not books:
                continue
            best_book: dict[str, Any] | None = None
            best_score = float("-inf")
            best_text = ""
            for book in books:
                text = candidate_text("", extra=book)
                score = score_candidate(text, hints, extra=book)
                if score > best_score:
                    best_score = score
                    best_book = book
                    best_text = text
            if best_book is not None:
                return ZlibPick(
                    book=best_book,
                    fmt=fmt,
                    quality=match_quality(hints, best_text),
                    score=best_score,
                )
        return None

    best: ZlibPick | None = None
    for fmt, books in books_by_fmt.items():
        for book in books:
            text = candidate_text("", extra=book)
            score = score_candidate(text, hints, extra=book) + _format_tiebreak(fmt, preferred_format)
            if best is None or score > best.score:
                best = ZlibPick(
                    book=book,
                    fmt=fmt,
                    quality=match_quality(hints, text),
                    score=score,
                )
    return best


def pick_annas_candidate(
    candidates_by_fmt: dict[str, list[tuple[str, str]]],
    hints: EditionHints,
    *,
    strategy: AcquireStrategy,
    preferred_format: str,
    format_order: list[str],
) -> AnnasPick | None:
    if strategy == "format_first":
        for fmt in format_order:
            rows = candidates_by_fmt.get(fmt) or []
            if not rows:
                continue
            best_md5 = ""
            best_label = ""
            best_score = float("-inf")
            for md5, label in rows:
                score = score_candidate(label, hints)
                if score > best_score:
                    best_score = score
                    best_md5 = md5
                    best_label = label
            if best_md5:
                return AnnasPick(
                    md5=best_md5,
                    label=best_label,
                    fmt=fmt,
                    quality=match_quality(hints, best_label),
                    score=best_score,
                )
        return None

    best: AnnasPick | None = None
    for fmt, rows in candidates_by_fmt.items():
        for md5, label in rows:
            score = score_candidate(label, hints) + _format_tiebreak(fmt, preferred_format)
            if best is None or score > best.score:
                best = AnnasPick(
                    md5=md5,
                    label=label,
                    fmt=fmt,
                    quality=match_quality(hints, label),
                    score=score,
                )
    return best
