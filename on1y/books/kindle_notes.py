"""Parse / merge Kindle delivery status in shelf item notes."""

from __future__ import annotations

import re

_KINDLE_STATUS_LINE = re.compile(r"^kindle_status:\s*", re.I)
_KINDLE_DETAIL_LINE = re.compile(r"^kindle_detail:\s*", re.I)


def parse_kindle_status(notes: str | None) -> str | None:
    for line in (notes or "").splitlines():
        if _KINDLE_STATUS_LINE.match(line.strip()):
            value = line.split(":", 1)[1].strip().lower()
            return value or None
    return None


def parse_kindle_detail(notes: str | None) -> str | None:
    for line in (notes or "").splitlines():
        if _KINDLE_DETAIL_LINE.match(line.strip()):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def merge_kindle_status(
    notes: str | None,
    status: str,
    detail: str | None = None,
) -> str:
    kept: list[str] = []
    for line in (notes or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _KINDLE_STATUS_LINE.match(stripped) or _KINDLE_DETAIL_LINE.match(stripped):
            continue
        kept.append(line.rstrip())
    kept.append(f"kindle_status: {status.strip()}")
    if detail and detail.strip():
        kept.append(f"kindle_detail: {detail.strip()[:500]}")
    return "\n".join(kept)
