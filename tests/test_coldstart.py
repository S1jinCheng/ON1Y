"""Cold-start / backfill helpers."""

from unittest.mock import MagicMock

from on1y.ingestion.rss import _should_skip_backfill_url
from on1y.ingestion.zhihu_follow_list import merge_follows_file
from on1y.models.enums import ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate


def test_merge_follows_file_collection_entries(tmp_path) -> None:
    path = tmp_path / "zhihu_follows.txt"
    path.write_text("activities:user-a\n", encoding="utf-8")
    added, total = merge_follows_file(
        [
            {"id": "809894830", "name": "我的收藏", "feed_type": "collection"},
            {"id": "989942573", "name": "科研", "feed_type": "collection"},
        ],
        path,
    )
    assert added == 2
    assert total == 3
    text = path.read_text(encoding="utf-8")
    assert "collection:809894830" in text
    assert "collection:989942573" in text


def test_merge_follows_file_adds_new_lines(tmp_path) -> None:
    path = tmp_path / "zhihu_follows.txt"
    path.write_text("activities:existing-user\n", encoding="utf-8")
    added, total = merge_follows_file(
        [
            {"url_token": "existing-user", "name": "A", "feed_type": "activities"},
            {"url_token": "new-user", "name": "B", "feed_type": "activities"},
        ],
        path,
    )
    assert added == 1
    assert total == 2
    text = path.read_text(encoding="utf-8")
    assert "activities:new-user" in text
    assert "activities:existing-user" in text


def test_should_skip_backfill_when_raw_exists(storage) -> None:
    storage.upsert_raw_item(
        RawItemCreate(
            url="https://www.zhihu.com/question/1/answer/1",
            platform="zhihu",
            source=SourceType.RSS,
            raw_title="t",
            body_text="body " * 20,
            content_type="article",
            extract_status=ExtractStatus.OK,
        )
    )
    assert _should_skip_backfill_url(
        storage,
        "https://www.zhihu.com/question/1/answer/1",
    )


def test_should_skip_backfill_when_in_queue(storage) -> None:
    from on1y.ingestion.enqueue import enqueue_url

    enqueue_url(storage, "https://example.com/new", source=SourceType.RSS)
    assert _should_skip_backfill_url(storage, "https://example.com/new")


def test_poll_rss_feeds_backfill_enqueues_feed_entries(storage, monkeypatch) -> None:
    from on1y.ingestion import rss as rss_mod
    from on1y.ingestion.rss import FeedConfig, poll_rss_feeds_backfill

    feed = FeedConfig(url="http://test/feed", label="zhihu-test", enabled=True)

    class FakeEntry(dict):
        pass

    parsed = MagicMock()
    parsed.bozo = False
    parsed.entries = [
        FakeEntry(
            link="https://www.zhihu.com/question/2/answer/2",
            id="e2",
            title="second",
            published="Wed, 01 Jan 2025 12:00:00 GMT",
        ),
        FakeEntry(
            link="https://www.zhihu.com/question/1/answer/1",
            id="e1",
            title="first",
            published="Wed, 01 Jan 2024 12:00:00 GMT",
        ),
    ]

    monkeypatch.setattr(rss_mod, "load_feeds", lambda _path=None: [feed])
    monkeypatch.setattr(rss_mod, "parse_feed", lambda _feed: parsed)

    count = poll_rss_feeds_backfill(storage, label_prefix="zhihu-", max_items_per_feed=10)
    assert count == 2
    last_id, _ = storage.get_rss_feed_state(feed.url)
    assert last_id == "e2"
