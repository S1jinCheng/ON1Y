"""Unified enqueue API for all triggers."""

from __future__ import annotations

import logging

from on1y.models.enums import SourceType
from on1y.models.queue import QueueEnqueue
from on1y.ports.storage import StoragePort
from on1y.utils.platform import normalize_url

logger = logging.getLogger(__name__)


def enqueue_url(
    storage: StoragePort,
    url: str,
    *,
    source: SourceType = SourceType.MANUAL,
    source_meta: dict | None = None,
) -> int:
    """Add URL to pending queue. Returns pending_urls.id."""
    item = QueueEnqueue(url=normalize_url(url), source=source, source_meta=source_meta or {})
    pending_id = storage.enqueue(item)
    logger.info("Enqueued url=%s source=%s id=%s", item.url_str(), source.value, pending_id)
    from on1y.sync.progress import get_cold_start_progress

    progress = get_cold_start_progress()
    if progress is not None:
        meta = source_meta or {}
        title = str(meta.get("entry_title") or meta.get("title") or item.url_str()).strip()
        platform = str(meta.get("platform") or "").strip() or None
        if not platform:
            from on1y.utils.platform import detect_platform

            platform = detect_platform(item.url_str())
        progress.log_item(
            phase=progress.phase or "collections",
            title=title,
            platform=platform,
            status="enqueued",
            url=item.url_str(),
            detail=str(meta.get("feed_label") or meta.get("folder_name") or "").strip() or None,
        )
    return pending_id
