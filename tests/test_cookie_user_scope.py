"""Per-user cookie path isolation."""

from __future__ import annotations

import json

import pytest

from on1y.auth.context import user_context
from on1y.cookies.loader import resolve_cookie_path
from on1y.exceptions import ConfigurationError


def test_resolve_cookie_path_user2_never_uses_legacy_global(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    legacy = tmp_path / "cookies"
    legacy.mkdir(parents=True)
    (legacy / "youtube.json").write_text(json.dumps([]), encoding="utf-8")
    (legacy / "zhihu.json").write_text(json.dumps([]), encoding="utf-8")

    user2_dir = tmp_path / "users" / "2" / "cookies"
    user2_dir.mkdir(parents=True)
    (user2_dir / "bilibili.json").write_text(json.dumps([]), encoding="utf-8")

    settings = get_settings()
    with user_context(2):
        yt = resolve_cookie_path("youtube", settings)
        zh = resolve_cookie_path("zhihu", settings)
        bi = resolve_cookie_path("bilibili", settings)

    assert yt == tmp_path / "users" / "2" / "cookies" / "youtube.json"
    assert zh == tmp_path / "users" / "2" / "cookies" / "zhihu.json"
    assert bi == tmp_path / "users" / "2" / "cookies" / "bilibili.json"
    assert not yt.is_file()
    assert not zh.is_file()
    assert bi.is_file()


def test_resolve_cookie_path_user1_can_fallback_legacy(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    legacy_yt = tmp_path / "legacy-youtube.json"
    legacy_yt.write_text(json.dumps([]), encoding="utf-8")

    settings = get_settings().model_copy(update={"youtube_cookies_path": legacy_yt})
    with user_context(1):
        path = resolve_cookie_path("youtube", settings)

    assert path == legacy_yt


def test_resolve_cookie_path_requires_user_context(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    with pytest.raises(ConfigurationError, match="user context required"):
        resolve_cookie_path("youtube", settings)
