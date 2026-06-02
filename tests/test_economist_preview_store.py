"""Tests for Economist preview persistence helpers."""

from __future__ import annotations

from on1y.hotlist.economist_preview_store import preview_is_complete


def test_preview_is_complete_by_chars() -> None:
    meta = {"preview_chars": 500}
    assert preview_is_complete("", meta) is True


def test_preview_is_complete_rejects_download_only() -> None:
    body = "EPUB 下载：https://example.com/book.epub"
    assert preview_is_complete(body, {}) is False
