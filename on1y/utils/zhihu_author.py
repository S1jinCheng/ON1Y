"""Resolve Zhihu author name / avatar / profile URL from API payloads."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from on1y.config import Settings, get_settings
from on1y.ingestion.zhihu_follow_list import DEFAULT_HEADERS, ZHIHU_API, _cookie_jar
from on1y.utils.author_meta import author_meta_patch

_ANSWER_ID_RE = re.compile(r"/answer/(\d+)")
_ARTICLE_ID_RE = re.compile(r"/p/(\d+)")
_PIN_ID_RE = re.compile(r"/pin/(\d+)")
_PEOPLE_TOKEN_RE = re.compile(r"/people/([^/?#]+)")
_QUESTION_ID_RE = re.compile(r"/question/(\d+)")


def _normalize_avatar_url(url: str | None) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    return value


def author_meta_from_user(user: dict[str, Any] | None) -> dict[str, str]:
    if not user:
        return {}
    name = str(user.get("name") or "").strip()
    avatar = _normalize_avatar_url(str(user.get("avatar_url") or user.get("avatar_url_template") or ""))
    url_token = str(user.get("url_token") or "").strip()
    author_url = f"https://www.zhihu.com/people/{url_token}" if url_token else ""
    if not author_url:
        profile = str(user.get("url") or "").strip()
        if profile.startswith("http"):
            author_url = profile
        elif profile.startswith("/people/"):
            author_url = f"https://www.zhihu.com{profile}"
    return author_meta_patch(
        author=name or None,
        author_avatar=avatar or None,
        author_url=author_url or None,
    )


def author_meta_from_content(content: dict[str, Any] | None) -> dict[str, str]:
    if not content:
        return {}
    return author_meta_from_user(content.get("author"))


def fetch_author_meta_for_url(
    url: str,
    *,
    cookie_path=None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """Fetch author fields for Zhihu answer, article, pin, profile, or question URL."""
    settings = settings or get_settings()
    answer_match = _ANSWER_ID_RE.search(url)
    article_match = _ARTICLE_ID_RE.search(url)
    pin_match = _PIN_ID_RE.search(url)
    people_match = _PEOPLE_TOKEN_RE.search(url)
    question_match = _QUESTION_ID_RE.search(url)
    if not any((answer_match, article_match, pin_match, people_match, question_match)):
        return {}

    path = cookie_path or settings.zhihu_cookies_path
    jar = _cookie_jar(path)
    if not jar:
        return {}

    own_client = client is None
    if own_client:
        client = httpx.Client(headers=DEFAULT_HEADERS, cookies=jar, timeout=settings.http_timeout_seconds)

    try:
        assert client is not None
        if answer_match:
            response = client.get(f"{ZHIHU_API}/answers/{answer_match.group(1)}")
            if response.status_code == 200:
                return author_meta_from_user(response.json().get("author"))
            return {}

        if pin_match:
            response = client.get(f"{ZHIHU_API}/pins/{pin_match.group(1)}")
            if response.status_code == 200:
                return author_meta_from_user(response.json().get("author"))
            return {}

        if people_match:
            response = client.get(f"{ZHIHU_API}/members/{people_match.group(1)}")
            if response.status_code == 200:
                return author_meta_from_user(response.json())
            return {}

        if question_match and not answer_match:
            response = client.get(
                f"{ZHIHU_API}/questions/{question_match.group(1)}/feeds",
                params={"limit": 1},
            )
            if response.status_code != 200:
                return {}
            batch = response.json().get("data") or []
            if not batch:
                return {}
            target = batch[0].get("target") or batch[0]
            return author_meta_from_user(target.get("author"))

        article_id = article_match.group(1) if article_match else ""
        host = urlparse(url).netloc.lower()
        api_base = "https://zhuanlan.zhihu.com/api" if "zhuanlan" in host else f"{ZHIHU_API}/articles"
        response = client.get(f"{api_base}/articles/{article_id}")
        if response.status_code != 200:
            return {}
        payload = response.json()
        author = payload.get("author")
        if not author and isinstance(payload.get("data"), dict):
            author = payload["data"].get("author")
        return author_meta_from_user(author)
    except Exception:
        return {}
    finally:
        if own_client and client is not None:
            client.close()
