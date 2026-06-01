"""Subscription sync orchestrators."""

from __future__ import annotations

from typing import Any

from on1y.config import Settings, get_settings
from on1y.ingestion.bilibili_subscriptions import sync_bilibili_subscriptions
from on1y.hotlist import sync_hotlists
from on1y.ports.storage import StoragePort


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
    sync_hotlist: bool = True,
) -> dict[str, Any]:
    settings = settings or get_settings()
    allowed = {"bilibili", "zhihu", "all"}
    if platform not in allowed:
        raise ValueError(f"unsupported platform for subscriptions sync: {platform}")

    report: dict[str, Any] = {"platform": platform}
    if platform in {"bilibili", "all"}:
        report["bilibili"] = sync_bilibili_subscriptions(
            storage,
            settings=settings,
            sync_config=sync_config,
            poll=poll,
            backfill=backfill,
            dry_run=dry_run,
            sync_since_ts=sync_since_ts,
        )
    if sync_hotlist and not dry_run and platform in {"zhihu", "all"}:
        report["hotlist"] = sync_hotlists(storage, settings=settings)
    return report
