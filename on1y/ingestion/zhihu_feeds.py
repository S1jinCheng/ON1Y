"""Zhihu RSSHub feed helpers (used by scripts/sync_zhihu_feeds.py)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ZHIHU_FEED_LABEL_PREFIX = "zhihu-"

_ROUTE_TEMPLATES = {
    "activities": "/zhihu/people/activities/{id}",
    "answers": "/zhihu/people/answers/{id}",
    "collection": "/zhihu/collection/{id}",
    "column": "/zhuanlan/zhihu/column/{id}",
}

_PEOPLE_URL_RE = re.compile(
    r"zhihu\.com/people/([^/?#]+)(?:/(activities|answers))?",
    re.IGNORECASE,
)
_COLLECTION_URL_RE = re.compile(r"zhihu\.com/collection/(\d+)", re.IGNORECASE)
_COLUMN_URL_RE = re.compile(r"zhuanlan\.zhihu\.com/([^/?#]+)", re.IGNORECASE)


def slug_label(feed_type: str, item_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{feed_type}-{item_id}".lower()).strip("-")[:48]
    return f"{ZHIHU_FEED_LABEL_PREFIX}{slug or feed_type}"


def parse_follow_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if ":" in line and not line.startswith("http"):
        feed_type, item_id = line.split(":", 1)
        feed_type = feed_type.strip().lower()
        item_id = item_id.strip().strip("/")
        if feed_type in _ROUTE_TEMPLATES and item_id:
            return feed_type, item_id
        return None

    if line.startswith("http"):
        people = _PEOPLE_URL_RE.search(line)
        if people:
            feed_type = (people.group(2) or "activities").lower()
            if feed_type not in _ROUTE_TEMPLATES:
                feed_type = "activities"
            return feed_type, people.group(1)
        coll = _COLLECTION_URL_RE.search(line)
        if coll:
            return "collection", coll.group(1)
        col = _COLUMN_URL_RE.search(line)
        if col:
            return "column", col.group(1)
        return None

    if re.fullmatch(r"[\w.-]+", line):
        return "activities", line
    return None


def follows_from_file(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_follow_line(line)
        if parsed and parsed not in seen:
            seen.add(parsed)
            rows.append(parsed)
    return rows


def build_feed_url(base: str, feed_type: str, item_id: str) -> str:
    base = base.rstrip("/")
    route = _ROUTE_TEMPLATES[feed_type].format(id=item_id)
    return f"{base}{route}"


def merge_zhihu_feeds_yaml(
    follows: list[tuple[str, str]],
    *,
    feeds_path: Path,
    rsshub_base: str,
    enabled: bool,
    dry_run: bool,
) -> int:
    if feeds_path.is_file():
        data = yaml.safe_load(feeds_path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    feeds = list(data.get("feeds") or [])
    feeds = [f for f in feeds if not str(f.get("label", "")).startswith(ZHIHU_FEED_LABEL_PREFIX)]

    for feed_type, item_id in follows:
        feeds.append(
            {
                "url": build_feed_url(rsshub_base, feed_type, item_id),
                "label": slug_label(feed_type, item_id),
                "enabled": enabled,
            }
        )

    data["feeds"] = feeds
    out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    if dry_run:
        print(out)
        return len(follows)
    feeds_path.parent.mkdir(parents=True, exist_ok=True)
    feeds_path.write_text(out, encoding="utf-8")
    return len(follows)
