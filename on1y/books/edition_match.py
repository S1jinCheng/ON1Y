"""Score remote ebook candidates against a Douban edition selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EditionHints:
    title: str
    author: str | None = None
    translator: str | None = None
    publisher: str | None = None
    isbn: str | None = None

    def search_query(self) -> str:
        parts = [(self.title or "").strip()]
        if self.author and self.author.strip():
            parts.append(self.author.strip())
        if self.translator and self.translator.strip():
            parts.append(self.translator.strip())
        return " ".join(p for p in parts if p)


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def candidate_text(blob: str, extra: dict | None = None) -> str:
    chunks = [blob]
    if extra:
        for key in ("title", "author", "publisher", "description", "biblio", "language", "year"):
            value = extra.get(key)
            if value:
                chunks.append(str(value))
    return " ".join(chunks)


def score_candidate(blob: str, hints: EditionHints, *, extra: dict | None = None) -> float:
    text = _norm(candidate_text(blob, extra))
    score = 0.0
    title = _norm(hints.title)
    if title and title in text:
        score += 15.0
    translator = _norm(hints.translator)
    if translator:
        if translator in text:
            score += 60.0
        else:
            score -= 25.0
    author = _norm(hints.author)
    if author and author in text:
        score += 25.0
    publisher = _norm(hints.publisher)
    if publisher and publisher in text:
        score += 12.0
    isbn = (hints.isbn or "").replace("-", "").strip()
    if isbn and isbn.lower() in text.replace("-", ""):
        score += 40.0
    return score


def pick_best_index(candidates: list[str], hints: EditionHints, *, extras: list[dict] | None = None) -> int:
    if not candidates:
        return 0
    best_i = 0
    best_score = float("-inf")
    for i, blob in enumerate(candidates):
        extra = extras[i] if extras and i < len(extras) else None
        score = score_candidate(blob, hints, extra=extra)
        if score > best_score:
            best_score = score
            best_i = i
    return best_i


def match_quality(hints: EditionHints, chosen_text: str, *, candidate: dict | None = None) -> str:
    """high | medium | low — for user-facing warnings."""
    from on1y.books.translator_match import translator_matches_hint

    score = score_candidate(chosen_text, hints)
    if hints.translator:
        if candidate is not None:
            if not translator_matches_hint(hints.translator, candidate):
                return "low"
        elif _norm(hints.translator) not in _norm(chosen_text):
            return "low"
    if score >= 50:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def score_reasons(
    blob: str,
    hints: EditionHints,
    *,
    extra: dict | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Return total score and human-readable scoring breakdown."""
    text = _norm(candidate_text(blob, extra))
    reasons: list[dict[str, Any]] = []
    score = 0.0

    title = _norm(hints.title)
    if title and title in text:
        score += 15.0
        reasons.append({"label": f"书名包含「{hints.title.strip()}」", "delta": 15})

    translator = _norm(hints.translator)
    if translator:
        if translator in text:
            score += 60.0
            reasons.append({"label": f"译者「{hints.translator.strip()}」匹配", "delta": 60})
        else:
            score -= 25.0
            reasons.append({"label": f"未找到译者「{hints.translator.strip()}」", "delta": -25})

    author = _norm(hints.author)
    if author and author in text:
        score += 25.0
        reasons.append({"label": f"作者「{hints.author.strip()}」匹配", "delta": 25})

    publisher = _norm(hints.publisher)
    if publisher and publisher in text:
        score += 12.0
        reasons.append({"label": f"出版社「{hints.publisher.strip()}」匹配", "delta": 12})

    isbn = (hints.isbn or "").replace("-", "").strip()
    if isbn and isbn.lower() in text.replace("-", ""):
        score += 40.0
        reasons.append({"label": f"ISBN {hints.isbn} 匹配", "delta": 40})

    return score, reasons
