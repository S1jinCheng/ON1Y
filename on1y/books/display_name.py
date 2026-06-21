"""Canonical book display / Kindle subject: 书名 [国家]作者 著;译者 译 出版社"""

from __future__ import annotations

import re
from typing import Any

from on1y.books.models import BookShelfItem

_COUNTRY_BRACKET_RE = re.compile(r"^\[([^\]]+)\]\s*")
_COUNTRY_PAREN_RE = re.compile(r"^[（(]([^）)]+)[）)]\s*")
_AUTHOR_ZHU_RE = re.compile(r"\s*著\s*$")
_TRANSLATOR_SEMI_RE = re.compile(r"著\s*;\s*([^;，,]+?)\s*译")
_TRANSLATOR_PLAIN_RE = re.compile(r"([\u4e00-\u9fff·A-Za-z]{2,30})\s*译")
_PUBLISHER_AFTER_YI_RE = re.compile(r"译\s+(.+?)\s*$")

_LANG_COUNTRY: dict[str, str] = {
    "chinese": "中",
    "zh": "中",
    "english": "英",
    "en": "英",
    "french": "法",
    "fr": "法",
    "german": "德",
    "de": "德",
    "japanese": "日",
    "ja": "日",
    "russian": "俄",
    "ru": "俄",
}


def _language_country(language: str | None) -> str | None:
    if not language:
        return None
    key = str(language).strip().lower().replace("_", "-").split("-")[0]
    return _LANG_COUNTRY.get(key)


def split_author_country(author: str | None) -> tuple[str | None, str | None]:
    """Return (country_label, author_name_without_country)."""
    text = (author or "").strip()
    if not text:
        return None, None
    country: str | None = None
    match = _COUNTRY_BRACKET_RE.match(text)
    if match:
        country = match.group(1).strip()
        text = text[match.end() :].strip()
    else:
        match = _COUNTRY_PAREN_RE.match(text)
        if match:
            country = match.group(1).strip()
            text = text[match.end() :].strip()
    text = _AUTHOR_ZHU_RE.sub("", text).strip()
    text = text.rstrip(";；,，").strip()
    return country or None, text or None


def parse_translator_from_text(*texts: str | None) -> str | None:
    blob = " ".join(str(t).strip() for t in texts if t and str(t).strip())
    if not blob:
        return None
    match = _TRANSLATOR_SEMI_RE.search(blob)
    if match:
        name = match.group(1).strip(" /，,;；")
        if 2 <= len(name) <= 30:
            return name
    for match in _TRANSLATOR_PLAIN_RE.finditer(blob):
        name = match.group(1).strip()
        if name in ("翻", "编", "选", "校"):
            continue
        if 2 <= len(name) <= 30:
            return name
    return None


def parse_publisher_from_text(text: str | None) -> str | None:
    blob = (text or "").strip()
    if not blob:
        return None
    match = _PUBLISHER_AFTER_YI_RE.search(blob)
    if not match:
        return None
    pub = match.group(1).strip(" /，,;；")
    return pub[:120] if pub else None


def parse_author_from_title(title: str | None) -> str | None:
    blob = (title or "").strip()
    if not blob:
        return None
    match = re.search(
        r"(\[[^\]]+\][^;；]+?)\s*著",
        blob,
    )
    if match:
        return match.group(1).strip()
    match = re.search(r"([^;；]+?)\s*著", blob)
    if match:
        return match.group(1).strip()
    return None


def enrich_fields_from_candidate(
    *,
    title: str,
    author: str | None,
    translator: str | None,
    publisher: str | None,
    candidate: dict[str, Any] | None,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    """Fill missing bibliographic fields from Z-Library candidate title."""
    cand_title = str((candidate or {}).get("title") or "").strip()
    language = str((candidate or {}).get("language") or "").strip() or None

    author_out = author or (candidate or {}).get("author")
    if isinstance(author_out, str):
        author_out = author_out.strip() or None

    if not author_out and cand_title:
        author_out = parse_author_from_title(cand_title)

    translator_out = translator or parse_translator_from_text(cand_title, (candidate or {}).get("author"))
    publisher_out = publisher or (candidate or {}).get("publisher")
    if isinstance(publisher_out, str):
        publisher_out = publisher_out.strip() or None
    if not publisher_out:
        publisher_out = parse_publisher_from_text(cand_title)

    title_out = (title or "").strip() or cand_title
    return title_out, author_out, translator_out, publisher_out, language


def format_book_label(
    *,
    title: str,
    author: str | None = None,
    translator: str | None = None,
    publisher: str | None = None,
    language: str | None = None,
    max_len: int = 200,
) -> str:
    """
    国富论 [英]亚当·斯密 著;胡长明 译 人民日报出版社
    """
    book_title = (title or "").strip()
    country, author_name = split_author_country(author)
    if not country:
        country = _language_country(language)

    chunks: list[str] = []
    if book_title:
        chunks.append(book_title)

    if author_name:
        author_chunk = f"[{country}]{author_name}" if country else author_name
        if not author_chunk.endswith("著"):
            author_chunk += " 著"
        chunks.append(author_chunk)

    tr = (translator or "").strip().rstrip("译").strip()
    tr_chunk = ""
    if tr:
        tr_chunk = f";{tr} 译"

    pub = (publisher or "").strip()
    pub_chunk = f" {pub}" if pub else ""

    if not chunks:
        label = (tr_chunk + pub_chunk).strip() or book_title or "book"
    else:
        label = " ".join(chunks) + tr_chunk + pub_chunk

    label = re.sub(r"\s+", " ", label).strip()
    if len(label) > max_len:
        label = label[: max_len - 1].rstrip() + "…"
    return label


def format_book_label_from_shelf(item: BookShelfItem) -> str:
    return format_book_label(
        title=item.title,
        author=item.author,
        translator=item.translator,
        publisher=item.publisher,
    )
