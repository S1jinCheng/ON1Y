"""Tests for Zhihu hot-list sync."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.hotlist.zhihu import _parse_hotlist_entry, sync_zhihu_hotlist


def test_parse_hotlist_entry_question() -> None:
    entry = {
        "detail_text": "1234 万热度",
        "target": {
            "type": "question",
            "id": 42,
            "title": "测试问题？",
            "excerpt": "这是问题描述。",
            "created": 1_700_000_000,
        },
    }
    parsed = _parse_hotlist_entry(entry, rank=1)
    assert parsed is not None
    assert parsed["title"] == "测试问题？"
    assert parsed["url"] == "https://www.zhihu.com/question/42"
    assert parsed["rank"] == 1
    assert parsed["heat_text"] == "1234 万热度"


@patch("on1y.hotlist.zhihu.fetch_zhihu_hotlist")
def test_sync_zhihu_hotlist_upserts(mock_fetch) -> None:
    mock_fetch.return_value = [
        {
            "question_id": "42",
            "title": "测试问题？",
            "excerpt": "这是问题描述。",
            "heat_text": "999 万热度",
            "rank": 1,
            "url": "https://www.zhihu.com/question/42",
            "published": "2026-06-01T00:00:00+00:00",
        }
    ]

    storage = MagicMock()
    storage.get_raw_by_url.return_value = None
    storage.upsert_raw_item.return_value = MagicMock(id=100)

    report = sync_zhihu_hotlist(storage, auto_tag=False)
    assert report["fetched"] == 1
    assert report["created"] == 1
    storage.upsert_raw_item.assert_called_once()
    storage.detach_hotlist_item.assert_called_with(100)
    storage.upsert_distilled.assert_called_once()
    storage.set_rss_feed_state.assert_called_once()
