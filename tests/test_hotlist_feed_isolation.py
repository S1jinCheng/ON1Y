"""Hot-list must not absorb subscription feed rows."""

from __future__ import annotations

from datetime import date

from on1y.auth.context import user_context
from on1y.hotlist.sql import is_feed_row_meta
from on1y.hotlist.zhihu import sync_zhihu_hotlist
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate


def test_is_feed_row_meta() -> None:
    assert is_feed_row_meta({}) is True
    assert is_feed_row_meta({"hotlist_source": ""}) is True
    assert is_feed_row_meta({"hotlist_source": "zhihu"}) is False


def test_zhihu_hotlist_skips_existing_feed_url(storage, monkeypatch) -> None:
    url = "https://www.zhihu.com/question/12345"
    with user_context(1):
        feed = storage.upsert_raw_item(
            RawItemCreate(
                url=url,
                platform="zhihu",
                source=SourceType.RSS,
                raw_title="订阅里的问题",
                body_text="正文",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
                source_meta={"feed_label": "zhihu-follow"},
            )
        )

        def fake_fetch(**_kwargs):
            return [
                {
                    "question_id": "12345",
                    "title": "热榜标题",
                    "url": url,
                    "excerpt": "热榜摘要",
                    "rank": 1,
                    "heat_text": "100万热度",
                    "published": None,
                }
            ]

        monkeypatch.setattr("on1y.hotlist.zhihu.fetch_zhihu_hotlist", fake_fetch)
        report = sync_zhihu_hotlist(storage, snapshot_date=date.today().isoformat())

    assert report["skipped_feed_overlap"] == 1
    assert report["created"] == 0
    row = storage.get_raw_by_id(feed.id)
    assert row is not None
    assert is_feed_row_meta(row.source_meta)
    assert row.raw_title == "订阅里的问题"
    hotlist_count = storage.count_collection_items(
        "hotlist",
        hotlist_date=date.today().isoformat(),
        hotlist_source="zhihu",
    )
    with user_context(1):
        assert hotlist_count == 0
