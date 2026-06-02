"""Subscription sync settings persisted in data/subscription_settings.json."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from on1y.auth.context import get_effective_user_id
from on1y.config import get_settings

logger = logging.getLogger(__name__)

PLATFORMS = ("bilibili", "youtube", "zhihu")


def settings_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    from on1y.user.paths import user_dir

    return user_dir(uid) / "subscription_settings.json"


def _legacy_settings_file_path() -> Path:
    return get_settings().data_dir / "subscription_settings.json"


def _empty_payload() -> dict[str, Any]:
    return {
        "bilibili_sync_since": None,
        "youtube_sync_since": None,
        "zhihu_sync_since": None,
        "enabled_platforms": list(PLATFORMS),
    }


def _load_from_db(user_id: int) -> dict[str, Any] | None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import UserStore

    storage = get_storage()
    try:
        if storage._current_schema_version(storage._connect()) < 9:
            return None
        raw = UserStore(storage).get_subscription_json(user_id)
        if raw is None:
            return None
        return _normalize_subscription(raw)
    finally:
        storage.close()


def _normalize_subscription(data: dict[str, Any]) -> dict[str, Any]:
    out = _empty_payload()
    for platform in PLATFORMS:
        key = f"{platform}_sync_since"
        raw = data.get(key)
        if raw is None or raw == "":
            out[key] = None
        else:
            out[key] = str(raw).strip()
    raw_enabled = data.get("enabled_platforms")
    if isinstance(raw_enabled, list):
        enabled = [str(p).strip() for p in raw_enabled if str(p).strip() in PLATFORMS]
        if enabled:
            out["enabled_platforms"] = enabled
    return out


def load_subscription_settings(*, user_id: int | None = None) -> dict[str, Any]:
    uid = user_id if user_id is not None else get_effective_user_id()
    from_db = _load_from_db(uid)
    if from_db is not None:
        return from_db

    path = settings_file_path(user_id=uid)
    if not path.is_file() and uid == 1:
        legacy = _legacy_settings_file_path()
        if legacy.is_file():
            path = legacy
    if not path.is_file():
        return _empty_payload()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_payload()
        payload = _normalize_subscription(data)
        _save_subscription_settings(payload, user_id=uid)
        return payload
    except json.JSONDecodeError:
        logger.warning("Invalid subscription settings file: %s", path)
        return _empty_payload()


def _parse_iso_date(value: str | None) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _save_subscription_settings(payload: dict[str, Any], *, user_id: int) -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import UserStore

    storage = get_storage()
    try:
        if storage._current_schema_version(storage._connect()) >= 9:
            UserStore(storage).save_subscription_json(user_id, payload)
    finally:
        storage.close()
    path = settings_file_path(user_id=user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_subscription_settings(
    *,
    bilibili_sync_since: str | None = None,
    youtube_sync_since: str | None = None,
    zhihu_sync_since: str | None = None,
    enabled_platforms: list[str] | None = None,
    user_id: int | None = None,
) -> None:
    uid = user_id if user_id is not None else get_effective_user_id()
    current = load_subscription_settings(user_id=uid)

    def normalize(field: str, incoming: str | None) -> str | None:
        if incoming is None:
            return current.get(field)
        text = str(incoming).strip()
        if not text:
            return None
        parsed = _parse_iso_date(text)
        if parsed is None:
            raise ValueError(f"invalid date for {field}: {incoming!r}")
        return parsed.isoformat()

    payload = {
        "bilibili_sync_since": normalize("bilibili_sync_since", bilibili_sync_since),
        "youtube_sync_since": normalize("youtube_sync_since", youtube_sync_since),
        "zhihu_sync_since": normalize("zhihu_sync_since", zhihu_sync_since),
        "enabled_platforms": current.get("enabled_platforms") or list(PLATFORMS),
    }
    if enabled_platforms is not None:
        cleaned = [p for p in enabled_platforms if p in PLATFORMS]
        if not cleaned:
            raise ValueError("enabled_platforms must include at least one platform")
        payload["enabled_platforms"] = cleaned
    _save_subscription_settings(payload, user_id=uid)
    logger.info("Saved subscription settings for user %s", uid)


def public_settings_view() -> dict[str, Any]:
    from on1y.config import get_settings

    cfg = load_subscription_settings()
    settings = get_settings()
    return {
        **cfg,
        "platforms": list(PLATFORMS),
        "bilibili_up_sync_enabled": settings.bilibili_up_sync_enabled,
        "bilibili_up_poll_mode": settings.bilibili_up_poll_mode,
        "auto_sync_enabled": settings.auto_sync_enabled,
        "auto_sync_interval_minutes": settings.auto_sync_interval_minutes,
        "youtube_auto_refresh_channels": settings.youtube_auto_refresh_channels,
        "zhihu_auto_refresh_follows": settings.zhihu_auto_refresh_follows,
    }


def sync_since_date(platform: str, *, user_id: int | None = None) -> date | None:
    if platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")
    key = f"{platform}_sync_since"
    return _parse_iso_date(load_subscription_settings(user_id=user_id).get(key))


def sync_since_timestamp(platform: str) -> int | None:
    """UTC start-of-day timestamp for the configured sync-since date."""
    day = sync_since_date(platform)
    if day is None:
        return None
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
