"""Tests for Economist RSS hot-list sync."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.hotlist.economist import _entry_excerpt, _strip_html, sync_economist_hotlist


def test_strip_html() -> None:
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_entry_excerpt_from_summary() -> None:
    entry = {"summary": "<p>Lead paragraph.</p>"}
    assert _entry_excerpt(entry) == "Lead paragraph."


@patch("on1y.hotlist.epub_preview.build_economist_preview")
@patch("on1y.hotlist.economist.fetch_economist_hotlist")
def test_sync_economist_hotlist_upserts(mock_fetch, mock_preview) -> None:
    mock_fetch.return_value = [
        {
            "entry_id": "ec-1",
            "title": "经济学人 2026年第22周",
            "excerpt": "",
            "heat_text": "2026-05-30",
            "rank": 1,
            "url": "https://example.com/TheEconomist.2026.05.30.epub",
            "epub_url": "https://example.com/TheEconomist.2026.05.30.epub",
            "edition_date": "2026-05-30",
            "published": "Mon, 01 Jun 2026 00:00:00 GMT",
        }
    ]
    mock_preview.return_value = {
        "summary": "出刊日期 **2026-05-30**。\n\n**目录**\n- Leaders",
        "body_text": "Hello preview text",
        "excerpt": "Hello preview",
        "chapters": ["Leaders"],
        "chapter_count": 1,
        "preview_chars": 5,
    }

    storage = MagicMock()
    storage.get_raw_by_url.return_value = None
    storage.get_hotlist_raw_id.return_value = None
    storage.upsert_raw_item.return_value = MagicMock(id=200)

    report = sync_economist_hotlist(storage, auto_tag=False)
    assert report["fetched"] == 1
    assert report["created"] == 1
    storage.detach_hotlist_item.assert_called_with(200)
    storage.upsert_distilled.assert_called_once()
