"""Optional refresh of feeds.yaml from platform follow/subscription lists."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from on1y.config import PROJECT_ROOT, Settings, get_settings
from on1y.user.feeds_config import resolve_feeds_config_path
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


def refresh_subscription_feeds_from_cookie(
    platform: str,
    *,
    settings: Settings | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Rebuild subscription feed entries from the saved cookie.

    Cookie verification reads the live account; sync must refresh feeds.yaml first or it
    keeps polling a stale channel/follow list (the real cache behind wrong content).
    """
    from on1y.auth.context import get_effective_user_id
    from on1y.user.feeds_config import ensure_user_feeds_config

    settings = settings or get_settings()
    uid = user_id if user_id is not None else get_effective_user_id()
    ensure_user_feeds_config(settings=settings, user_id=uid)

    if platform == "bilibili":
        from on1y.ingestion.bilibili_subscriptions import sync_bilibili_up_config

        return sync_bilibili_up_config(settings=settings)
    if platform == "youtube":
        return refresh_youtube_feeds(
            settings=settings,
            max_channels=settings.youtube_refresh_max_channels,
            use_file_fallback=False,
            user_id=uid,
        )
    if platform == "zhihu":
        if settings.zhihu_follow_sync_mode == "api":
            return {"platform": "zhihu", "skipped": True, "skip_reason": "api_mode"}
        return refresh_zhihu_follow_feeds(settings=settings)
    raise ValueError(f"unsupported platform: {platform}")


def youtube_feeds_stale(
    *,
    settings: Settings | None = None,
    user_id: int | None = None,
) -> bool:
    """True when cookie was updated after feeds.yaml (subscription list likely outdated)."""
    from on1y.auth.context import get_effective_user_id
    from on1y.cookies.loader import resolve_cookie_path

    settings = settings or get_settings()
    uid = user_id if user_id is not None else get_effective_user_id()
    cookie_path = resolve_cookie_path("youtube", settings, user_id=uid)
    feeds_path = resolve_feeds_config_path(settings, user_id=uid)
    if not cookie_path.is_file():
        return False
    if not feeds_path.is_file():
        return True
    return cookie_path.stat().st_mtime > feeds_path.stat().st_mtime


def refresh_youtube_feeds(
    *,
    settings: Settings | None = None,
    max_channels: int = 50,
    dry_run: bool = False,
    use_ytdlp: bool = True,
    use_file_fallback: bool = True,
    user_id: int | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    report: dict[str, Any] = {"platform": "youtube", "dry_run": dry_run, "channels_merged": 0}

    rows: list[tuple[str, str | None]] = []
    if use_ytdlp:
        rows = channels_from_ytdlp(
            max_channels=max_channels,
            settings=settings,
            user_id=user_id,
        )
        report["ytdlp_channels"] = len(rows)

    if not rows and use_file_fallback and DEFAULT_CHANNELS_FILE.is_file():
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
        feeds_path=resolve_feeds_config_path(settings, user_id=user_id),
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
        feeds_path=resolve_feeds_config_path(settings),
        rsshub_base=settings.zhihu_rsshub_base,
        enabled=True,
        dry_run=dry_run,
    )
    report["feeds_merged"] = count
    return report
