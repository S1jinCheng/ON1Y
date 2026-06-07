"""Resolve outbound HTTP proxy for yt-dlp / httpx."""

from __future__ import annotations

import logging
import socket
from typing import Any
import httpx

from on1y.config import Settings, get_settings
from on1y.network.settings import load_file_settings

logger = logging.getLogger(__name__)

_COMMON_PROXY_PORTS = (7890, 7897, 10809, 1080, 8080)


def _normalize_proxy_url(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = f"http://{text}"
    return text


def detect_system_proxy() -> str | None:
    """Read Windows Internet Settings proxy (user-level)."""
    import sys

    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        server = str(server or "").strip()
        if not server:
            return None
        if "=" in server:
            # PAC-style map e.g. http=host:port;https=host:port — pick http
            for part in server.split(";"):
                part = part.strip()
                if part.lower().startswith("http="):
                    server = part.split("=", 1)[1].strip()
                    break
        return _normalize_proxy_url(server)
    except OSError:
        return None


def probe_common_proxies() -> str | None:
    """When system proxy is off, try common local Clash/V2Ray ports."""
    for port in _COMMON_PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.35):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue
    return None


def effective_ytdlp_proxy(*, settings: Settings | None = None, user_id: int | None = None) -> str | None:
    settings = settings or get_settings()
    prefs = load_file_settings(user_id=user_id)
    mode = str(prefs.get("proxy_mode") or "auto").strip().lower()
    manual = _normalize_proxy_url(str(prefs.get("manual_proxy") or ""))

    if mode == "off":
        return None
    if mode == "manual":
        return manual or _normalize_proxy_url(settings.ytdlp_proxy or "")

    # auto
    for candidate in (
        _normalize_proxy_url(settings.ytdlp_proxy or ""),
        detect_system_proxy(),
        probe_common_proxies(),
    ):
        if candidate:
            return candidate
    return None


def httpx_client_kwargs(*, settings: Settings | None = None, user_id: int | None = None) -> dict[str, Any]:
    proxy = effective_ytdlp_proxy(settings=settings, user_id=user_id)
    if not proxy:
        return {}
    return {"proxy": proxy}


def proxy_hint_message(*, settings: Settings | None = None, user_id: int | None = None) -> str:
    settings = settings or get_settings()
    proxy = effective_ytdlp_proxy(settings=settings, user_id=user_id)
    if proxy:
        return f"Proxy is set ({proxy}) but connection still failed."
    return (
        "YouTube may be unreachable from your network. "
        "Enable system proxy (Clash/V2Ray) or set a proxy in Settings → General → Network."
    )


def test_proxy_reachability(
    proxy_url: str | None,
    *,
    test_url: str = "https://www.youtube.com/generate_204",
    timeout: float = 8.0,
) -> dict[str, Any]:
    proxy = _normalize_proxy_url(proxy_url or "")
    if not proxy:
        return {"ok": False, "error": "no_proxy"}
    try:
        with httpx.Client(
            proxy=proxy,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "On1y/0.1"},
        ) as client:
            response = client.get(test_url)
        return {"ok": response.status_code < 500, "status_code": response.status_code, "proxy": proxy}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "proxy": proxy}
