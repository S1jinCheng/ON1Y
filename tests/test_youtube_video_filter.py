"""YouTube live / Shorts / duration ingest filters."""

from on1y.config import Settings
from on1y.extract.ytdlp_meta import video_metadata_from_info
from on1y.models.video_extract import VideoMetadata
from on1y.utils.youtube_video_filter import (
    live_flags_from_info,
    should_skip_youtube_url,
    youtube_ingest_reject_reason,
)


def test_should_skip_youtube_live_and_shorts_urls() -> None:
    assert should_skip_youtube_url("https://www.youtube.com/live/abc123")
    assert should_skip_youtube_url("https://www.youtube.com/shorts/abc123")
    assert not should_skip_youtube_url("https://www.youtube.com/watch?v=abc123")
    assert not should_skip_youtube_url("https://example.com/video")


def test_live_flags_from_info() -> None:
    assert live_flags_from_info({"is_live": True}) == ("is_live", True, False)
    assert live_flags_from_info({"was_live": True}) == ("was_live", False, True)
    assert live_flags_from_info({"live_status": "post_live"}) == ("post_live", False, False)


def test_video_metadata_from_info_includes_live_fields() -> None:
    meta = video_metadata_from_info(
        {
            "title": "Test",
            "description": "desc",
            "duration": 600,
            "live_status": "not_live",
        }
    )
    assert meta.duration_sec == 600
    assert meta.live_status == "not_live"
    assert not meta.is_live
    assert not meta.was_live


def test_reject_live_stream() -> None:
    settings = Settings()
    meta = VideoMetadata(
        title="Live now",
        description="",
        duration_sec=None,
        live_status="is_live",
        is_live=True,
    )
    assert youtube_ingest_reject_reason("https://www.youtube.com/watch?v=x", meta, settings) == "youtube_live"


def test_reject_live_replay() -> None:
    settings = Settings()
    meta = VideoMetadata(
        title="Replay",
        description="",
        duration_sec=3600,
        live_status="was_live",
        was_live=True,
    )
    assert (
        youtube_ingest_reject_reason("https://www.youtube.com/watch?v=x", meta, settings)
        == "youtube_live_replay"
    )


def test_reject_shorts_by_duration() -> None:
    settings = Settings()
    meta = VideoMetadata(title="Short", description="", duration_sec=45)
    assert (
        youtube_ingest_reject_reason("https://www.youtube.com/watch?v=x", meta, settings)
        == "youtube_shorts"
    )


def test_reject_too_short_regular_video() -> None:
    settings = Settings()
    meta = VideoMetadata(title="Clip", description="", duration_sec=90, live_status="not_live")
    assert (
        youtube_ingest_reject_reason("https://www.youtube.com/watch?v=x", meta, settings)
        == "youtube_too_short"
    )


def test_allow_long_regular_video() -> None:
    settings = Settings()
    meta = VideoMetadata(
        title="Long form",
        description="",
        duration_sec=900,
        live_status="not_live",
    )
    assert youtube_ingest_reject_reason("https://www.youtube.com/watch?v=x", meta, settings) is None
