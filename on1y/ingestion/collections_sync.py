"""Poll platform 收藏夹 / playlists and enqueue new items for ingest."""

from __future__ import annotations

import logging
from typing import Any

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError
from on1y.ingestion.bilibili_collections import backfill_bilibili_collections
from on1y.ingestion.zhihu_collections import backfill_zhihu_collections
from on1y.ingestion.youtube_collections import sync_youtube_collections
from on1y.ports.storage import StoragePort

logger = logging.getLogger(__name__)

COLLECTIONS_PLATFORMS = ("bilibili", "zhihu", "youtube")


def parse_collections_platforms(value: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in value.replace(";", ",").split(","):
        name = part.strip().lower()
        if name in COLLECTIONS_PLATFORMS and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _scan_settings(settings: Settings) -> dict[str, Any]:
    return {
        "max_scan": settings.collections_max_items_per_source,
        "early_stop": settings.collections_early_stop_existing_streak,
    }


def _maybe_alert_cookie(platform: str, exc: ConfigurationError) -> None:
    from on1y.alerts import maybe_alert_cookie_expired

    maybe_alert_cookie_expired(str(exc), platform=platform, worker="collections")


def _pending_count(storage: StoragePort, platform: str) -> int:
    counter = getattr(storage, "count_pending_for_platform", None)
    if counter is None:
        return 0
    return int(counter(platform))


def _should_ingest_platform(
    report: dict[str, Any],
    platform: str,
    *,
    storage: StoragePort,
) -> bool:
    platform_report = report.get(platform)
    if not isinstance(platform_report, dict) or platform_report.get("cookie_error"):
        return False
    if int(platform_report.get("enqueued") or 0) > 0:
        return True
    return _pending_count(storage, platform) > 0


def sync_collections(
    storage: StoragePort,
    *,
    platforms: list[str] | None = None,
    dry_run: bool = False,
    ingest: bool = False,
    ingest_limit: int = 3,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Scan favorites/playlists for new URLs and optionally process a small ingest batch.
    Designed for frequent polling while `on1y serve` is running.
    """
    settings = settings or get_settings()
    targets = platforms or parse_collections_platforms(settings.collections_sync_platforms)
    scan = _scan_settings(settings)

    report: dict[str, Any] = {
        "platforms": targets,
        "enqueued_total": 0,
        "ingest": {},
    }

    for name in COLLECTIONS_PLATFORMS:
        if name not in targets:
            continue
        try:
            if name == "bilibili":
                platform_report = backfill_bilibili_collections(
                    storage,
                    dry_run=dry_run,
                    max_scan_per_folder=scan["max_scan"],
                    early_stop_existing_streak=scan["early_stop"],
                    settings=settings,
                )
            elif name == "zhihu":
                platform_report = backfill_zhihu_collections(
                    storage,
                    dry_run=dry_run,
                    max_scan_per_collection=scan["max_scan"],
                    early_stop_existing_streak=scan["early_stop"],
                    settings=settings,
                )
            else:
                platform_report = sync_youtube_collections(
                    storage,
                    include_watch_later=settings.youtube_collections_watch_later,
                    include_liked=settings.youtube_collections_liked,
                    max_items_per_playlist=scan["max_scan"],
                    early_stop_existing_streak=scan["early_stop"],
                    dry_run=dry_run,
                    settings=settings,
                )
            report[name] = platform_report
            report["enqueued_total"] += int(platform_report.get("enqueued") or 0)
        except ConfigurationError as exc:
            logger.warning("Collections sync %s failed: %s", name, exc)
            _maybe_alert_cookie(name, exc)
            report[name] = {"error": str(exc), "cookie_error": True}

    if dry_run or not ingest:
        return report

    limit = max(0, min(ingest_limit, 20))
    if limit <= 0:
        return report

    if "bilibili" in targets and _should_ingest_platform(report, "bilibili", storage=storage):
        from on1y.pipeline.video_enrich import run_video_enrich_pipeline

        report["ingest"]["bilibili"] = run_video_enrich_pipeline(
            storage,
            platform="bilibili",
            ingest_limit=limit,
            subtitle_limit=min(limit, settings.auto_sync_subtitle_limit),
            distill_limit=0,
            use_ai_summary=False,
        )

    if "youtube" in targets and _should_ingest_platform(report, "youtube", storage=storage):
        from on1y.pipeline.video_enrich import run_video_enrich_pipeline

        report["ingest"]["youtube"] = run_video_enrich_pipeline(
            storage,
            platform="youtube",
            ingest_limit=limit,
            subtitle_limit=min(limit, settings.auto_sync_subtitle_limit),
            distill_limit=0,
            use_ai_summary=False,
        )

    if "zhihu" in targets and _should_ingest_platform(report, "zhihu", storage=storage):
        from on1y.pipeline.zhihu_catchup import run_zhihu_catchup

        report["ingest"]["zhihu"] = run_zhihu_catchup(
            storage,
            ingest_per_round=limit,
            max_rounds=1,
        )

    return report
