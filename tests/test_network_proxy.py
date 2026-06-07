"""Network proxy resolution tests."""

from __future__ import annotations

from on1y.network.proxy import _normalize_proxy_url, effective_ytdlp_proxy
from on1y.network.settings import load_file_settings, save_file_settings


def test_normalize_proxy_url_adds_scheme() -> None:
    assert _normalize_proxy_url("127.0.0.1:7890") == "http://127.0.0.1:7890"


def test_effective_proxy_manual_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    save_file_settings(proxy_mode="manual", manual_proxy="http://127.0.0.1:7897", user_id=1)
    assert effective_ytdlp_proxy(user_id=1) == "http://127.0.0.1:7897"


def test_effective_proxy_off_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_YTDLP_PROXY", "http://127.0.0.1:7890")
    from on1y.config import get_settings

    get_settings.cache_clear()
    save_file_settings(proxy_mode="off", user_id=1)
    assert effective_ytdlp_proxy(user_id=1) is None
    prefs = load_file_settings(user_id=1)
    assert prefs["proxy_mode"] == "off"
