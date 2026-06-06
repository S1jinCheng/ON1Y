"""Live cold-start progress: per-item event log for the UI."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
from uuid import uuid4

_current: ContextVar[ColdStartProgress | None] = ContextVar("cold_start_progress", default=None)

_MAX_EVENTS = 800


def get_cold_start_progress() -> ColdStartProgress | None:
    return _current.get()


class ColdStartProgress:
    def __init__(
        self,
        *,
        user_id: int,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.user_id = user_id
        self._on_update = on_update
        self._lock = threading.Lock()
        self._seq = 0
        self.started_monotonic = time.perf_counter()
        self.phase: str | None = "starting"
        self.counters: dict[str, int] = {
            "enqueued": 0,
            "ingested": 0,
            "distilled": 0,
            "failed": 0,
            "skipped": 0,
        }
        self.events: list[dict[str, Any]] = []

    @contextmanager
    def activate(self) -> Iterator[None]:
        token = _current.set(self)
        try:
            yield
        finally:
            _current.reset(token)

    def set_phase(self, phase: str, *, detail: str | None = None) -> None:
        with self._lock:
            self.phase = phase
            self._append_event(
                kind="phase",
                status="active",
                title=detail or phase,
                phase=phase,
            )
        self._notify()

    def log_step(self, *, phase: str, title: str, detail: str | None = None) -> None:
        with self._lock:
            self.phase = phase
            self._append_event(
                kind="step",
                status="info",
                title=title,
                phase=phase,
                detail=detail,
            )
        self._notify()

    def log_item(
        self,
        *,
        phase: str,
        title: str,
        platform: str | None = None,
        status: str = "queued",
        detail: str | None = None,
        url: str | None = None,
    ) -> None:
        counter_key = {
            "enqueued": "enqueued",
            "ingested": "ingested",
            "distilled": "distilled",
            "failed": "failed",
            "skipped": "skipped",
        }.get(status)
        with self._lock:
            self.phase = phase
            if counter_key:
                self.counters[counter_key] = int(self.counters.get(counter_key, 0)) + 1
            self._append_event(
                kind="item",
                status=status,
                title=title or url or "—",
                phase=phase,
                platform=platform,
                detail=detail,
                url=url,
            )
        self._notify()

    def log_error(self, *, phase: str, title: str, detail: str | None = None) -> None:
        with self._lock:
            self.counters["failed"] = int(self.counters.get("failed", 0)) + 1
            self._append_event(
                kind="error",
                status="failed",
                title=title,
                phase=phase,
                detail=detail,
            )
        self._notify()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            elapsed_ms = round((time.perf_counter() - self.started_monotonic) * 1000, 1)
            return {
                "user_id": self.user_id,
                "phase": self.phase,
                "elapsed_ms": elapsed_ms,
                "counters": dict(self.counters),
                "events": list(self.events[-120:]),
                "event_total": len(self.events),
            }

    def _append_event(
        self,
        *,
        kind: str,
        status: str,
        title: str,
        phase: str,
        platform: str | None = None,
        detail: str | None = None,
        url: str | None = None,
    ) -> None:
        self._seq += 1
        event = {
            "id": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "status": status,
            "phase": phase,
            "title": title,
            "platform": platform,
            "detail": detail,
            "url": url,
        }
        self.events.append(event)
        if len(self.events) > _MAX_EVENTS:
            self.events = self.events[-_MAX_EVENTS:]

    def _notify(self) -> None:
        if self._on_update:
            self._on_update(self.snapshot())
