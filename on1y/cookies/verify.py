"""Probe saved cookies against each platform's logged-in account API."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from on1y.config import Settings, get_settings
from on1y.cookies.loader import PLATFORM_COOKIE_ATTR, extract_cookie_list, load_cookie_file

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_verify_cache: dict[tuple[int, str, float], dict[str, Any]] = {}

_GOOGLE_LOGIN_NAMES = frozenset(
    {
        "__Secure-1PSID",
        "__Secure-3PSID",
        "SAPISID",
        "APISID",
        "SID",
        "HSID",
        "SSID",
    }
)
_VISITOR_ONLY_NAMES = frozenset(
    {
        "VISITOR_INFO1_LIVE",
        "VISITOR_PRIVACY_METADATA",
        "YSC",
        "PREF",
        "GPS",
    }
)


def _empty_account() -> dict[str, Any]:
    return {
        "valid": False,
        "account_id": None,
        "account_name": None,
        "avatar_url": None,
        "detail": None,
        "verified_at": None,
    }


def _cache_key(user_id: int, platform: str, cookie_path: Path) -> tuple[int, str, float]:
    mtime = cookie_path.stat().st_mtime if cookie_path.is_file() else 0.0
    return (user_id, platform, mtime)


def _get_cached(user_id: int, platform: str, cookie_path: Path) -> dict[str, Any] | None:
    key = _cache_key(user_id, platform, cookie_path)
    row = _verify_cache.get(key)
    if not row:
        return None
    verified_at = float(row.get("_cached_at") or 0)
    if time.monotonic() - verified_at > _CACHE_TTL_SECONDS:
        _verify_cache.pop(key, None)
        return None
    out = dict(row)
    out.pop("_cached_at", None)
    return out


def _set_cached(user_id: int, platform: str, cookie_path: Path, account: dict[str, Any]) -> None:
    key = _cache_key(user_id, platform, cookie_path)
    payload = dict(account)
    payload["_cached_at"] = time.monotonic()
    _verify_cache[key] = payload


def verify_cookie_account(
    platform: str,
    *,
    user_id: int,
    settings: Settings | None = None,
    force: bool = False,
    quick: bool = False,
) -> dict[str, Any]:
    """Return account probe for *platform*; uses short-lived cache keyed by cookie mtime."""
    settings = settings or get_settings()
    from on1y.user.paths import COOKIE_PLATFORMS

    if platform not in COOKIE_PLATFORMS:
        return {**_empty_account(), "detail": f"unknown platform: {platform}"}

    from on1y.cookies.loader import resolve_cookie_path

    path = resolve_cookie_path(platform, settings, user_id=user_id)
    if not path.is_file():
        return _empty_account()

    if not force:
        cached = _get_cached(user_id, platform, path)
        if cached is not None:
            return cached

    try:
        data = load_cookie_file(path)
        cookies = extract_cookie_list(data)
    except Exception as exc:
        account = {**_empty_account(), "detail": str(exc)}
        if not force:
            _set_cached(user_id, platform, path, account)
        return account

    if not cookies:
        account = {**_empty_account(), "detail": "Cookie 文件为空"}
        if not force:
            _set_cached(user_id, platform, path, account)
        return account

    try:
        if platform == "bilibili":
            account = _verify_bilibili(path, settings=settings)
        elif platform == "zhihu":
            account = _verify_zhihu(path, settings=settings, quick=quick)
        elif platform == "youtube":
            account = _verify_youtube(
                cookies,
                settings=settings,
                cookie_path=path,
                user_id=user_id,
                quick=quick,
            )
        elif platform == "xiaohongshu":
            account = {
                **_empty_account(),
                "valid": None,
                "detail": "暂不支持自动验证，导入后请试同步",
            }
        elif platform == "twitter":
            account = _verify_twitter(path, settings=settings)
        elif platform == "zlibrary":
            account = _verify_zlibrary(user_id=user_id, settings=settings)
        else:
            account = {**_empty_account(), "detail": "unsupported platform"}
    except Exception as exc:
        logger.debug("Cookie verify failed for %s: %s", platform, exc)
        account = {**_empty_account(), "detail": str(exc)}

    import datetime as dt

    account["verified_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if not force:
        _set_cached(user_id, platform, path, account)
    return account


def _verify_zlibrary(*, user_id: int, settings: Settings) -> dict[str, Any]:
    from on1y.books.zlib_eapi import ZlibEapiClient
    from on1y.books.zlib_session import load_zlib_session

    session = load_zlib_session(user_id)
    if not session:
        return {
            **_empty_account(),
            "detail": "缺少 remix_userid / remix_userkey Cookie",
        }
    client = ZlibEapiClient(session)
    if not client.verify():
        return {
            **_empty_account(),
            "detail": "Z-Library 登录无效，请重新导出 Cookie",
        }
    profile = client.profile()
    user = profile.get("user") if isinstance(profile.get("user"), dict) else {}
    name = str(user.get("name") or user.get("email") or "Z-Library").strip()
    return {
        "valid": True,
        "account_id": str(user.get("id") or "") or None,
        "account_name": name,
        "avatar_url": None,
        "detail": None,
        "verified_at": None,
    }


def _verify_bilibili(cookie_path: Path, *, settings: Settings) -> dict[str, Any]:
    from on1y.ingestion.bilibili_api import fetch_bilibili_me, fetch_bilibili_up_face

    me = fetch_bilibili_me(cookie_path=cookie_path, settings=settings)
    mid = str(me.get("mid") or "").strip()
    name = str(me.get("name") or mid).strip()
    face = str(me.get("face") or "").strip()
    if not face and mid:
        face = fetch_bilibili_up_face(mid, cookie_path=cookie_path, settings=settings)
    return {
        "valid": True,
        "account_id": mid or None,
        "account_name": name or None,
        "avatar_url": face or None,
        "detail": None,
        "verified_at": None,
    }


def _verify_twitter(cookie_path: Path, *, settings: Settings) -> dict[str, Any]:
    from on1y.browser.twitter_playwright import verify_twitter_session

    try:
        return verify_twitter_session(cookie_path, settings=settings)
    except Exception as exc:
        return {**_empty_account(), "detail": str(exc)}


def _verify_zhihu(cookie_path: Path, *, settings: Settings, quick: bool = False) -> dict[str, Any]:
    from on1y.ingestion.zhihu_follow_list import fetch_zhihu_me

    last_exc: Exception | None = None
    me: dict[str, Any] | None = None
    attempts = 1 if quick else 2
    for attempt in range(attempts):
        try:
            me = fetch_zhihu_me(cookie_path=cookie_path, settings=settings)
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            time.sleep(0.35)
    if me is None:
        raise last_exc or RuntimeError("zhihu verify failed")
    name = str(me.get("name") or me.get("url_token") or "").strip()
    avatar = str(me.get("avatar_url") or "").strip()
    token = str(me.get("url_token") or me.get("id") or "").strip()
    return {
        "valid": True,
        "account_id": token or None,
        "account_name": name or None,
        "avatar_url": avatar or None,
        "detail": None,
        "verified_at": None,
    }


def _youtube_login_cookie_check(cookies: list[dict[str, Any]]) -> tuple[bool, str]:
    names: set[str] = set()
    for row in cookies:
        domain = str(row.get("domain") or "")
        if "google.com" not in domain and "youtube.com" not in domain:
            continue
        name = str(row.get("name") or "").strip()
        if name:
            names.add(name)
    if not names:
        return False, "未找到 YouTube / Google 域 Cookie"
    if names <= _VISITOR_ONLY_NAMES:
        return False, "访客 Cookie：请在已登录的 youtube.com 页面重新导出"
    if not names & _GOOGLE_LOGIN_NAMES:
        return False, "缺少 Google 登录 Cookie（如 __Secure-1PSID），请重新登录后导出"
    return True, ""


def _youtube_verify_failure_detail(*, settings: Settings) -> str:
    from on1y.network.proxy import effective_ytdlp_proxy

    proxy = effective_ytdlp_proxy(settings=settings)
    if proxy:
        return (
            f"无法读取订阅频道：当前代理 {proxy} 访问 YouTube 可能异常（SSL/连接失败）。"
            "可在设置 → 网络将代理改为「关闭」或「手动」并确认 Clash 端口可用，"
            "或维护 config/youtube_channels.txt 手动添加频道。"
        )
    return "无法读取订阅频道：请检查 Cookie 是否完整，或维护 config/youtube_channels.txt 手动添加频道。"


def _verify_youtube(
    cookies: list[dict[str, Any]],
    *,
    settings: Settings,
    cookie_path: Path,
    user_id: int,
    quick: bool = False,
) -> dict[str, Any]:
    ok, hint = _youtube_login_cookie_check(cookies)
    if not ok:
        return {**_empty_account(), "detail": hint}

    from on1y.utils.youtube_account import fetch_youtube_account_profile

    profile = fetch_youtube_account_profile(cookie_path=cookie_path, settings=settings)
    account_id = profile.get("account_id")
    account_name = str(profile.get("account_name") or "").strip() or "YouTube"
    avatar_url = profile.get("avatar_url")

    if quick:
        detail = "登录 Cookie 有效"
        if account_name and account_name != "YouTube":
            detail = f"已登录 · {account_name}"
        return {
            "valid": True,
            "account_id": account_id,
            "account_name": account_name,
            "avatar_url": avatar_url,
            "detail": detail,
            "verified_at": None,
        }

    from on1y.ingestion.youtube_feeds import channels_from_ytdlp

    rows = channels_from_ytdlp(
        max_channels=8,
        settings=settings,
        cookie_path=cookie_path,
        user_id=user_id,
    )
    if not rows:
        if account_id or avatar_url or (account_name and account_name != "YouTube"):
            return {
                "valid": True,
                "account_id": account_id,
                "account_name": account_name,
                "avatar_url": avatar_url,
                "detail": "已识别账号，但无法读取订阅频道（请检查代理或 Cookie）",
                "verified_at": None,
            }
        return {
            **_empty_account(),
            "detail": _youtube_verify_failure_detail(settings=settings),
        }
    count = len(rows)
    detail = f"已识别 {count} 个订阅频道"
    if account_name and account_name != "YouTube":
        detail = f"{account_name} · {detail}"
    return {
        "valid": True,
        "account_id": account_id,
        "account_name": account_name,
        "avatar_url": avatar_url,
        "detail": detail,
        "verified_at": None,
    }
