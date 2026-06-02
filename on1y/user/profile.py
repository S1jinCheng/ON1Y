"""Per-user profile in SQLite (schema v9) with legacy file fallback."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from on1y.auth.context import get_effective_user_id
from on1y.config import Settings, get_settings
from on1y.user.paths import COOKIE_PLATFORMS, user_cookie_path

logger = logging.getLogger(__name__)

PROFILE_VERSION = 1


def profile_file_path() -> Path:
    """Legacy single-user file (migrated on bootstrap)."""
    return get_settings().data_dir / "user_profile.json"


def example_profile_path() -> Path:
    return get_settings().data_dir.parent / "config" / "user_profile.json.example"


def _default_payload(settings: Settings | None = None, *, user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    uid = user_id if user_id is not None else get_effective_user_id()
    kindle_to = (settings.kindle_send_to or "").strip()
    cookies: dict[str, str] = {}
    for platform in COOKIE_PLATFORMS:
        cookies[platform] = str(user_cookie_path(uid, platform))
    return {
        "version": PROFILE_VERSION,
        "owner": "default",
        "kindle": {
            "enabled": bool(kindle_to) and settings.economist_auto_kindle,
            "send_to": kindle_to,
        },
        "economist": {
            "auto_ingest_enabled": settings.economist_auto_sync_enabled,
            "auto_kindle_enabled": settings.economist_auto_kindle,
            "last_synced_edition": None,
            "last_kindle_edition": None,
        },
        "integrations": {
            "cookies": cookies,
            "llm": {
                "source": "env and/or per-user llm_settings.json",
                "base_url": settings.llm_base_url,
                "model": settings.llm_model,
                "api_key_configured": bool(settings.llm_api_key),
            },
            "smtp": {
                "host": settings.smtp_host or "",
                "port": settings.smtp_port,
                "from": settings.smtp_from or "",
                "user_configured": bool(settings.smtp_user),
            },
        },
    }


def _normalize_profile(data: dict[str, Any], *, user_id: int | None = None) -> dict[str, Any]:
    base = _default_payload(user_id=user_id)
    kindle_in = data.get("kindle") if isinstance(data.get("kindle"), dict) else {}
    econ_in = data.get("economist") if isinstance(data.get("economist"), dict) else {}
    base["owner"] = str(data.get("owner") or base["owner"])
    base["kindle"]["enabled"] = bool(kindle_in.get("enabled", base["kindle"]["enabled"]))
    send_to = str(kindle_in.get("send_to") or base["kindle"]["send_to"] or "").strip()
    base["kindle"]["send_to"] = send_to
    base["economist"]["auto_ingest_enabled"] = bool(
        econ_in.get("auto_ingest_enabled", base["economist"]["auto_ingest_enabled"])
    )
    base["economist"]["auto_kindle_enabled"] = bool(
        econ_in.get("auto_kindle_enabled", base["economist"]["auto_kindle_enabled"])
    )
    for key in ("last_synced_edition", "last_kindle_edition"):
        raw = econ_in.get(key)
        base["economist"][key] = str(raw).strip() if raw else None
    if isinstance(data.get("integrations"), dict):
        base["integrations"] = {**base["integrations"], **data["integrations"]}
    uid = user_id if user_id is not None else get_effective_user_id()
    cookies_map = base["integrations"].get("cookies")
    if isinstance(cookies_map, dict):
        for platform in COOKIE_PLATFORMS:
            cookies_map[platform] = str(user_cookie_path(uid, platform))
    return base


def _load_from_db(user_id: int) -> dict[str, Any] | None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import UserStore

    storage = get_storage()
    try:
        if storage._current_schema_version(storage._connect()) < 9:
            return None
        raw = UserStore(storage).get_profile_json(user_id)
        if raw is None:
            return None
        return _normalize_profile(raw, user_id=user_id)
    finally:
        storage.close()


def _save_to_db(user_id: int, profile: dict[str, Any]) -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import UserStore

    storage = get_storage()
    try:
        UserStore(storage).save_profile_json(user_id, profile)
    finally:
        storage.close()


def load_user_profile(
    user_id: int | None = None,
    *,
    create_if_missing: bool = True,
) -> dict[str, Any]:
    uid = user_id if user_id is not None else get_effective_user_id()
    from_db = _load_from_db(uid)
    if from_db is not None:
        return from_db

    path = profile_file_path()
    if path.is_file() and uid == 1:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                payload = _normalize_profile(data, user_id=uid)
                if create_if_missing:
                    _save_to_db(uid, payload)
                return payload
        except json.JSONDecodeError:
            logger.warning("Invalid legacy user profile: %s", path)

    payload = _default_payload(user_id=uid)
    if create_if_missing:
        _save_to_db(uid, payload)
    return payload


def save_user_profile(payload: dict[str, Any] | None = None, *, user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_effective_user_id()
    data = _normalize_profile(
        payload or load_user_profile(uid, create_if_missing=False),
        user_id=uid,
    )
    _save_to_db(uid, data)


def patch_user_profile(*, user_id: int | None = None, **sections: Any) -> dict[str, Any]:
    uid = user_id if user_id is not None else get_effective_user_id()
    current = load_user_profile(uid)
    if "kindle" in sections and isinstance(sections["kindle"], dict):
        current["kindle"].update(sections["kindle"])
    if "economist" in sections and isinstance(sections["economist"], dict):
        current["economist"].update(sections["economist"])
    save_user_profile(current, user_id=uid)
    return current


def public_profile_view(user_id: int | None = None) -> dict[str, Any]:
    profile = load_user_profile(user_id)
    integrations = profile.get("integrations") or {}
    llm = integrations.get("llm") if isinstance(integrations.get("llm"), dict) else {}
    smtp = integrations.get("smtp") if isinstance(integrations.get("smtp"), dict) else {}
    cookies = integrations.get("cookies") if isinstance(integrations.get("cookies"), dict) else {}
    cookie_status = {}
    for platform, path_str in cookies.items():
        p = Path(str(path_str))
        cookie_status[platform] = {"path": str(p), "exists": p.is_file()}
    return {
        "user_id": user_id if user_id is not None else get_effective_user_id(),
        "owner": profile.get("owner"),
        "kindle": {
            "enabled": profile["kindle"]["enabled"],
            "send_to": profile["kindle"]["send_to"],
        },
        "economist": dict(profile["economist"]),
        "integrations": {
            "cookies": cookie_status,
            "llm": {
                "base_url": llm.get("base_url"),
                "model": llm.get("model"),
                "api_key_configured": llm.get("api_key_configured"),
            },
            "smtp": {
                "host": smtp.get("host"),
                "port": smtp.get("port"),
                "from": smtp.get("from"),
                "configured": bool(smtp.get("user_configured")),
            },
        },
    }


def economist_automation_enabled(profile: dict[str, Any] | None = None) -> bool:
    profile = profile or load_user_profile()
    settings = get_settings()
    if not settings.economist_hotlist_enabled:
        return False
    return bool(profile["economist"]["auto_ingest_enabled"])
