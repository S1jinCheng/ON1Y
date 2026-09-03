"""Orchestrate QR cookie login (Bilibili only)."""

from __future__ import annotations

import logging
from typing import Any

from on1y.cookies.import_user import persist_user_cookie_payload
from on1y.cookies.qr_login.bilibili import poll_bilibili_qr, start_bilibili_qr
from on1y.cookies.qr_login.cookies_convert import httpx_client_to_storage_state
from on1y.cookies.qr_login.session_store import (
    cancel_session,
    create_session,
    get_session,
    pop_session,
)

logger = logging.getLogger(__name__)

QR_LOGIN_PLATFORMS = frozenset({"bilibili"})

_HINTS = {
    "bilibili": {
        "zh": "打开哔哩哔哩 App → 扫一扫 → 扫描下方二维码 → 在手机上确认登录",
        "en": "Open the Bilibili app → Scan → scan the QR code below → confirm on your phone",
    },
}


def _hint(platform: str, *, locale: str = "zh") -> str:
    entry = _HINTS.get(platform, {})
    return entry.get(locale) or entry.get("zh") or ""


def start_qr_login(platform: str, *, user_id: int, locale: str = "zh") -> dict[str, Any]:
    if platform not in QR_LOGIN_PLATFORMS:
        raise ValueError(f"QR login not supported for platform: {platform}")

    if platform == "bilibili":
        holder = start_bilibili_qr()
        session = create_session(
            platform=platform,
            user_id=user_id,
            qr_content=holder.qr_url,
            hint=_hint(platform, locale=locale),
            method="app_scan",
            holder=holder,
        )
        return _session_view(session)

    raise ValueError(f"unsupported platform: {platform}")


def poll_qr_login(session_id: str, *, user_id: int) -> dict[str, Any]:
    session = get_session(session_id)
    if session is None:
        return {"status": "expired", "message": "登录会话已过期，请重新扫码"}
    if session.user_id != user_id:
        return {"status": "error", "message": "invalid session"}
    if session.is_expired():
        session.status = "expired"
        session.message = "二维码已过期"
        pop_session(session_id)
        session.close()
        return _session_view(session)

    if session.status == "success":
        return _session_view(session)

    platform = session.platform
    holder = session._holder

    try:
        if platform == "bilibili":
            status, msg = poll_bilibili_qr(holder)
        else:
            status, msg = "error", "unsupported platform"
    except Exception as exc:
        logger.exception("QR login poll failed platform=%s", platform)
        session.status = "error"
        session.message = str(exc)
        return _session_view(session)

    session.status = status
    session.message = msg

    if status == "success" and session.import_result is None:
        try:
            state = httpx_client_to_storage_state(holder.client)
            result = persist_user_cookie_payload(platform, state, user_id=user_id)
            session.import_result = result
            session.account = result.get("account")
        except Exception as exc:
            logger.exception("Failed to persist cookies after QR login")
            session.status = "error"
            session.message = str(exc)
        finally:
            pop_session(session_id)
            session.close()
    elif status in {"expired", "error"}:
        pop_session(session_id)
        session.close()

    return _session_view(session)


def cancel_qr_login(session_id: str, *, user_id: int) -> dict[str, Any]:
    session = get_session(session_id)
    if session is None:
        return {"cancelled": False}
    if session.user_id != user_id:
        return {"cancelled": False}
    cancel_session(session_id)
    return {"cancelled": True}


def _session_view(session: Any) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "platform": session.platform,
        "method": session.method,
        "status": session.status,
        "qr_content": session.qr_content,
        "hint": session.hint,
        "message": session.message,
        "account": session.account,
        "import_result": (
            {
                "platform": session.import_result.get("platform"),
                "count": session.import_result.get("count"),
                "account": session.import_result.get("account"),
            }
            if isinstance(session.import_result, dict)
            else None
        ),
    }
