"""Telegram QR login sessions (Telethon qr_login, background wait loop)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from on1y.telegram.client import TelegramClientError, session_authorized
from on1y.telegram.credentials import api_credentials_configured
from on1y.telegram.settings import load_settings
from on1y.telegram.state import load_state, save_state

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sessions: dict[str, "QrAuthSession"] = {}
_by_user: dict[int, str] = {}


@dataclass
class QrAuthSession:
    session_id: str
    user_id: int
    status: str = "starting"
    url: str | None = None
    message: str | None = None
    _password_value: str | None = field(default=None, repr=False)
    _password_event: Any = field(default=None, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _client: Any = field(default=None, repr=False)
    _qr_login: Any = field(default=None, repr=False)


def _public_view(session: QrAuthSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "status": session.status,
        "url": session.url,
        "message": session.message,
    }


def cancel_user_qr_sessions(*, user_id: int) -> None:
    """Disconnect any in-progress QR login holding the Telethon session."""
    with _lock:
        session_id = _by_user.get(user_id)
        if not session_id:
            return
        session = _sessions.get(session_id)
        if session is None:
            _by_user.pop(user_id, None)
            return
        session.status = "cancelled"
        loop = session._loop
        event = session._password_event
    if event is not None and loop is not None:
        loop.call_soon_threadsafe(event.set)
    if loop is not None and session._client is not None:
        try:
            asyncio.run_coroutine_threadsafe(_disconnect_client(session), loop).result(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    _cleanup_session(session_id)


def _cleanup_session(session_id: str) -> None:
    with _lock:
        session = _sessions.pop(session_id, None)
        if session is not None:
            _by_user.pop(session.user_id, None)


async def _disconnect_client(session: QrAuthSession) -> None:
    client = session._client
    session._client = None
    if client is None:
        return
    try:
        if client.is_connected():
            await client.disconnect()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Telegram QR client disconnect: %s", exc)


async def _sync_qr_export(client: Any, qr_login: Any) -> None:
    """Handle DC migration and reject already-authorized exports before showing QR."""
    from telethon.tl import functions, types

    resp = qr_login._resp
    if isinstance(resp, types.auth.LoginTokenMigrateTo):
        await client._switch_dc(resp.dc_id)
        qr_login._resp = await client(functions.auth.ImportLoginTokenRequest(resp.token))
        resp = qr_login._resp
    if isinstance(resp, types.auth.LoginTokenSuccess):
        raise TelegramClientError("Telegram session is already authorized")


async def _qr_flow(session: QrAuthSession) -> None:
    from datetime import UTC, datetime

    from telethon.errors import SessionPasswordNeededError

    from on1y.telegram.client import _agent_log, _build_client

    session._password_event = asyncio.Event()
    try:
        client = await _build_client(user_id=session.user_id)
        session._client = client
        if await client.is_user_authorized():
            await client.log_out()
            await client.disconnect()
            client = await _build_client(user_id=session.user_id)
            session._client = client
        qr_login = await client.qr_login()
        session._qr_login = qr_login
        await _sync_qr_export(client, qr_login)
        session.url = qr_login.url
        session.status = "pending"
        # #region agent log
        _agent_log(
            "F",
            "qr_auth.py:_qr_flow",
            "qr url ready",
            {
                "session_id": session.session_id,
                "url_prefix": (session.url or "")[:32],
                "url_len": len(session.url or ""),
            },
        )
        # #endregion

        while session.status == "pending":
            try:
                expires = qr_login.expires
                now = datetime.now(tz=UTC)
                timeout = (expires - now).total_seconds() - 2.0
                timeout = max(5.0, min(25.0, timeout))
                await qr_login.wait(timeout=timeout)
                session.status = "authorized"
                # #region agent log
                _agent_log(
                    "B",
                    "qr_auth.py:_qr_flow",
                    "qr wait authorized",
                    {"session_id": session.session_id, "user_id": session.user_id},
                )
                # #endregion
                break
            except SessionPasswordNeededError:
                session.status = "needs_password"
                # #region agent log
                _agent_log(
                    "B",
                    "qr_auth.py:_qr_flow",
                    "qr needs password",
                    {"session_id": session.session_id},
                )
                # #endregion
                await session._password_event.wait()
                pwd = (session._password_value or "").strip()
                if not pwd or session.status == "cancelled":
                    session.status = "cancelled"
                    await _disconnect_client(session)
                    return
                await client.sign_in(password=pwd)
                session.status = "authorized"
                break
            except asyncio.TimeoutError:
                await qr_login.recreate()
                await _sync_qr_export(client, qr_login)
                session.url = qr_login.url
                # #region agent log
                _agent_log(
                    "B",
                    "qr_auth.py:_qr_flow",
                    "qr recreated",
                    {"session_id": session.session_id, "url_len": len(session.url or "")},
                )
                # #endregion
            except Exception as exc:  # noqa: BLE001
                session.status = "error"
                session.message = str(exc)
                # #region agent log
                _agent_log(
                    "B",
                    "qr_auth.py:_qr_flow",
                    "qr error",
                    {"session_id": session.session_id, "error": str(exc)},
                )
                # #endregion
                await _disconnect_client(session)
                return

        if session.status == "authorized":
            state = load_state(user_id=session.user_id)
            state.pop("auth_pending", None)
            save_state(state, user_id=session.user_id)
            await _disconnect_client(session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Telegram QR login failed")
        session.status = "error"
        session.message = str(exc)
        await _disconnect_client(session)


def _run_worker(session: QrAuthSession) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    session._loop = loop
    try:
        loop.run_until_complete(_qr_flow(session))
    finally:
        loop.close()
        session._loop = None
        if session.status in {"authorized", "error", "cancelled", "expired"}:
            _cleanup_session(session.session_id)


def start_qr_login(*, user_id: int, force: bool = False) -> dict[str, Any]:
    from on1y.telegram.client import _agent_log

    if force and session_authorized(user_id=user_id):
        from on1y.telegram.client import logout_session

        logout_session(user_id=user_id)
    elif session_authorized(user_id=user_id):
        # #region agent log
        _agent_log("D", "qr_auth.py:start_qr_login", "short-circuit authorized", {"user_id": user_id})
        # #endregion
        return {"session_id": "", "status": "authorized", "url": None, "message": None}

    cfg = load_settings(user_id=user_id)
    if not api_credentials_configured(cfg):
        raise TelegramClientError(
            "Telegram API credentials are not configured. "
            "Set ON1Y_TELEGRAM_API_ID and ON1Y_TELEGRAM_API_HASH in .env."
        )

    with _lock:
        existing = _by_user.get(user_id)
        if existing:
            old = _sessions.get(existing)
            if old is not None and old.status in {"starting", "pending", "needs_password"}:
                old.status = "cancelled"
                if old._loop is not None and old._client is not None:
                    try:
                        asyncio.run_coroutine_threadsafe(_disconnect_client(old), old._loop)
                    except Exception:  # noqa: BLE001
                        pass

        session_id = uuid.uuid4().hex
        session = QrAuthSession(session_id=session_id, user_id=user_id)
        _sessions[session_id] = session
        _by_user[user_id] = session_id

    thread = threading.Thread(target=_run_worker, args=(session,), daemon=True)
    session._thread = thread
    thread.start()

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        with _lock:
            if session.url:
                view = _public_view(session)
                break
            if session.status in {"error", "cancelled"}:
                raise TelegramClientError(session.message or "QR login failed")
            view = _public_view(session)
        time.sleep(0.1)
    else:
        with _lock:
            view = _public_view(session)

    if view.get("url"):
        # #region agent log
        _agent_log(
            "F",
            "qr_auth.py:start_qr_login",
            "returning qr session",
            {
                "session_id": view.get("session_id"),
                "status": view.get("status"),
                "url_prefix": str(view.get("url") or "")[:32],
                "url_len": len(str(view.get("url") or "")),
            },
        )
        # #endregion
    return view


def poll_qr_login(session_id: str, *, user_id: int) -> dict[str, Any]:
    from on1y.telegram.client import _agent_log

    with _lock:
        session = _sessions.get(session_id)
        if session is None:
            if session_authorized(user_id=user_id):
                return {"session_id": session_id, "status": "authorized", "url": None, "message": None}
            raise TelegramClientError("QR login session not found or expired")
        if session.user_id != user_id:
            raise TelegramClientError("QR login session not found or expired")
        view = _public_view(session)
    if view.get("status") != "pending":
        # #region agent log
        _agent_log(
            "B",
            "qr_auth.py:poll_qr_login",
            "poll",
            {
                "session_id": session_id,
                "status": view.get("status"),
                "has_url": bool(view.get("url")),
                "url_prefix": str(view.get("url") or "")[:32],
            },
        )
        # #endregion
    return view


def cancel_qr_login(session_id: str, *, user_id: int) -> dict[str, Any]:
    with _lock:
        session = _sessions.get(session_id)
        if session is None or session.user_id != user_id:
            return {"session_id": session_id, "status": "cancelled", "url": None, "message": None}
        session.status = "cancelled"
        loop = session._loop
        event = session._password_event
    if event is not None and loop is not None:
        loop.call_soon_threadsafe(event.set)
    if loop is not None and session._client is not None:
        try:
            asyncio.run_coroutine_threadsafe(_disconnect_client(session), loop)
        except Exception:  # noqa: BLE001
            pass
    _cleanup_session(session_id)
    return {"session_id": session_id, "status": "cancelled", "url": None, "message": None}


def complete_qr_password(session_id: str, *, password: str, user_id: int) -> dict[str, Any]:
    pwd = (password or "").strip()
    if not pwd:
        raise TelegramClientError("2FA password is required")

    with _lock:
        session = _sessions.get(session_id)
        if session is None or session.user_id != user_id:
            raise TelegramClientError("QR login session not found or expired")
        if session.status != "needs_password":
            raise TelegramClientError("QR login is not waiting for a password")
        loop = session._loop
        if loop is None:
            raise TelegramClientError("QR login session is no longer active")
        session._password_value = pwd

    event = session._password_event
    if event is not None:
        loop.call_soon_threadsafe(event.set)

    end = time.monotonic() + 60
    while time.monotonic() < end:
        with _lock:
            current = _sessions.get(session_id)
            if current is None:
                break
            if current.status == "authorized":
                return {"ok": True, "authorized": session_authorized(user_id=user_id)}
            if current.status in {"error", "cancelled"}:
                raise TelegramClientError(current.message or "QR login failed")
        time.sleep(0.3)

    raise TelegramClientError("QR login timed out waiting for password verification")
