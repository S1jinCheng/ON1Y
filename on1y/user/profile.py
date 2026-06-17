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


def _llm_integration_defaults(*, user_id: int | None = None) -> dict[str, Any]:
    from on1y.llm.settings import public_settings_view

    pub = public_settings_view(user_id=user_id)
    return {
        "source": "per-user data/users/<id>/llm_settings.json",
        "base_url": pub["base_url"],
        "model": pub["model"],
        "api_key_configured": pub["api_key_set"],
    }


def _smtp_integration_defaults(*, user_id: int | None = None) -> dict[str, Any]:
    from on1y.delivery.smtp_settings import public_settings_view

    pub = public_settings_view(user_id=user_id)
    return {
        "host": pub["host"],
        "port": pub["port"],
        "from": pub["from"],
        "user": pub["user"],
        "use_tls": pub["use_tls"],
        "configured": pub["configured"],
        "password_set": pub["password_set"],
    }


def kindle_delivery_address(profile: dict[str, Any]) -> str:
    """Per-user Kindle recipient from profile only (never global .env)."""
    kindle = profile.get("kindle") if isinstance(profile.get("kindle"), dict) else {}
    return str(kindle.get("send_to") or "").strip()


def _default_payload(settings: Settings | None = None, *, user_id: int | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    uid = user_id if user_id is not None else get_effective_user_id()
    cookies: dict[str, str] = {}
    for platform in COOKIE_PLATFORMS:
        cookies[platform] = str(user_cookie_path(uid, platform))
    return {
        "version": PROFILE_VERSION,
        "owner": "default",
        "app": {
            "locale": "zh",
            "appearance": "system",
            "open_browser_on_start": True,
            "last_today_visit_at": None,
        },
        "kindle": {
            "enabled": False,
            "send_to": "",
        },
        "economist": {
            "auto_ingest_enabled": False,
            "auto_kindle_enabled": False,
            "last_synced_edition": None,
            "last_kindle_edition": None,
        },
        "cold_start": {
            "onboarding_dismissed": False,
            "last_completed_at": None,
        },
        "integrations": {
            "cookies": cookies,
            "llm": _llm_integration_defaults(user_id=uid),
            "smtp": _smtp_integration_defaults(user_id=uid),
        },
    }


def _normalize_profile(data: dict[str, Any], *, user_id: int | None = None) -> dict[str, Any]:
    base = _default_payload(user_id=user_id)
    kindle_in = data.get("kindle") if isinstance(data.get("kindle"), dict) else {}
    econ_in = data.get("economist") if isinstance(data.get("economist"), dict) else {}
    base["owner"] = str(data.get("owner") or base["owner"])
    app_in = data.get("app") if isinstance(data.get("app"), dict) else {}
    locale = str(app_in.get("locale") or base["app"]["locale"] or "zh").strip().lower()
    base["app"]["locale"] = locale if locale in {"zh", "en"} else "zh"
    appearance = str(app_in.get("appearance") or base["app"]["appearance"] or "system").strip().lower()
    base["app"]["appearance"] = appearance if appearance in {"light", "dark", "system"} else "system"
    base["app"]["open_browser_on_start"] = bool(
        app_in.get("open_browser_on_start", base["app"]["open_browser_on_start"])
    )
    visit = app_in.get("last_today_visit_at")
    base["app"]["last_today_visit_at"] = str(visit).strip() if visit else None
    if "enabled" in kindle_in:
        base["kindle"]["enabled"] = bool(kindle_in["enabled"])
    if "send_to" in kindle_in:
        base["kindle"]["send_to"] = str(kindle_in.get("send_to") or "").strip()
    if "auto_ingest_enabled" in econ_in:
        base["economist"]["auto_ingest_enabled"] = bool(econ_in["auto_ingest_enabled"])
    if "auto_kindle_enabled" in econ_in:
        base["economist"]["auto_kindle_enabled"] = bool(econ_in["auto_kindle_enabled"])
    for key in ("last_synced_edition", "last_kindle_edition"):
        raw = econ_in.get(key)
        base["economist"][key] = str(raw).strip() if raw else None
    cold_in = data.get("cold_start") if isinstance(data.get("cold_start"), dict) else {}
    base["cold_start"]["onboarding_dismissed"] = bool(
        cold_in.get("onboarding_dismissed", base["cold_start"]["onboarding_dismissed"])
    )
    completed = cold_in.get("last_completed_at")
    base["cold_start"]["last_completed_at"] = str(completed).strip() if completed else None
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
    if "app" in sections and isinstance(sections["app"], dict):
        current["app"].update(sections["app"])
        if "open_browser_on_start" in sections["app"]:
            from on1y.desktop.launch_prefs import write_launch_prefs

            write_launch_prefs(
                open_browser_on_start=bool(current["app"]["open_browser_on_start"]),
            )
    if "cold_start" in sections and isinstance(sections["cold_start"], dict):
        current.setdefault("cold_start", _default_payload(user_id=uid)["cold_start"])
        current["cold_start"].update(sections["cold_start"])
    save_user_profile(current, user_id=uid)
    return current


def public_profile_view(user_id: int | None = None) -> dict[str, Any]:
    from on1y.desktop.launch_prefs import read_launch_prefs
    from on1y.desktop.windows_autostart import autostart_installed, is_windows

    profile = load_user_profile(user_id)
    integrations = profile.get("integrations") or {}
    llm = _llm_integration_defaults(user_id=user_id)
    smtp = _smtp_integration_defaults(user_id=user_id)
    cookies = integrations.get("cookies") if isinstance(integrations.get("cookies"), dict) else {}
    cookie_status = {}
    for platform, path_str in cookies.items():
        p = Path(str(path_str))
        cookie_status[platform] = {"path": str(p), "exists": p.is_file()}
    launch = read_launch_prefs()
    app = profile.get("app") if isinstance(profile.get("app"), dict) else {}
    return {
        "user_id": user_id if user_id is not None else get_effective_user_id(),
        "owner": profile.get("owner"),
        "app": {
            "locale": str(app.get("locale") or "zh"),
            "appearance": str(app.get("appearance") or "system"),
            "open_browser_on_start": bool(
                launch.get("open_browser_on_start", app.get("open_browser_on_start", True))
            ),
            "autostart_enabled": autostart_installed() if is_windows() else False,
            "autostart_supported": is_windows(),
        },
        "kindle": {
            "enabled": profile["kindle"]["enabled"],
            "send_to": profile["kindle"]["send_to"],
        },
        "economist": dict(profile["economist"]),
        "cold_start": dict(profile.get("cold_start") or {}),
        "integrations": {
            "cookies": cookie_status,
            "llm": {
                "base_url": llm.get("base_url"),
                "model": llm.get("model"),
                "api_key_configured": llm.get("api_key_configured"),
            },
            "smtp": smtp,
        },
    }


def economist_automation_enabled(profile: dict[str, Any] | None = None) -> bool:
    profile = profile or load_user_profile()
    settings = get_settings()
    if not settings.economist_hotlist_enabled:
        return False
    return bool(profile["economist"]["auto_ingest_enabled"])
