"""Tests for YouTube account profile resolution."""

from __future__ import annotations

import json

from on1y.utils.youtube_account import (
    _decode_json_string,
    _parse_yt_initial_data,
    _pick_best_profile,
    _walk_profile_candidates,
    _channel_title_from_html,
)


def test_parse_yt_initial_data_from_html() -> None:
    payload = {
        "header": {
            "activeAccountHeader": {
                "accountName": {"simpleText": "Alice Channel"},
                "accountAvatar": {
                    "thumbnails": [{"url": "https://yt3.ggpht.com/avatar=s88"}],
                },
                "navigationEndpoint": {
                    "browseEndpoint": {"browseId": "UCtest123456789012345678"},
                },
            }
        }
    }
    html = f"<script>var ytInitialData = {json.dumps(payload)};</script>"
    parsed = _parse_yt_initial_data(html)
    assert parsed is not None
    candidates: list[dict[str, str]] = []
    _walk_profile_candidates(parsed, candidates)
    profile = _pick_best_profile(candidates)
    assert profile is not None
    assert profile["account_name"] == "Alice Channel"
    assert profile["account_id"] == "UCtest123456789012345678"
    assert "yt3.ggpht.com" in profile["avatar_url"]


def test_verify_youtube_returns_profile(monkeypatch) -> None:
    from pathlib import Path

    from on1y.config import get_settings
    from on1y.cookies.verify import _verify_youtube

    def fake_profile(**_kwargs):
        return {
            "account_id": "UCtest123456789012345678",
            "account_name": "Alice Channel",
            "avatar_url": "https://yt3.ggpht.com/avatar=s88",
        }

    monkeypatch.setattr("on1y.utils.youtube_account.fetch_youtube_account_profile", fake_profile)
    cookies = [
        {"name": "__Secure-1PSID", "value": "x", "domain": ".google.com"},
        {"name": "SAPISID", "value": "y", "domain": ".google.com"},
    ]
    account = _verify_youtube(
        cookies,
        settings=get_settings(),
        cookie_path=Path("youtube.json"),
        user_id=1,
        quick=True,
    )
    assert account["valid"] is True
    assert account["account_name"] == "Alice Channel"
    assert account["avatar_url"] == "https://yt3.ggpht.com/avatar=s88"


def test_channel_title_from_html_preserves_utf8() -> None:
    html = '<script>"channelMetadataRenderer":{"title":"助人为衣"}</script>'
    assert _channel_title_from_html(html) == "助人为衣"


def test_channel_title_from_html_unicode_escape() -> None:
    html = r'<script>"channelMetadataRenderer":{"title":"\u4e2d\u6587\u9891\u9053"}</script>'
    assert _channel_title_from_html(html) == "中文频道"


def test_decode_json_string_does_not_mojibake_utf8() -> None:
    assert _decode_json_string("助人为衣") == "助人为衣"
