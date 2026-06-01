"""One-shot cold start: sync subscriptions → RSS backfill → platform catchup."""

from __future__ import annotations

import logging
from pathlib import Path

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.config import PROJECT_ROOT, Settings, get_settings
from on1y.ingestion.rss import poll_rss_feeds_backfill
from on1y.ingestion.zhihu_feeds import follows_from_file, merge_zhihu_feeds_yaml
from on1y.ingestion.zhihu_follow_list import (
    fetch_zhihu_favlists,
    fetch_zhihu_followees,
    merge_follows_file,
)
from on1y.pipeline.catchup import run_catchup
from on1y.pipeline.zhihu_catchup import run_zhihu_catchup

logger = logging.getLogger(__name__)

DEFAULT_ZHIHU_FOLLOWS = PROJECT_ROOT / "config" / "zhihu_follows.txt"


def run_bootstrap(
    storage: SqliteStorage,
    *,
    youtube: bool = True,
    zhihu: bool = True,
    sync_zhihu_follows: bool = False,
    sync_zhihu_favlists: bool = False,
    max_feed_items: int | None = None,
    youtube_ingest_batch: int = 15,
    youtube_subtitle_batch: int = 8,
    zhihu_max_rounds: int = 500,
    pause_seconds: float = 1.0,
    settings: Settings | None = None,
) -> dict[str, object]:
    """
    Cold-start pipeline:
      1. (optional) Sync Zhihu follow list → feeds.yaml
      2. RSS backfill for selected platforms
      3. YouTube catchup / Zhihu catchup
    Does not run LLM distill — run `on1y distill` after subtitles/content are ready.
    """
    settings = settings or get_settings()
    max_items = max_feed_items if max_feed_items is not None else settings.rss_backfill_max_items_per_feed
    report: dict[str, object] = {"youtube": None, "zhihu": None}

    if (sync_zhihu_follows or sync_zhihu_favlists) and zhihu:
        follows_path = PROJECT_ROOT / "config" / "zhihu_follows.txt"
        sync_report: dict[str, object] = {}
        if sync_zhihu_follows:
            followees = fetch_zhihu_followees(settings=settings)
            added, total = merge_follows_file(followees, follows_path)
            sync_report["followees"] = {
                "fetched": len(followees),
                "follows_added": added,
                "follows_total": total,
            }
        if sync_zhihu_favlists:
            favlists = fetch_zhihu_favlists(settings=settings)
            added, total = merge_follows_file(favlists, follows_path)
            sync_report["favlists"] = {
                "fetched": len(favlists),
                "follows_added": added,
                "follows_total": total,
            }
        follows = follows_from_file(follows_path)
        feed_count = merge_zhihu_feeds_yaml(
            follows,
            feeds_path=settings.rss_config_path,
            rsshub_base=settings.zhihu_rsshub_base,
            enabled=True,
            dry_run=False,
        )
        sync_report["feeds_merged"] = feed_count
        report["zhihu_follow_sync"] = sync_report

    if youtube:
        enqueued = poll_rss_feeds_backfill(
            storage,
            label_prefix="yt-",
            max_items_per_feed=max_items,
        )
        catchup = run_catchup(
            storage,
            ingest_batch=youtube_ingest_batch,
            subtitle_batch=youtube_subtitle_batch,
            max_rounds=500,
            pause_seconds=pause_seconds,
        )
        report["youtube"] = {"rss_backfill_enqueued": enqueued, "catchup": catchup}

    if zhihu:
        enqueued = poll_rss_feeds_backfill(
            storage,
            label_prefix="zhihu-",
            max_items_per_feed=max_items,
        )
        catchup = run_zhihu_catchup(
            storage,
            ingest_per_round=1,
            max_rounds=zhihu_max_rounds,
        )
        report["zhihu"] = {"rss_backfill_enqueued": enqueued, "catchup": catchup}

    report["raw_count"] = storage.count_raw_items()
    report["distilled_count"] = storage.count_distilled_items()
    return report
