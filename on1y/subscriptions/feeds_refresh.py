"""Optional refresh of feeds.yaml from platform follow/subscription lists."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from on1y.config import PROJECT_ROOT, Settings, get_settings
from on1y.ingestion.youtube_feeds import (
    DEFAULT_CHANNELS_FILE,
    channels_from_file,
    channels_from_ytdlp,
    merge_youtube_feeds_yaml,
    resolve_channel_ids,
)
from on1y.ingestion.zhihu_feeds import follows_from_file, merge_zhihu_feeds_yaml
from on1y.ingestion.zhihu_follow_list import fetch_zhihu_followees, merge_follows_file

logger = logging.getLogger(__name__)

DEFAULT_ZHIHU_FOLLOWS = PROJECT_ROOT / "config" / "zhihu_follows.txt"


def refresh_youtube_feeds(
    *,
    settings: Settings | None = None,
    max_channels: int = 50,
    dry_run: bool = False,
    use_ytdlp: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    report: dict[str, Any] = {"platform": "youtube", "dry_run": dry_run, "channels_merged": 0}

    rows: list[tuple[str, str | None]] = []
    if use_ytdlp:
        rows = channels_from_ytdlp(max_channels=max_channels, settings=settings)
        report["ytdlp_channels"] = len(rows)

    if not rows and DEFAULT_CHANNELS_FILE.is_file():
        rows = channels_from_file(DEFAULT_CHANNELS_FILE)
        report["file_channels"] = len(rows)

    if not rows:
        report["skipped"] = True
        report["skip_reason"] = "no_channels_found"
        return report

    channels = resolve_channel_ids(rows[:max_channels])
    if not channels:
        report["skipped"] = True
        report["skip_reason"] = "no_resolved_channel_ids"
        return report

    count = merge_youtube_feeds_yaml(
        channels,
        feeds_path=settings.rss_config_path,
        enabled=True,
        dry_run=dry_run,
    )
    report["channels_merged"] = count
    return report


def refresh_zhihu_follow_feeds(
    *,
    settings: Settings | None = None,
    follows_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    path = follows_path or DEFAULT_ZHIHU_FOLLOWS
    report: dict[str, Any] = {"platform": "zhihu", "dry_run": dry_run}

    followees = fetch_zhihu_followees(settings=settings)
    added, total = merge_follows_file(followees, path)
    report["followees_fetched"] = len(followees)
    report["follows_added"] = added
    report["follows_total"] = total

    follows = follows_from_file(path)
    count = merge_zhihu_feeds_yaml(
        follows,
        feeds_path=settings.rss_config_path,
        rsshub_base=settings.zhihu_rsshub_base,
        enabled=True,
        dry_run=dry_run,
    )
    report["feeds_merged"] = count
    return report
