"""Cookie account verification helpers."""

from __future__ import annotations

from on1y.cookies.verify import _youtube_login_cookie_check, verify_cookie_account


def test_youtube_login_cookie_check_guest() -> None:
    cookies = [
        {"name": "VISITOR_INFO1_LIVE", "value": "x", "domain": ".youtube.com"},
        {"name": "YSC", "value": "y", "domain": ".youtube.com"},
    ]
    ok, hint = _youtube_login_cookie_check(cookies)
    assert ok is False
    assert "访客" in hint


def test_youtube_login_cookie_check_logged_in() -> None:
    cookies = [
        {"name": "__Secure-1PSID", "value": "x", "domain": ".google.com"},
        {"name": "SAPISID", "value": "y", "domain": ".google.com"},
    ]
    ok, hint = _youtube_login_cookie_check(cookies)
    assert ok is True
    assert hint == ""


def test_verify_bilibili_account(storage, monkeypatch) -> None:
    import json

    from on1y.auth.context import user_context
    from on1y.user.paths import user_cookie_path

    path = user_cookie_path(1, "bilibili")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "SESSDATA", "value": "test", "domain": ".bilibili.com", "path": "/"},
                ],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )

    with user_context(1):

        def fake_me(**_kwargs):
            return {"mid": "123", "name": "测试用户", "face": "https://example.com/a.jpg"}

        monkeypatch.setattr("on1y.ingestion.bilibili_api.fetch_bilibili_me", fake_me)
        monkeypatch.setattr("on1y.ingestion.bilibili_api.fetch_bilibili_up_face", lambda *_a, **_k: "")

        account = verify_cookie_account("bilibili", user_id=1, force=True)

    assert account["valid"] is True
    assert account["account_name"] == "测试用户"
    assert account["avatar_url"] == "https://example.com/a.jpg"
    assert user_cookie_path(1, "bilibili").is_file()
