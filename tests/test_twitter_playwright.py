"""Tests for X/Twitter URL helpers."""

from __future__ import annotations

from on1y.browser.twitter_playwright import (
    normalize_twitter_status_url,
    parse_status_id,
)
from on1y.subscriptions import SYNC_PLATFORMS
from on1y.subscriptions.settings import PLATFORMS


def test_parse_status_id() -> None:
    assert parse_status_id("https://x.com/elonmusk/status/1234567890") == "1234567890"
    assert parse_status_id("https://twitter.com/foo/status/99") == "99"
    assert parse_status_id("https://example.com") is None


def test_normalize_twitter_status_url() -> None:
    assert (
        normalize_twitter_status_url("https://x.com/user/status/42?ref=1")
        == "https://x.com/i/web/status/42"
    )


def test_twitter_likes_url() -> None:
    from on1y.browser.twitter_playwright import twitter_likes_url

    assert twitter_likes_url("elonmusk") == "https://x.com/elonmusk/likes"
    assert twitter_likes_url("@jack") == "https://x.com/jack/likes"


def test_normalize_twitter_image_url() -> None:
    from on1y.browser.twitter_playwright import _normalize_twitter_image_url

    assert (
        _normalize_twitter_image_url("//pbs.twimg.com/profile_images/1/x.jpg")
        == "https://pbs.twimg.com/profile_images/1/x.jpg"
    )
    assert _normalize_twitter_image_url("https://pbs.twimg.com/x.jpg") == "https://pbs.twimg.com/x.jpg"
    assert _normalize_twitter_image_url("") is None


def test_sync_platforms_include_twitter() -> None:
    assert "twitter" in SYNC_PLATFORMS
    assert "twitter" in PLATFORMS
