"""Zero-LLM tag extraction from social text and item metadata."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_\u4e00-\u9fff]{1,64})")
_CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{0,15})\b")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_SKIP_LINK_HOSTS = frozenset(
    {
        "x.com",
        "twitter.com",
        "mobile.twitter.com",
        "t.co",
        "pic.twitter.com",
    }
)

_FEED_LABEL_TAGS: dict[str, str] = {
    "x-home": "X关注",
    "x-likes": "X点赞",
    "x-bookmarks": "X书签",
}

_PLATFORM_TAGS: dict[str, str] = {
    "twitter": "X",
    "zhihu": "知乎",
    "bilibili": "B站",
    "youtube": "YouTube",
}


def _normalize_tag(label: str) -> str:
    return label.strip().lstrip("#$").strip()


def _dedupe_tags(names: list[str], *, max_tags: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        label = _normalize_tag(name)
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
        if len(out) >= max_tags:
            break
    return out


def extract_hashtags(body: str, *, max_tags: int = 12) -> list[str]:
    if not body:
        return []
    return _dedupe_tags(_HASHTAG_RE.findall(body), max_tags=max_tags)


def extract_cashtags(body: str, *, max_tags: int = 4) -> list[str]:
    if not body:
        return []
    return _dedupe_tags([f"${name}" for name in _CASHTAG_RE.findall(body)], max_tags=max_tags)


def extract_link_domain_tags(
    body: str,
    url: str | None = None,
    *,
    max_tags: int = 4,
) -> list[str]:
    hosts: list[str] = []
    for match in _URL_RE.findall(body or ""):
        host = (urlparse(match).netloc or "").lower().removeprefix("www.")
        if host and host not in _SKIP_LINK_HOSTS:
            hosts.append(host)
    if url:
        host = (urlparse(url).netloc or "").lower().removeprefix("www.")
        if host and host not in _SKIP_LINK_HOSTS:
            hosts.append(host)
    return _dedupe_tags(hosts, max_tags=max_tags)


def extract_meta_tags(
    *,
    platform: str | None = None,
    source_meta: dict[str, Any] | None = None,
    author: str | None = None,
    max_tags: int = 8,
) -> list[str]:
    meta = source_meta or {}
    names: list[str] = []

    plat = (platform or str(meta.get("platform") or "")).strip().lower()
    plat_tag = _PLATFORM_TAGS.get(plat)
    if plat_tag:
        names.append(plat_tag)

    feed_label = str(meta.get("feed_label") or "").strip()
    feed_tag = _FEED_LABEL_TAGS.get(feed_label)
    if feed_tag:
        names.append(feed_tag)
    elif feed_label:
        names.append(feed_label)

    folder = str(meta.get("folder_name") or "").strip()
    if folder and folder not in names:
        names.append(folder)

    author_name = (author or str(meta.get("author") or "")).strip()
    if author_name:
        names.append(author_name)

    return _dedupe_tags(names, max_tags=max_tags)


def collect_short_content_tags(
    *,
    body: str,
    platform: str | None = None,
    url: str | None = None,
    source_meta: dict[str, Any] | None = None,
    author: str | None = None,
    max_tags: int = 16,
) -> list[str]:
    """Merge hashtag, cashtag, metadata, and outbound link tags without LLM."""
    meta = source_meta or {}
    author_name = author or str(meta.get("author") or "").strip() or None
    merged: list[str] = []
    merged.extend(extract_hashtags(body, max_tags=12))
    merged.extend(extract_cashtags(body, max_tags=4))
    merged.extend(
        extract_meta_tags(
            platform=platform,
            source_meta=meta,
            author=author_name,
            max_tags=8,
        )
    )
    merged.extend(extract_link_domain_tags(body, url, max_tags=4))
    return _dedupe_tags(merged, max_tags=max_tags)
