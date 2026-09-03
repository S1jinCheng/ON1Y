"""Tests for Telegram API credential resolution."""

from __future__ import annotations

from on1y.telegram.credentials import api_credentials_configured, resolve_api_credentials
from on1y.telegram.settings import TelegramSettings


def test_resolve_api_credentials_from_user_settings() -> None:
    cfg = TelegramSettings(api_id=12345, api_hash="abc")
    assert resolve_api_credentials(cfg) == (12345, "abc")
    assert api_credentials_configured(cfg) is True


def test_resolve_api_credentials_empty_without_env(monkeypatch) -> None:
    monkeypatch.delenv("ON1Y_TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("ON1Y_TELEGRAM_API_HASH", raising=False)
    from on1y.config import get_settings

    get_settings.cache_clear()
    cfg = TelegramSettings()
    assert resolve_api_credentials(cfg) is None
    assert api_credentials_configured(cfg) is False
    get_settings.cache_clear()
