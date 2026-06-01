"""Shared yt-dlp option builder (proxy, timeouts)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from on1y.config import get_settings
from on1y.cookies.loader import load_cookies_for_ytdlp
from on1y.extract.subtitles import DEFAULT_SUBTITLE_LANGS, parse_subtitle_langs


def build_ytdlp_opts(
    *,
    cookie_path: Path | None = None,
    cookies_required: bool | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Base options for subtitle-only extraction."""
    settings = get_settings()
    required = settings.require_login_cookies if cookies_required is None else cookies_required
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": settings.ytdlp_socket_timeout,
        "retries": settings.ytdlp_retries,
        "extractor_retries": settings.ytdlp_retries,
    }
    if settings.ytdlp_proxy:
        opts["proxy"] = settings.ytdlp_proxy
    if cookie_path is not None:
        netscape = load_cookies_for_ytdlp(cookie_path, required=required)
        if netscape is not None:
            opts["cookiefile"] = str(netscape)
    opts.update(overrides)
    return opts


def parse_subtitle_langs_from_settings() -> list[str]:
    from on1y.extract.subtitles import yt_dlp_subtitle_request_langs

    settings = get_settings()
    return yt_dlp_subtitle_request_langs(settings.ytdlp_sub_langs)


def proxy_hint() -> str:
    settings = get_settings()
    if settings.ytdlp_proxy:
        return f"Proxy is set ({settings.ytdlp_proxy}) but connection still failed."
    return (
        "WSL may not reach YouTube. Set ON1Y_YTDLP_PROXY in .env "
        "(e.g. http://127.0.0.1:7890) to match your VPN/clash on Windows."
    )
