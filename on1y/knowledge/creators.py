"""Subscribed creators (RSS / Bilibili) for sidebar navigation."""

from __future__ import annotations

import re
from typing import Any

from on1y.ingestion.rss import FeedConfig, load_feeds

_SUBSCRIPTION_PREFIXES = ("zhihu-", "yt-", "bili-")
_ZHIHU_PERSON_FEED_RE = re.compile(r"^zhihu-(?:activities|answers)-(.+)$")
_ZHIHU_COLLECTION_FEED_RE = re.compile(r"^zhihu-collection-(\d+)$")
_ZHIHU_PEOPLE_URL_RE = re.compile(r"/people/(?:activities|answers)/([^/?#]+)")
_ZHIHU_COLLECTION_URL_RE = re.compile(r"/collection/(\d+)")
_BILI_UP_FEED_URL_RE = re.compile(r"/bilibili/user/video/(\d+)")


def is_subscription_feed(label: str) -> bool:
    if label.startswith("hotlist-"):
        return False
    return any(label.startswith(prefix) for prefix in _SUBSCRIPTION_PREFIXES)


def zhihu_author_url(token: str) -> str:
    token = token.strip().strip("/")
    return f"https://www.zhihu.com/people/{token}"


def normalize_zhihu_author_url(url: str | None) -> str:
    value = str(url or "").strip().rstrip("/")
    if not value:
        return ""
    if value.startswith("http://"):
        value = "https://" + value[len("http://") :]
    return value


def zhihu_author_url_variants(token: str) -> list[str]:
    base = zhihu_author_url(token)
    return list(dict.fromkeys([base, f"{base}/"]))


def zhihu_person_token_from_url(author_url: str | None) -> str | None:
    match = re.search(r"/people/([^/?#]+)", str(author_url or ""))
    if not match:
        return None
    token = match.group(1).strip()
    return token or None


def zhihu_person_key_from_author_url(author_url: str | None) -> str | None:
    token = zhihu_person_token_from_url(author_url)
    if not token:
        return None
    return f"zhihu-person:{token}"


def is_zhihu_collection_feed(feed: FeedConfig) -> bool:
    if feed.label.startswith("zhihu-collection-"):
        return True
    return bool(_ZHIHU_COLLECTION_URL_RE.search(feed.url))


def is_bilibili_rss_feed(feed: FeedConfig) -> bool:
    """Legacy RSSHub B站 feeds — real UP rows come from dynamic sync + author_url."""
    return feed.label.startswith("bili-")


def is_sidebar_creator_feed(feed: FeedConfig) -> bool:
    """Feeds that map to a sidebar creator row (collections are split by author)."""
    if not feed.enabled or not is_subscription_feed(feed.label):
        return False
    if is_zhihu_collection_feed(feed):
        return False
    if is_bilibili_rss_feed(feed):
        return False
    return True


def creator_key_from_feed_label(label: str) -> str:
    match = _ZHIHU_PERSON_FEED_RE.match(label)
    if match:
        return f"zhihu-person:{match.group(1)}"
    match = _ZHIHU_COLLECTION_FEED_RE.match(label)
    if match:
        return f"zhihu-collection:{match.group(1)}"
    return f"feed:{label}"


def creator_key_from_feed(feed: FeedConfig) -> str:
    match = _ZHIHU_PEOPLE_URL_RE.search(feed.url)
    if match:
        return f"zhihu-person:{match.group(1)}"
    match = _ZHIHU_COLLECTION_URL_RE.search(feed.url)
    if match:
        return f"zhihu-collection:{match.group(1)}"
    return creator_key_from_feed_label(feed.label)


def _zhihu_feed_labels_for_token(token: str, feed_labels: list[str] | None = None) -> list[str]:
    labels: list[str] = []
    slug = token.replace(".", "-")
    for base in (token, slug):
        labels.append(f"zhihu-activities-{base}")
        labels.append(f"zhihu-answers-{base}")
    if feed_labels:
        labels.extend(feed_labels)
    return list(dict.fromkeys(label for label in labels if label))


def creator_filter_sql(creator_key: str) -> tuple[str, list[Any]]:
    """Return SQL fragment (no leading AND) + params for raw_items alias r."""
    if creator_key.startswith("zhihu-person:"):
        token = creator_key.split(":", 1)[1]
        urls = zhihu_author_url_variants(token)
        url_placeholders = ", ".join("?" for _ in urls)
        feed_labels = _zhihu_feed_labels_for_token(token)
        feed_clauses = " OR ".join(
            "json_extract(r.source_meta, '$.feed_label') = ?" for _ in feed_labels
        )
        return (
            "("
            f"json_extract(r.source_meta, '$.author_url') IN ({url_placeholders}) "
            f"OR {feed_clauses}"
            ")",
            [*urls, *feed_labels],
        )
    if creator_key.startswith("zhihu-collection:"):
        collection_id = creator_key.split(":", 1)[1]
        return (
            "json_extract(r.source_meta, '$.feed_label') = ?",
            [f"zhihu-collection-{collection_id}"],
        )
    if creator_key.startswith("bili:"):
        return ("json_extract(r.source_meta, '$.author_url') = ?", [creator_key[5:]])
    if creator_key.startswith("feed:"):
        return ("json_extract(r.source_meta, '$.feed_label') = ?", [creator_key[5:]])
    return ("json_extract(r.source_meta, '$.feed_label') = ?", [creator_key])


def _platform_for_feed(label: str) -> str:
    if label.startswith("zhihu-"):
        return "zhihu"
    if label.startswith("yt-"):
        return "youtube"
    if label.startswith("bili-"):
        return "bilibili"
    return "generic"


def _label_display_hint(label: str) -> str:
    for prefix in ("zhihu-activities-", "zhihu-answers-", "zhihu-collection-", "yt-", "bili-"):
        if label.startswith(prefix):
            slug = label[len(prefix) :].replace("-", " ")
            return slug.title()
    return label


def bilibili_following_groups() -> dict[str, dict[str, Any]]:
    """All followed Bilibili UPs from feeds.yaml (bili-up-*), including those with no items yet."""
    from on1y.ingestion.bilibili_feeds import BILI_UP_FEED_LABEL_PREFIX

    groups: dict[str, dict[str, Any]] = {}
    for feed in load_feeds():
        if not feed.enabled or not feed.label.startswith(BILI_UP_FEED_LABEL_PREFIX):
            continue
        match = _BILI_UP_FEED_URL_RE.search(feed.url)
        if not match:
            continue
        up_mid = match.group(1)
        author_url = f"https://space.bilibili.com/{up_mid}"
        key = f"bili:{author_url}"
        name = str(feed.display_name or "").strip() or _label_display_hint(feed.label)
        groups[key] = {
            "key": key,
            "platform": "bilibili",
            "feed_labels": [feed.label],
            "name_hint": name,
            "author_url": author_url,
            "up_mid": up_mid,
            "subscribed": True,
        }
    return groups


def subscription_feed_groups() -> dict[str, dict[str, Any]]:
    """Merge subscription feeds into creator sidebar groups."""
    groups: dict[str, dict[str, Any]] = {}
    for feed in load_feeds():
        if not is_sidebar_creator_feed(feed):
            continue
        key = creator_key_from_feed(feed)
        if key.startswith("zhihu-collection:"):
            continue
        row = groups.setdefault(
            key,
            {
                "key": key,
                "platform": _platform_for_feed(feed.label),
                "feed_labels": [],
                "name_hint": _label_display_hint(feed.label),
            },
        )
        if feed.label not in row["feed_labels"]:
            row["feed_labels"].append(feed.label)
        if key.startswith("zhihu-person:"):
            token = key.split(":", 1)[1]
            row["people_url"] = zhihu_author_url(token)
    return groups


def discover_zhihu_person_groups(
    zhihu_by_url: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Authors found in DB (e.g. collection articles) keyed by zhihu-person:*."""
    groups: dict[str, dict[str, Any]] = {}
    for author_url, zh in zhihu_by_url.items():
        key = zhihu_person_key_from_author_url(author_url)
        if not key:
            continue
        groups[key] = {
            "key": key,
            "platform": "zhihu",
            "feed_labels": [],
            "name_hint": str(zh.get("author") or "").strip()
            or zhihu_person_token_from_url(author_url)
            or key,
            "people_url": normalize_zhihu_author_url(author_url),
        }
    return groups


def list_subscription_feeds() -> list[FeedConfig]:
    return [f for f in load_feeds() if f.enabled and is_subscription_feed(f.label)]
