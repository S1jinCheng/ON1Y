"""Dev-oriented sync timing: per-phase durations and persisted history."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from on1y.config import get_settings

logger = logging.getLogger(__name__)

_HISTORY_FILE = "sync_timing_history.jsonl"
_MAX_HISTORY_LINES = 50


def format_duration_ms(ms: float | int | None) -> str:
    if ms is None:
        return "—"
    total_s = max(0, int(round(float(ms) / 1000)))
    if total_s < 60:
        return f"{total_s}s"
    minutes, seconds = divmod(total_s, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


class SyncTimer:
    """Accumulate named phase durations in milliseconds."""

    def __init__(self) -> None:
        self.spans_ms: dict[str, float] = {}

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.spans_ms[name] = round((time.perf_counter() - t0) * 1000, 1)

    def total_ms(self) -> float:
        return round(sum(self.spans_ms.values()), 1)

    def summary(self) -> dict[str, Any]:
        return {
            "spans_ms": dict(self.spans_ms),
            "total_ms": self.total_ms(),
        }


def _history_path() -> Path:
    return get_settings().data_dir / _HISTORY_FILE


def _trim_history(path: Path, *, max_lines: int = _MAX_HISTORY_LINES) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_lines:
        return
    path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def append_timing_record(record: dict[str, Any]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    _trim_history(path)
    logger.info(
        "Full sync timing saved: total=%s phases=%s",
        format_duration_ms(record.get("total_ms")),
        ", ".join(
            f"{name}={format_duration_ms(ms)}"
            for name, ms in (record.get("phases_ms") or {}).items()
        ),
    )


def list_timing_history(*, limit: int = 20) -> list[dict[str, Any]]:
    path = _history_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(records) >= limit:
            break
    return records


def rollup_phase_totals(spans_ms: dict[str, float]) -> dict[str, float]:
    """Sum leaf span durations into collections / subscriptions / pipeline."""
    totals = {"collections": 0.0, "subscriptions": 0.0, "pipeline": 0.0}
    for name, ms in spans_ms.items():
        root = name.split(".", 1)[0]
        if root in totals:
            totals[root] = round(totals[root] + float(ms), 1)
    return totals


def build_timing_record(
    *,
    user_id: int,
    started_at: str,
    finished_at: str,
    phases_ms: dict[str, float],
    detail: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    total_ms = round(sum(phases_ms.values()), 1)
    return {
        "user_id": user_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "total_ms": total_ms,
        "total_human": format_duration_ms(total_ms),
        "phases_ms": phases_ms,
        "phases_human": {k: format_duration_ms(v) for k, v in phases_ms.items()},
        "detail": detail or {},
        "error": error,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
