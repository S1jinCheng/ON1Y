"""Per-user Telegram archive settings stored under data/users/<id>/telegram_settings.json.

Two acquisition modes:
- ``export``: scan Telegram Desktop JSON exports in ``export_dir``
- ``client``: pull incrementally via Telethon (local session, no Desktop export)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from on1y.auth.context import get_effective_user_id
from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)

SyncMode = Literal["export", "client"]


class TelegramSettings(BaseModel):
    enabled: bool = False
    sync_mode: SyncMode = "client"
    export_dir: str = ""
    api_id: int | None = None
    api_hash: str = ""
    sync_chat_ids: list[str] = Field(default_factory=list)
    interval_seconds: int = Field(default=300, ge=15, le=3600)
    auto_distill: bool = True
    session_gap_minutes: int = Field(default=30, ge=1, le=720)
    min_session_chars: int = Field(default=400, ge=0, le=100_000)
    min_msg_count: int = Field(default=6, ge=1, le=1000)
    min_substantive_ratio: float = Field(default=0.4, ge=0.0, le=1.0)
    prefer_local_llm: bool = True


def settings_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    return user_dir(uid) / "telegram_settings.json"


def load_settings(*, user_id: int | None = None) -> TelegramSettings:
    path = settings_file_path(user_id=user_id)
    if not path.is_file():
        return TelegramSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Invalid Telegram settings file: %s", path)
        return TelegramSettings()
    if not isinstance(payload, dict):
        return TelegramSettings()
    try:
        return TelegramSettings.model_validate(payload)
    except Exception:
        logger.warning("Invalid Telegram settings payload: %s", path)
        return TelegramSettings()


def save_settings(*, user_id: int | None = None, **fields: Any) -> TelegramSettings:
    uid = user_id if user_id is not None else get_effective_user_id()
    current = load_settings(user_id=uid)
    update: dict[str, Any] = {}
    if "enabled" in fields and fields["enabled"] is not None:
        update["enabled"] = bool(fields["enabled"])
    if "sync_mode" in fields and fields["sync_mode"] is not None:
        mode = str(fields["sync_mode"]).strip().lower()
        update["sync_mode"] = "client" if mode == "client" else "export"
    if "export_dir" in fields and fields["export_dir"] is not None:
        update["export_dir"] = str(fields["export_dir"]).strip()
    if "api_id" in fields and fields["api_id"] is not None:
        update["api_id"] = int(fields["api_id"]) if fields["api_id"] else None
    if "api_hash" in fields and fields["api_hash"] is not None:
        update["api_hash"] = str(fields["api_hash"]).strip()
    if "sync_chat_ids" in fields and fields["sync_chat_ids"] is not None:
        raw = fields["sync_chat_ids"]
        if isinstance(raw, list):
            update["sync_chat_ids"] = [str(x).strip() for x in raw if str(x).strip()]
        else:
            update["sync_chat_ids"] = []
    if "interval_seconds" in fields and fields["interval_seconds"] is not None:
        interval = int(fields["interval_seconds"])
        update["interval_seconds"] = max(15, min(3600, interval))
    if "auto_distill" in fields and fields["auto_distill"] is not None:
        update["auto_distill"] = bool(fields["auto_distill"])
    if "session_gap_minutes" in fields and fields["session_gap_minutes"] is not None:
        gap = int(fields["session_gap_minutes"])
        update["session_gap_minutes"] = max(1, min(720, gap))
    if "min_session_chars" in fields and fields["min_session_chars"] is not None:
        chars = int(fields["min_session_chars"])
        update["min_session_chars"] = max(0, min(100_000, chars))
    if "min_msg_count" in fields and fields["min_msg_count"] is not None:
        count = int(fields["min_msg_count"])
        update["min_msg_count"] = max(1, min(1000, count))
    if "min_substantive_ratio" in fields and fields["min_substantive_ratio"] is not None:
        ratio = float(fields["min_substantive_ratio"])
        update["min_substantive_ratio"] = max(0.0, min(1.0, ratio))
    if "prefer_local_llm" in fields and fields["prefer_local_llm"] is not None:
        update["prefer_local_llm"] = bool(fields["prefer_local_llm"])

    merged = current.model_copy(update=update)
    path = settings_file_path(user_id=uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return merged


def public_settings_view(*, user_id: int | None = None) -> dict[str, Any]:
    from on1y.telegram.client import client_configured, session_authorized

    settings = load_settings(user_id=user_id)
    payload = settings.model_dump()
    payload["session_authorized"] = session_authorized(user_id=user_id)
    payload["client_ready"] = client_configured(settings) and payload["session_authorized"]
    return payload


def sync_is_configured(cfg: TelegramSettings, *, user_id: int | None = None) -> bool:
    if not cfg.enabled:
        return False
    if cfg.sync_mode == "client":
        from on1y.telegram.client import client_configured, session_authorized

        return client_configured(cfg) and session_authorized(user_id=user_id)
    return bool((cfg.export_dir or "").strip())


def any_telegram_sync_enabled() -> bool:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import list_sync_user_ids

    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage, current_user_only=True)
    finally:
        storage.close()
    if not user_ids:
        return False
    for uid in user_ids:
        cfg = load_settings(user_id=uid)
        if sync_is_configured(cfg, user_id=uid):
            return True
    return False
