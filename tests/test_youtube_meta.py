from on1y.pipeline.youtube_meta import (
    SUBTITLE_STATUS_READY,
    is_subtitle_ready,
    with_subtitle_pending,
    with_subtitle_ready,
)


def test_subtitle_meta_pending_and_ready() -> None:
    meta = with_subtitle_pending({"feed_label": "test"})
    assert meta["subtitle_status"] == "pending"
    assert meta["feed_label"] == "test"
    assert not is_subtitle_ready(meta)

    ready = with_subtitle_ready(meta)
    assert ready["subtitle_status"] == SUBTITLE_STATUS_READY
    assert is_subtitle_ready(ready)
