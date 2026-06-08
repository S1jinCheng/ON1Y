"""Tests for published_at parsing."""

from __future__ import annotations

from datetime import datetime, timezone

from on1y.utils.published_at import published_at_from_meta, published_at_iso


def test_published_at_from_rss_string() -> None:
    meta = {"published": "Mon, 27 May 2024 12:34:56 +0000"}
    dt = published_at_from_meta(meta)
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 5
    assert dt.day == 27


def test_published_at_from_unix_timestamp() -> None:
    meta = {"published": 1_700_000_000}
    iso = published_at_iso(meta)
    assert iso is not None
    assert datetime.fromisoformat(iso).astimezone(timezone.utc).timestamp() == 1_700_000_000


def test_published_at_from_entry_published() -> None:
    meta = {"entry_published": "Mon, 27 May 2024 12:34:56 +0000"}
    dt = published_at_from_meta(meta)
    assert dt is not None
    assert dt.year == 2024


def test_published_at_from_ytdlp_upload_date() -> None:
    meta = {"upload_date": "20240527"}
    dt = published_at_from_meta(meta)
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 5
    assert dt.day == 27
