"""Resolve clean display titles for Zhihu URLs (pins, answers, articles)."""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx

from on1y.config import Settings, get_settings
from on1y.ingestion.zhihu_follow_list import DEFAULT_HEADERS, ZHIHU_API, _cookie_jar
from on1y.utils.zhihu_author import (
    _ANSWER_ID_RE,
    _ARTICLE_ID_RE,
    _PIN_ID_RE,
    _QUESTION_ID_RE,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_BOOK_TITLE_RE = re.compile(r"《([^》]{2,200})》")
_RSS_ACTION_RE = re.compile(
    r"^[\w\u4e00-\u9fff·.\-]+(?:发布了想法|赞同了想法|发布了文章)[：:]\s*(.+)$",
    re.DOTALL,
)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    plain = _TAG_RE.sub(" ", unescape(str(text)))
    return _WS_RE.sub(" ", plain).strip()


def clean_rss_entry_title(entry: str | None) -> str:
    """Turn RSSHub activity titles into readable plain text."""
    text = strip_html(entry)
    if not text:
        return ""
    match = _RSS_ACTION_RE.match(text)
    if match:
        text = match.group(1).strip()
    book = _BOOK_TITLE_RE.search(text)
    if book:
        return book.group(1).strip()
    if len(text) > 160:
        text = text[:160].rstrip() + "…"
    return text


def _title_from_pin_payload(payload: dict[str, Any]) -> str | None:
    for key in ("excerpt_title", "content_html"):
        cleaned = clean_rss_entry_title(str(payload.get(key) or ""))
        if cleaned:
            book = _BOOK_TITLE_RE.search(cleaned)
            if book:
                return book.group(1).strip()
            if len(cleaned) >= 4:
                return cleaned
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        cleaned = clean_rss_entry_title(str(block.get("content") or block.get("own_text") or ""))
        if not cleaned:
            continue
        book = _BOOK_TITLE_RE.search(cleaned)
        if book:
            return book.group(1).strip()
        if len(cleaned) >= 8:
            return cleaned[:200]
    return None


def _title_from_answer_payload(payload: dict[str, Any]) -> str | None:
    title = str(payload.get("title") or "").strip()
    if title:
        return strip_html(title)
    question = payload.get("question")
    if isinstance(question, dict):
        q_title = str(question.get("title") or "").strip()
        if q_title:
            return strip_html(q_title)
    return None


def fetch_zhihu_title_for_url(
    url: str,
    *,
    cookie_path=None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    settings = settings or get_settings()
    answer_match = _ANSWER_ID_RE.search(url)
    article_match = _ARTICLE_ID_RE.search(url)
    pin_match = _PIN_ID_RE.search(url)
    question_match = _QUESTION_ID_RE.search(url)
    if not any((answer_match, article_match, pin_match, question_match)):
        return None

    path = cookie_path or settings.zhihu_cookies_path
    jar = _cookie_jar(path)
    if not jar:
        return None

    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    try:
        assert client is not None
        if answer_match:
            response = client.get(f"{ZHIHU_API}/answers/{answer_match.group(1)}")
            if response.status_code == 200:
                return _title_from_answer_payload(response.json())
            return None

        if pin_match:
            response = client.get(f"{ZHIHU_API}/pins/{pin_match.group(1)}")
            if response.status_code == 200:
                return _title_from_pin_payload(response.json())
            return None

        if question_match and not answer_match:
            qid = question_match.group(1)
            response = client.get(f"{ZHIHU_API}/questions/{qid}/answers", params={"limit": 1})
            if response.status_code == 200:
                batch = response.json().get("data") or []
                if batch:
                    target = batch[0]
                    question = target.get("question")
                    if isinstance(question, dict):
                        q_title = str(question.get("title") or "").strip()
                        if q_title:
                            return strip_html(q_title)
            return None

        article_id = article_match.group(1) if article_match else ""
        host = urlparse(url).netloc.lower()
        api_base = "https://zhuanlan.zhihu.com/api" if "zhuanlan" in host else f"{ZHIHU_API}/articles"
        response = client.get(f"{api_base}/articles/{article_id}")
        if response.status_code != 200:
            return None
        payload = response.json()
        title = payload.get("title")
        if not title and isinstance(payload.get("data"), dict):
            title = payload["data"].get("title")
        cleaned = strip_html(str(title or ""))
        return cleaned or None
    except Exception:
        return None
    finally:
        if own_client and client is not None:
            client.close()


def resolve_zhihu_title(
    url: str,
    raw_title: str | None,
    meta: dict[str, Any] | None = None,
    *,
    fetch_api: bool = True,
) -> str:
    """Pick the best plain-text title for storage and UI."""
    meta = meta or {}
    title = strip_html(str(raw_title or ""))
    entry = clean_rss_entry_title(str(meta.get("entry_title") or ""))

    def _looks_ok(value: str) -> bool:
        if not value or len(value) < 2:
            return False
        if value.startswith("http"):
            return False
        if "zhihu.com" in value or "zhuanlan.zhihu.com" in value:
            return False
        return True

    if _looks_ok(title) and "发布了想法" not in title and "赞同了想法" not in title:
        return title[:500]

    if _looks_ok(entry):
        return entry[:500]

    if fetch_api:
        api_title = fetch_zhihu_title_for_url(url)
        if _looks_ok(api_title or ""):
            return str(api_title)[:500]

    if _looks_ok(title):
        return title[:500]
    if _looks_ok(entry):
        return entry[:500]
    return "知乎内容"
