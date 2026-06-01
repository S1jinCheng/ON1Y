"""Bilibili UP subscription feed helpers."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

BILI_UP_FEED_LABEL_PREFIX = "bili-up-"


def up_cursor_key(up_mid: str) -> str:
    """Synthetic feed key stored in rss_feed_state for API polling."""
    return f"bilibili-up://{up_mid}"


def dynamic_video_cursor_key() -> str:
    """Global cursor for Bilibili following dynamics (video tab)."""
    return "bilibili-dynamic://video"


def slug_label(up_mid: str, uname: str | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (uname or up_mid).strip().lower()).strip("-")[:40]
    slug = slug or up_mid
    return f"{BILI_UP_FEED_LABEL_PREFIX}{slug}"


def build_feed_url(rsshub_base: str, up_mid: str) -> str:
    base = rsshub_base.rstrip("/")
    return f"{base}/bilibili/user/video/{up_mid}"


def merge_bilibili_up_feeds_yaml(
    followings: list[dict[str, str]],
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
    feeds = [f for f in feeds if not str(f.get("label", "")).startswith(BILI_UP_FEED_LABEL_PREFIX)]

    for row in followings:
        mid = str(row.get("mid") or "").strip()
        if not mid:
            continue
        uname = str(row.get("uname") or mid)
        feeds.append(
            {
                "url": build_feed_url(rsshub_base, mid),
                "label": slug_label(mid, uname),
                "enabled": enabled,
            }
        )

    data["feeds"] = feeds
    out = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    if dry_run:
        print(out)
        return len(followings)
    feeds_path.parent.mkdir(parents=True, exist_ok=True)
    feeds_path.write_text(out, encoding="utf-8")
    return len(followings)
