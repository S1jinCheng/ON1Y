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


def test_click_following_tab_js_present() -> None:
    from on1y.browser import twitter_playwright as tw

    assert "Following" in tw._CLICK_FOLLOWING_TAB_JS
    assert "正在关注" in tw._CLICK_FOLLOWING_TAB_JS
    assert "for_you" in tw._ACTIVE_HOME_TAB_JS
    assert callable(tw.click_twitter_following_tab)
    assert callable(tw.ensure_twitter_following_tab)



def test_twitter_account_fallback_meta_normalizes_profile_data() -> None:
    from on1y.browser import twitter_playwright as tw

    class FakePage:
        def evaluate(self, script):
            assert script == tw._TWITTER_ACCOUNT_FALLBACK_META_JS
            return {
                "handle": "alice",
                "name": "Alice",
                "avatar": "//pbs.twimg.com/profile_images/alice.jpg",
            }

    assert tw._account_meta_from_fallback_page(FakePage()) == {
        "handle": "alice",
        "name": "Alice",
        "avatar": "https://pbs.twimg.com/profile_images/alice.jpg",
    }


def test_twitter_account_settings_meta_script_has_username_and_avatar_fallbacks() -> None:
    from on1y.browser import twitter_playwright as tw

    assert 'input[name="username"]' in tw._TWITTER_ACCOUNT_SETTINGS_META_JS
    assert 'input[name="displayName"]' in tw._TWITTER_ACCOUNT_SETTINGS_META_JS
    assert 'img[src*="profile_images"]' in tw._TWITTER_ACCOUNT_SETTINGS_META_JS
