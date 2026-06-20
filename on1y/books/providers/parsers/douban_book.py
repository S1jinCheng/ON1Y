"""Parse Douban book search and subject pages."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from on1y.books.cover import normalize_cover_url
from on1y.books.models import BookEditionHit, BookLink, BookWorkDetail

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_SEARCH_URL = "https://search.douban.com/book/subject_search?search_text={query}"


def _parse_search_data(html: str) -> list[dict[str, Any]]:
    marker = "window.__DATA__"
    idx = html.find(marker)
    if idx < 0:
        return []
    start = html.find("{", idx)
    if start < 0:
        return []
    depth = 0
    for pos in range(start, len(html)):
        ch = html[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(html[start : pos + 1])
                except json.JSONDecodeError:
                    return []
                items = data.get("items")
                return items if isinstance(items, list) else []
    return []


def _split_abstract(abstract: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse Douban abstract line into author, translator, publisher, pub_meta."""
    text = (abstract or "").strip()
    if not text:
        return None, None, None, None
    parts = [p.strip() for p in text.split(" / ") if p.strip()]
    if not parts:
        return None, None, None, None
    author = parts[0] if parts else None
    translator: str | None = None
    publisher: str | None = None
    pub_meta: str | None = None
    if len(parts) >= 4:
        translator = parts[1]
        publisher = parts[2]
        pub_meta = " / ".join(parts[3:])
    elif len(parts) == 3:
        publisher = parts[1]
        pub_meta = parts[2]
    elif len(parts) == 2:
        publisher = parts[1]
    return author, translator, publisher, pub_meta


def _edition_from_item(item: dict[str, Any]) -> BookEditionHit | None:
    url = str(item.get("url") or "").strip()
    if "book.douban.com/subject" not in url:
        return None
    subject_id = str(item.get("id") or "").strip()
    if not subject_id and "/subject/" in url:
        m = re.search(r"/subject/(\d+)", url)
        subject_id = m.group(1) if m else ""
    if not subject_id:
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    author, translator, publisher, pub_meta = _split_abstract(str(item.get("abstract") or ""))
    rating_raw = item.get("rating") if isinstance(item.get("rating"), dict) else {}
    rating_val = rating_raw.get("value")
    rating_count = rating_raw.get("count")
    return BookEditionHit(
        edition_id=f"douban:{subject_id}",
        source_id="douban-fetch",
        source_name="豆瓣图书",
        title=title,
        author=author,
        translator=translator,
        publisher=publisher,
        pub_meta=pub_meta,
        rating=float(rating_val) if rating_val is not None else None,
        rating_count=int(rating_count) if rating_count is not None else None,
        cover_url=normalize_cover_url(str(item.get("cover_url") or "").strip() or None),
        url=url,
    )


def search_douban_books(query: str, *, limit: int = 30) -> list[BookEditionHit]:
    text = (query or "").strip()
    if not text:
        return []
    url = _SEARCH_URL.format(query=quote(text))
    try:
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT, "Referer": "https://www.douban.com/"},
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Douban book search failed for %r: %s", text, exc)
        return []
    hits: list[BookEditionHit] = []
    for raw in _parse_search_data(resp.text):
        if not isinstance(raw, dict):
            continue
        edition = _edition_from_item(raw)
        if edition is not None:
            hits.append(edition)
        if len(hits) >= limit:
            break
    return hits


def _info_field(info_text: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}\s*:\s*([^\n|]+)"
    m = re.search(pattern, info_text)
    return m.group(1).strip() if m else None


def _clean_review_text(text: str) -> str:
    cleaned = re.sub(r"\s*\(展开\)\s*", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 500:
        cleaned = cleaned[:497].rstrip() + "…"
    return cleaned


def _parse_short_reviews(soup: BeautifulSoup, *, limit: int = 6) -> list[BookShortReview]:
    """Parse Douban 短评 (hot comments), not 书评 (long reviews)."""
    from on1y.books.models import BookShortReview

    reviews: list[BookShortReview] = []
    for item in soup.select("#score .comment-item, .comment-list .comment-item"):
        short = item.select_one("span.short")
        if not short:
            continue
        content = _clean_review_text(short.get_text(" ", strip=True))
        if not content:
            continue
        author_el = item.select_one(".comment-info a[href*='/people/']")
        author = author_el.get_text(strip=True) if author_el else None
        time_el = item.select_one(".comment-time")
        published_at = time_el.get_text(strip=True) if time_el else None
        reviews.append(
            BookShortReview(
                author=author,
                content=content,
                published_at=published_at,
            )
        )
        if len(reviews) >= limit:
            break
    return reviews


def fetch_douban_subject(url: str) -> BookWorkDetail | None:
    subject_url = (url or "").strip()
    if "book.douban.com/subject" not in subject_url:
        return None
    m = re.search(r"/subject/(\d+)", subject_url)
    if not m:
        return None
    subject_id = m.group(1)
    try:
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT, "Referer": "https://book.douban.com/"},
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            resp = client.get(subject_url)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Douban subject fetch failed %s: %s", subject_url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    title_el = soup.select_one("h1 span")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        return None

    intro_parts: list[str] = []
    link_report = soup.select_one("#link-report")
    if link_report:
        for node in link_report.select("span.all, span.short, .intro"):
            text = node.get_text(" ", strip=True)
            if text and text not in intro_parts:
                intro_parts.append(text)
    summary = "\n\n".join(intro_parts).strip() or None

    info_el = soup.select_one("#info")
    info_text = info_el.get_text("\n", strip=True) if info_el else ""
    author = _info_field(info_text, "作者")
    translator = _info_field(info_text, "译者")
    publisher = _info_field(info_text, "出版社")
    pub_date = _info_field(info_text, "出版年")
    isbn = _info_field(info_text, "ISBN")

    rating_val: float | None = None
    rating_count: int | None = None
    rating_el = soup.select_one("#interest_sectl strong.rating_num")
    if rating_el:
        try:
            rating_val = float(rating_el.get_text(strip=True))
        except ValueError:
            pass
    count_el = soup.select_one("#interest_sectl span[property='v:votes']")
    if count_el:
        try:
            rating_count = int(count_el.get_text(strip=True))
        except ValueError:
            pass

    cover_el = soup.select_one("#mainpic img")
    cover_url = None
    if cover_el:
        cover_url = (
            cover_el.get("src")
            or cover_el.get("data-src")
            or cover_el.get("data-origin")
            or cover_el.get("data-lazy-src")
        )
    short_reviews = _parse_short_reviews(soup)

    return BookWorkDetail(
        edition_id=f"douban:{subject_id}",
        title=title,
        author=author,
        translator=translator,
        publisher=publisher,
        pub_date=pub_date,
        isbn=isbn,
        rating=rating_val,
        rating_count=rating_count,
        cover_url=normalize_cover_url(str(cover_url).strip() if cover_url else None),
        summary=summary,
        short_reviews=short_reviews,
        url=subject_url,
        acquisition_links=[],
    )


def build_acquisition_links(
    *,
    title: str,
    link_sources: list[Any],
) -> list[BookLink]:
    from on1y.books.models import BookSource

    encoded = quote(title.strip())
    links: list[BookLink] = []
    for raw in link_sources:
        if not isinstance(raw, BookSource):
            continue
        if raw.type != "link" or not raw.enabled:
            continue
        url = raw.url_template.replace("{query}", encoded)
        links.append(BookLink(label=raw.name, url=url))
    return links
