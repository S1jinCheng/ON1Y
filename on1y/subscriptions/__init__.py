"""Subscription sync orchestrators."""

from __future__ import annotations

from typing import Any

from on1y.auth.context import get_current_user_id
from on1y.config import Settings, get_settings
from on1y.sync_settings.settings import resolve_settings
from on1y.ingestion.bilibili_subscriptions import sync_bilibili_subscriptions
from on1y.ports.storage import StoragePort
from on1y.subscriptions.feeds_refresh import (
    refresh_youtube_feeds,
    refresh_zhihu_follow_feeds,
    youtube_feeds_stale,
)
from on1y.subscriptions.rss_sync import RSS_PLATFORM_PREFIXES, sync_rss_subscriptions

SYNC_PLATFORMS = frozenset({"bilibili", "youtube", "zhihu", "twitter", "all"})


def sync_subscriptions(
    storage: StoragePort,
    *,
    platform: str = "bilibili",
    sync_config: bool = True,
    poll: bool = True,
    backfill: bool = False,
    dry_run: bool = False,
    settings: Settings | None = None,
    sync_since_ts: int | None = None,
    backfill_max_days: int | None = None,
    sync_hotlist: bool = False,
    refresh_feeds: bool | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Unified subscription sync.

    - bilibili: API dynamic feed (+ optional feeds.yaml merge)
    - youtube / zhihu: RSS poll by label prefix (yt- / zhihu-)
    - all: bilibili + youtube + zhihu + twitter (no hotlist; use hotlist sync separately)
    - zhihu platform does NOT include hotlist (use on1y hotlist sync / Web 热榜按钮).
    """
    settings = settings or resolve_settings()
    if platform not in SYNC_PLATFORMS:
        raise ValueError(f"unsupported platform for subscriptions sync: {platform}")

    do_refresh = refresh_feeds
    if do_refresh is None:
        do_refresh = False

    report: dict[str, Any] = {"platform": platform}
    uid = user_id if user_id is not None else get_current_user_id()

    if platform in {"bilibili", "all"}:
        report["bilibili"] = sync_bilibili_subscriptions(
            storage,
            settings=settings,
            sync_config=sync_config,
            poll=poll,
            backfill=backfill,
            dry_run=dry_run,
            sync_since_ts=sync_since_ts,
            backfill_max_days=backfill_max_days,
            user_id=uid,
        )

    for rss_platform in ("youtube", "zhihu"):
        if platform not in {rss_platform, "all"}:
            continue
        if dry_run:
            report[rss_platform] = {"skipped": True, "skip_reason": "dry_run"}
            continue
        if not poll:
            continue

        rss_report: dict[str, Any] = {}
        auto_refresh = (
            settings.youtube_auto_refresh_channels
            if rss_platform == "youtube"
            else settings.zhihu_auto_refresh_follows
        )
        if rss_platform == "zhihu" and settings.zhihu_follow_sync_mode == "api":
            from on1y.ingestion.zhihu_subscriptions import poll_zhihu_api_subscriptions

            rss_report["poll"] = poll_zhihu_api_subscriptions(
                storage,
                settings=settings,
                backfill=backfill,
                backfill_max_days=backfill_max_days,
                user_id=uid,
            )
        else:
            stale_youtube = rss_platform == "youtube" and youtube_feeds_stale(
                settings=settings,
                user_id=uid,
            )
            if do_refresh or auto_refresh or stale_youtube:
                try:
                    if rss_platform == "youtube":
                        rss_report["config"] = refresh_youtube_feeds(
                            settings=settings,
                            max_channels=settings.youtube_refresh_max_channels,
                            user_id=uid,
                        )
                        if stale_youtube and not do_refresh and not auto_refresh:
                            rss_report["config"]["refreshed_reason"] = "cookie_newer_than_feeds"
                    else:
                        rss_report["config"] = refresh_zhihu_follow_feeds(
                            settings=settings,
                            user_id=uid,
                        )
                except Exception as exc:
                    rss_report["config"] = {"error": str(exc)}

            rss_report["poll"] = sync_rss_subscriptions(
                storage,
                platform=rss_platform,
                backfill=backfill,
                settings=settings,
                backfill_max_days=backfill_max_days,
            )
        report[rss_platform] = rss_report

    if platform in {"twitter", "all"}:
        if dry_run:
            report["twitter"] = {"skipped": True, "skip_reason": "dry_run"}
        elif poll:
            from on1y.ingestion.twitter_subscriptions import sync_twitter_subscriptions

            report["twitter"] = sync_twitter_subscriptions(
                storage,
                settings=settings,
                poll=True,
                backfill=backfill,
                sync_since_ts=sync_since_ts,
                backfill_max_days=backfill_max_days,
            )

    if sync_hotlist and not dry_run and platform in {"zhihu", "all"}:
        from on1y.hotlist import sync_hotlists

        report["hotlist"] = sync_hotlists(storage, settings=settings)

    return report
