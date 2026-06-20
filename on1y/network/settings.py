"""Per-user network settings (proxy mode) stored beside LLM settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from on1y.auth.context import get_effective_user_id
from on1y.config import get_settings

logger = logging.getLogger(__name__)

ProxyMode = Literal["auto", "manual", "off"]

_DEFAULT: dict[str, Any] = {
    "proxy_mode": "auto",
    "manual_proxy": "",
}


def settings_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    from on1y.user.paths import user_dir

    return user_dir(uid) / "network_settings.json"


def load_file_settings(*, user_id: int | None = None) -> dict[str, Any]:
    path = settings_file_path(user_id=user_id)
    if not path.is_file():
        return dict(_DEFAULT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(_DEFAULT)
    except json.JSONDecodeError:
        logger.warning("Invalid network settings file: %s", path)
        return dict(_DEFAULT)


def save_file_settings(
    *,
    proxy_mode: ProxyMode | None = None,
    manual_proxy: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    uid = user_id if user_id is not None else get_effective_user_id()
    path = settings_file_path(user_id=uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_file_settings(user_id=uid)
    if proxy_mode is not None:
        mode = str(proxy_mode).strip().lower()
        current["proxy_mode"] = mode if mode in {"auto", "manual", "off"} else "auto"
    if manual_proxy is not None:
        current["manual_proxy"] = str(manual_proxy or "").strip()
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from on1y.config import get_settings
    from on1y.network.proxy import clear_proxy_check_cache

    clear_proxy_check_cache()
    get_settings.cache_clear()
    return current


def public_settings_view(*, user_id: int | None = None) -> dict[str, Any]:
    from on1y.network.proxy import detect_system_proxy, probe_common_proxies
    from on1y.network.proxy import effective_ytdlp_proxy

    raw = load_file_settings(user_id=user_id)
    mode = str(raw.get("proxy_mode") or "auto").strip().lower()
    if mode not in {"auto", "manual", "off"}:
        mode = "auto"
    manual = str(raw.get("manual_proxy") or "").strip()
    env_proxy = (get_settings().ytdlp_proxy or "").strip()
    system_proxy = detect_system_proxy()
    probed = probe_common_proxies() if mode == "auto" and not system_proxy else None
    effective = effective_ytdlp_proxy(user_id=user_id)
    probed_ok = bool(probed and probed == effective)
    return {
        "proxy_mode": mode,
        "manual_proxy": manual,
        "env_proxy": env_proxy or None,
        "system_proxy": system_proxy,
        "probed_proxy": probed,
        "probed_proxy_usable": probed_ok if probed else None,
        "effective_proxy": effective,
        "restart_required": False,
    }
