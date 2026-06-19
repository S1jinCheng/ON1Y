"""Tests for Zhihu following-moments poll."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from on1y.ingestion.zhihu_subscriptions import poll_zhihu_following_moments


def test_poll_zhihu_following_moments_enqueues_create_verbs_only() -> None:
    storage = MagicMock()
    storage.get_rss_feed_state.return_value = (None, None)
    storage.get_raw_by_url.return_value = None
    storage.url_in_rss_queue.return_value = False

    moments = [
        {
            "id": "m1",
            "verb": "MEMBER_ANSWER_QUESTION",
            "created_time": 1_900_000_000,
            "actors": [{"name": "Alice"}],
            "target": {
                "type": "answer",
                "id": "1",
                "question": {"id": "9", "title": "Q1"},
            },
        },
        {
            "id": "m2",
            "verb": "MEMBER_VOTEUP_ANSWER",
            "created_time": 1_900_000_001,
            "target": {"type": "answer", "id": "2", "question": {"id": "8", "title": "Q2"}},
        },
        {
            "id": "m3",
            "verb": "MEMBER_CREATE_ARTICLE",
            "created_time": 1_900_000_002,
            "target": {"type": "article", "id": "77", "title": "Article"},
        },
    ]

    with (
        patch("on1y.ingestion.zhihu_subscriptions._cookie_jar", return_value={"z_c0": "x"}),
        patch(
            "on1y.ingestion.zhihu_subscriptions.iter_following_moments",
            return_value=iter(moments),
        ),
    ):
        report = poll_zhihu_following_moments(storage, backfill=True)

    assert report["mode"] == "moments"
    assert report["enqueued"] == 2
    assert report["skipped_unsupported"] == 1
    storage.set_rss_feed_state.assert_called_once()
