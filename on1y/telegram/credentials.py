"""Resolve Telegram Client API credentials (user settings or server env)."""

from __future__ import annotations

from on1y.config import get_settings
from on1y.telegram.settings import TelegramSettings


def resolve_api_credentials(cfg: TelegramSettings | None = None) -> tuple[int, str] | None:
    """Return (api_id, api_hash) from user settings or ON1Y_TELEGRAM_* env."""
    user_id: int | None = None
    user_hash = ""
    if cfg is not None:
        user_id = cfg.api_id
        user_hash = (cfg.api_hash or "").strip()

    app = get_settings()
    api_id = user_id or app.telegram_api_id
    api_hash = user_hash or (app.telegram_api_hash or "").strip()
    if api_id and api_hash:
        return int(api_id), api_hash
    return None


def api_credentials_configured(cfg: TelegramSettings | None = None) -> bool:
    return resolve_api_credentials(cfg) is not None
