"""Collections sync helpers."""

from on1y.ingestion.collections_sync import parse_collections_platforms
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
