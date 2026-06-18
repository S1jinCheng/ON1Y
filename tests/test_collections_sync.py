"""Collections sync helpers."""

from unittest.mock import MagicMock

from on1y.ingestion.collections_sync import (
    _should_ingest_platform,
    parse_collections_platforms,
    sync_collections,
)
from on1y.ingestion.youtube_collections import _video_url_from_entry


def test_parse_collections_platforms() -> None:
    assert parse_collections_platforms("bilibili,zhihu,youtube") == [
        "bilibili",
        "zhihu",
        "youtube",
    ]
    assert parse_collections_platforms("youtube,bilibili") == ["youtube", "bilibili"]
    assert parse_collections_platforms("unknown,bilibili") == ["bilibili"]


def test_youtube_video_url_from_flat_entry() -> None:
    assert (
        _video_url_from_entry({"id": "dQw4w9WgXcQ", "title": "Test"})
        == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    assert _video_url_from_entry({"id": "PLsomething"}) is None


def test_should_ingest_platform_with_backlog() -> None:
    storage = MagicMock()
    storage.count_pending_for_platform.return_value = 3
    report = {"zhihu": {"enqueued": 0}}
    assert _should_ingest_platform(report, "zhihu", storage=storage) is True


def test_sync_collections_ingests_zhihu_backlog(monkeypatch) -> None:
    storage = MagicMock()
    storage.count_pending_for_platform.return_value = 2
    caught: list[dict] = []

    import on1y.ingestion.collections_sync as mod

    monkeypatch.setattr(mod, "backfill_zhihu_collections", lambda *a, **k: {"enqueued": 0})
    monkeypatch.setattr(
        "on1y.pipeline.zhihu_catchup.run_zhihu_catchup",
        lambda _storage, **kwargs: caught.append(kwargs) or {"processed": 1},
    )

    report = sync_collections(
        storage,
        platforms=["zhihu"],
        ingest=True,
        ingest_limit=5,
    )
    assert "zhihu" in report["ingest"]
    assert caught == [{"ingest_per_round": 5, "max_rounds": 1}]
