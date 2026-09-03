"""Persist per-user cookie JSON (file upload or clipboard import)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from on1y.auth.context import get_effective_user_id
from on1y.browser.cookies import load_cookie_file
from on1y.cookies.loader import PLATFORM_COOKIE_ATTR, extract_cookie_list, invalidate_cookie_sidecar
def verify_cookie_account(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from on1y.cookies.verify import verify_cookie_account as _verify_cookie_account
    return _verify_cookie_account(*args, **kwargs)
from on1y.user.paths import COOKIE_PLATFORMS, user_cookie_path


def _require_zlib_login_cookies(cookies: list[dict]) -> None:
    names = {str(c.get("name") or "").lower() for c in cookies}
    missing: list[str] = []
    if "remix_userid" not in names:
        missing.append("remix_userid")
    if "remix_userkey" not in names:
        missing.append("remix_userkey")
    if missing:
        raise ValueError(
            "Z-Library Cookie 缺少登录字段："
            + "、".join(missing)
            + "。请在已登录 z-lib 的页面用 Cookie-Editor 导出完整 JSON"
        )


def persist_user_cookie_payload(
    platform: str,
    data: dict[str, Any] | list[dict[str, Any]],
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    if platform not in COOKIE_PLATFORMS:
        raise ValueError(f"unknown platform: {platform}")
    cookies = extract_cookie_list(data)
    if not cookies:
        raise ValueError("no cookies in payload")
    if platform == "zlibrary":
        _require_zlib_login_cookies(cookies)
    uid = user_id if user_id is not None else get_effective_user_id()
    dest = user_cookie_path(uid, platform)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, dict) and "cookies" in data:
        from on1y.browser.cookies import normalize_storage_state

        payload = normalize_storage_state(data)
    else:
        payload = {"cookies": cookies, "origins": []}
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    invalidate_cookie_sidecar(dest)
    if uid == 1 and platform in PLATFORM_COOKIE_ATTR:
        from on1y.config import get_settings

        legacy = getattr(get_settings(), PLATFORM_COOKIE_ATTR[platform], None)
        if legacy and Path(legacy).is_file() and Path(legacy).resolve() != dest.resolve():
            invalidate_cookie_sidecar(Path(legacy))
            Path(legacy).unlink(missing_ok=True)
    _ = load_cookie_file(dest)
    from on1y.subscriptions.feeds_refresh import refresh_subscription_feeds_from_cookie

    account = verify_cookie_account(platform, user_id=uid, force=True)
    feeds_refresh: dict[str, Any] | None = None
    if platform in {"bilibili", "youtube", "zhihu"}:
        try:
            feeds_refresh = refresh_subscription_feeds_from_cookie(
                platform,
                user_id=uid,
            )
        except Exception as exc:
            feeds_refresh = {"platform": platform, "error": str(exc)}
    return {
        "platform": platform,
        "path": str(dest),
        "count": len(cookies),
        "account": account,
        "feeds_refresh": feeds_refresh,
    }
