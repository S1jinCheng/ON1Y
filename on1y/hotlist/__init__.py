"""Daily hot-list sync orchestrator."""

from __future__ import annotations

from typing import Any

from on1y.config import Settings, get_settings
from on1y.hotlist.constants import HOTLIST_ZHIHU, SUPPORTED_HOTLIST_SOURCES
from on1y.hotlist.zhihu import sync_zhihu_hotlist
from on1y.ports.storage import StoragePort


def sync_hotlists(
    storage: StoragePort,
    *,
    sources: list[str] | None = None,
    settings: Settings | None = None,
    auto_distill: bool = False,
) -> dict[str, Any]:
    settings = settings or get_settings()
    selected = sources or list(SUPPORTED_HOTLIST_SOURCES)
    unknown = [s for s in selected if s not in SUPPORTED_HOTLIST_SOURCES]
    if unknown:
        raise ValueError(f"unsupported hotlist source(s): {', '.join(unknown)}")

    report: dict[str, Any] = {"sources": selected, "results": {}}
    if HOTLIST_ZHIHU in selected and settings.zhihu_hotlist_enabled:
        report["results"][HOTLIST_ZHIHU] = sync_zhihu_hotlist(
            storage,
            settings=settings,
            auto_distill=auto_distill,
        )
    return report
