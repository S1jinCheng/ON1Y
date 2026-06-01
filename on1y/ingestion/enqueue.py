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
    return pending_id
