"""Storage port — implement with SQLite today, PostgreSQL tomorrow."""

from __future__ import annotations

from typing import Protocol

from on1y.models.queue import PendingUrl, QueueEnqueue
from on1y.models.raw import RawItem, RawItemCreate


class StoragePort(Protocol):
    def initialize(self) -> None:
        """Apply schema migrations and ensure database is ready."""
        ...

    def enqueue(self, item: QueueEnqueue) -> int:
        """Insert or ignore duplicate (url, source). Returns row id."""
        ...

    def claim_next_pending(self) -> PendingUrl | None:
        """Atomically mark one pending row as processing and return it."""
        ...

    def claim_next_pending_for_platform(self, platform: str) -> PendingUrl | None:
        """Claim the oldest pending URL whose URL matches the given platform."""
        ...

    def count_pending_for_platform(self, platform: str, *, status: str = "pending") -> int:
        """Count queue rows for a platform (by URL pattern)."""
        ...

    def mark_pending_done(self, pending_id: int) -> None:
        ...

    def mark_pending_failed(self, pending_id: int, error: str, *, retry: bool) -> None:
        ...

    def upsert_raw_item(self, item: RawItemCreate) -> RawItem:
        ...

    def get_raw_by_url(self, url: str) -> RawItem | None:
        ...

    def get_raw_by_id(self, raw_id: int) -> RawItem | None:
        ...

    def list_raw_items(
        self,
        *,
        platform: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RawItem]:
        ...

    def list_pending_urls(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PendingUrl]:
        ...

    def count_pending_by_status(self) -> dict[str, int]:
        ...

    def count_raw_items(self) -> int:
        ...

    def count_distilled_items(self) -> int:
        ...

    def url_in_rss_queue(self, url: str) -> bool:
        """True if URL is pending/processing/done in the RSS queue."""
        ...

    def get_rss_feed_state(self, feed_url: str) -> tuple[str | None, str | None]:
        """Return (last_entry_id, last_published)."""
        ...

    def set_rss_feed_state(
        self,
        feed_url: str,
        *,
        last_entry_id: str | None,
        last_published: str | None,
    ) -> None:
        ...
