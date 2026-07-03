"""Telegram Client API (Telethon) — direct local sync without Desktop export."""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from on1y.auth.context import get_effective_user_id
from on1y.telegram.credentials import api_credentials_configured, resolve_api_credentials
from on1y.telegram.settings import TelegramSettings, load_settings
from on1y.telegram.state import load_state, save_state
from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)

_DEBUG_LOG = Path(__file__).resolve().parents[2] / "debug-3ec0ad.log"


def _agent_log(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    # #region agent log
    try:
        import json

        payload = {
            "sessionId": "3ec0ad",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with _DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion


class TelegramClientError(Exception):
    pass


class TelegramAuthRequired(TelegramClientError):
    pass


def session_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    return user_dir(uid) / "telegram"


def avatar_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    return user_dir(uid) / "telegram_avatar.jpg"


def session_authorized(*, user_id: int | None = None) -> bool:
    base = session_path(user_id=user_id)
    return base.with_suffix(".session").is_file() or Path(f"{base}.session").is_file()


def client_configured(cfg: TelegramSettings) -> bool:
    return bool(api_credentials_configured(cfg) and cfg.sync_chat_ids)


def _require_telethon():
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError

        return TelegramClient, SessionPasswordNeededError
    except ImportError as exc:
        raise TelegramClientError(
            "Telethon is not installed. Run: pip install telethon"
        ) from exc


def _proxy_tuple(*, user_id: int | None) -> tuple | None:
    from on1y.network.proxy import effective_telegram_proxy

    raw = (effective_telegram_proxy(user_id=user_id) or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return None
    try:
        import python_socks  # noqa: F401
    except ImportError as exc:
        raise TelegramClientError(
            "Telegram proxy is configured but python-socks is not installed. "
            "Run: pip install \"python-socks[asyncio]\""
        ) from exc
    scheme = (parsed.scheme or "http").lower()
    if scheme.startswith("socks"):
        return ("socks5", host, port)
    return ("http", host, port)


def _run(coro, *, timeout: float = 60.0):
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def _unlink_path(path: Path, *, retries: int = 8, delay: float = 0.25) -> bool:
    if not path.is_file():
        return False
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            path.unlink()
            return True
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            time.sleep(delay * (attempt + 1))
    if last_error is not None:
        stamp = int(time.time())
        pending = path.with_name(f"{path.name}.pending-delete-{stamp}")
        try:
            path.rename(pending)
            pending.unlink(missing_ok=True)
            return True
        except OSError:
            raise last_error from None
    return False


async def _build_client(*, user_id: int | None) -> Any:
    TelegramClient, _ = _require_telethon()
    cfg = load_settings(user_id=user_id)
    creds = resolve_api_credentials(cfg)
    if not creds:
        raise TelegramClientError(
            "Telegram API credentials are not configured. "
            "Set ON1Y_TELEGRAM_API_ID and ON1Y_TELEGRAM_API_HASH in .env."
        )
    api_id, api_hash = creds
    proxy = _proxy_tuple(user_id=user_id)
    try:
        import python_socks as _ps  # noqa: F401

        has_python_socks = True
    except ImportError:
        has_python_socks = False
    # #region agent log
    _agent_log(
        "A",
        "client.py:_build_client",
        "building telethon client",
        {
            "user_id": user_id,
            "proxy_kind": proxy[0] if proxy else None,
            "proxy_host": proxy[1] if proxy else None,
            "has_python_socks": has_python_socks,
        },
    )
    # #endregion
    client = TelegramClient(
        str(session_path(user_id=user_id)),
        int(api_id),
        api_hash,
        proxy=proxy,
    )
    await client.connect()
    return client


def send_login_code(*, phone: str, user_id: int | None = None) -> dict[str, Any]:
    phone_text = (phone or "").strip()
    if not phone_text:
        raise TelegramClientError("phone is required")

    async def _send() -> dict[str, Any]:
        client = await _build_client(user_id=user_id)
        try:
            result = await client.send_code_request(phone_text)
            state = load_state(user_id=user_id)
            state["auth_pending"] = {
                "phone": phone_text,
                "phone_code_hash": result.phone_code_hash,
            }
            save_state(state, user_id=user_id)
            return {"phone": phone_text, "sent": True}
        finally:
            await client.disconnect()

    return _run(_send())


def sign_in(
    *,
    phone: str,
    code: str,
    password: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    phone_text = (phone or "").strip()
    code_text = (code or "").strip()
    if not phone_text or not code_text:
        raise TelegramClientError("phone and code are required")

    _, SessionPasswordNeededError = _require_telethon()
    state = load_state(user_id=user_id)
    pending = state.get("auth_pending") if isinstance(state.get("auth_pending"), dict) else {}
    phone_code_hash = str(pending.get("phone_code_hash") or "").strip()
    if not phone_code_hash:
        raise TelegramClientError("call send-code first")

    async def _sign_in() -> dict[str, Any]:
        client = await _build_client(user_id=user_id)
        try:
            try:
                await client.sign_in(
                    phone=phone_text,
                    code=code_text,
                    phone_code_hash=phone_code_hash,
                )
            except SessionPasswordNeededError:
                pwd = (password or "").strip()
                if not pwd:
                    return {"ok": False, "needs_password": True}
                await client.sign_in(password=pwd)
            state2 = load_state(user_id=user_id)
            state2.pop("auth_pending", None)
            save_state(state2, user_id=user_id)
            return {"ok": True, "authorized": await client.is_user_authorized()}
        finally:
            await client.disconnect()

    return _run(_sign_in())


def _empty_account(*, detail: str | None = None) -> dict[str, Any]:
    return {
        "valid": False,
        "account_id": None,
        "account_name": None,
        "username": None,
        "avatar_url": None,
        "detail": detail,
        "verified_at": None,
    }


def _display_name(entity: Any) -> str:
    first = str(getattr(entity, "first_name", "") or "").strip()
    last = str(getattr(entity, "last_name", "") or "").strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    username = str(getattr(entity, "username", "") or "").strip()
    if username:
        return f"@{username}"
    return str(getattr(entity, "id", "") or "")


def get_account_info(*, user_id: int | None = None, refresh_avatar: bool = True) -> dict[str, Any]:
    if not session_authorized(user_id=user_id):
        return _empty_account(detail="not signed in")

    async def _fetch() -> dict[str, Any]:
        from datetime import UTC, datetime

        client = await _build_client(user_id=user_id)
        try:
            if not await client.is_user_authorized():
                return _empty_account(detail="session expired")
            me = await client.get_me()
            if me is None:
                return _empty_account(detail="account unavailable")
            avatar_url: str | None = None
            avatar_path = avatar_file_path(user_id=user_id)
            if refresh_avatar:
                try:
                    saved = await client.download_profile_photo(me, file=str(avatar_path))
                    # #region agent log
                    _agent_log(
                        "E",
                        "client.py:get_account_info",
                        "avatar download",
                        {
                            "user_id": user_id,
                            "saved": bool(saved),
                            "file_exists": avatar_path.is_file(),
                        },
                    )
                    # #endregion
                    if not saved and avatar_path.is_file():
                        avatar_path.unlink(missing_ok=True)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Telegram avatar download failed: %s", exc)
            if avatar_path.is_file():
                avatar_url = "/api/telegram/account/avatar"
            username = str(getattr(me, "username", "") or "").strip() or None
            verified_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            return {
                "valid": True,
                "account_id": str(getattr(me, "id", "") or ""),
                "account_name": _display_name(me),
                "username": username,
                "avatar_url": avatar_url,
                "detail": None,
                "verified_at": verified_at,
            }
        finally:
            await client.disconnect()

    try:
        return _run(_fetch(), timeout=45.0)
    except asyncio.TimeoutError:
        return _empty_account(detail="Telegram request timed out")
    except TelegramAuthRequired:
        return _empty_account(detail="not signed in")
    except TelegramClientError as exc:
        return _empty_account(detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram account info failed: %s", exc)
        return _empty_account(detail=str(exc))


def logout_session(*, user_id: int | None = None) -> dict[str, Any]:
    from on1y.telegram.qr_auth import cancel_user_qr_sessions

    uid = user_id if user_id is not None else get_effective_user_id()
    cancel_user_qr_sessions(user_id=uid)
    time.sleep(0.15)

    if session_authorized(user_id=uid):

        async def _remote_logout() -> None:
            client = await _build_client(user_id=uid)
            try:
                await client.log_out()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Telegram log_out: %s", exc)
            finally:
                await client.disconnect()

        try:
            _run(_remote_logout(), timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram remote logout failed: %s", exc)
        time.sleep(0.2)
        gc.collect()

    base = session_path(user_id=uid)
    removed = False
    errors: list[str] = []
    for candidate in (
        base.with_suffix(".session"),
        Path(f"{base}.session"),
        Path(f"{base}.session-journal"),
        avatar_file_path(user_id=uid),
    ):
        if not candidate.is_file():
            continue
        try:
            if _unlink_path(candidate):
                removed = True
        except OSError as exc:
            errors.append(f"{candidate.name}: {exc}")

    state = load_state(user_id=uid)
    state.pop("auth_pending", None)
    save_state(state, user_id=uid)

    still_authorized = session_authorized(user_id=uid)
    if errors and still_authorized:
        raise TelegramClientError(
            "Could not remove Telegram session file (still in use). "
            "Stop any Telegram login dialog, wait a few seconds, and try again."
        )
    return {
        "ok": True,
        "logged_out": removed or not still_authorized,
    }


def list_dialogs(*, user_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if not session_authorized(user_id=user_id):
        raise TelegramAuthRequired("Telegram session not authorized")

    async def _list() -> list[dict[str, Any]]:
        from telethon.tl.types import Channel, Chat, User

        client = await _build_client(user_id=user_id)
        try:
            if not await client.is_user_authorized():
                raise TelegramAuthRequired("Telegram session not authorized")
            rows: list[dict[str, Any]] = []
            async for dialog in client.iter_dialogs(limit=max(1, limit)):
                entity = dialog.entity
                chat_id = str(getattr(entity, "id", "") or "")
                if not chat_id:
                    continue
                if isinstance(entity, User):
                    chat_type = "personal_chat"
                    title = dialog.name or chat_id
                elif isinstance(entity, Chat):
                    chat_type = "private_group"
                    title = dialog.name or chat_id
                elif isinstance(entity, Channel):
                    if not getattr(entity, "megagroup", False):
                        continue
                    chat_type = "supergroup"
                    title = dialog.name or chat_id
                else:
                    chat_type = "unknown"
                    title = dialog.name or chat_id
                rows.append(
                    {
                        "chat_id": chat_id,
                        "title": title,
                        "chat_type": chat_type,
                        "unread_count": int(dialog.unread_count or 0),
                    }
                )
            return rows
        finally:
            await client.disconnect()

    return _run(_list())


def _entity_chat_type(entity: Any) -> str:
    from telethon.tl.types import Channel, Chat, User

    if isinstance(entity, User):
        return "personal_chat"
    if isinstance(entity, Chat):
        return "private_group"
    if isinstance(entity, Channel):
        return "supergroup" if getattr(entity, "megagroup", False) else "channel"
    return "unknown"


def _message_from_telethon(
    msg: Any,
    *,
    chat_id: str,
    contact: str,
    chat_type: str,
) -> Any | None:
    from on1y.ingestion.telegram_import import TelegramMessage

    if msg is None or getattr(msg, "action", None):
        return None
    text = str(getattr(msg, "message", "") or "").strip()
    kind = "text"
    if getattr(msg, "photo", None):
        kind = "photo"
    elif getattr(msg, "sticker", None):
        kind = "sticker"
    elif getattr(msg, "voice", None):
        kind = "voice_message"
    elif getattr(msg, "video", None):
        kind = "video_file"
    elif getattr(msg, "document", None):
        kind = "file"
    if kind == "text" and not text:
        return None
    sender = ""
    sender_entity = getattr(msg, "sender", None)
    if sender_entity is not None:
        first = str(getattr(sender_entity, "first_name", "") or "").strip()
        last = str(getattr(sender_entity, "last_name", "") or "").strip()
        sender = f"{first} {last}".strip() or str(getattr(sender_entity, "title", "") or "").strip()
    if not sender:
        sender = "我" if getattr(msg, "out", False) else contact
    ts = float(msg.date.timestamp()) if getattr(msg, "date", None) else 0.0
    if ts <= 0:
        return None
    return TelegramMessage(
        chat_id=chat_id,
        contact=contact,
        chat_type=chat_type,
        sender=sender,
        timestamp=ts,
        kind=kind,
        content=text,
        is_self=bool(getattr(msg, "out", False)),
    )


def fetch_incremental_messages(
    cfg: TelegramSettings,
    *,
    user_id: int | None = None,
    watermark_by_chat: dict[str, float],
    per_chat_limit: int = 500,
) -> dict[str, list[Any]]:
    """Pull new messages from configured chats since timestamp watermarks."""
    if not session_authorized(user_id=user_id):
        raise TelegramAuthRequired("Telegram session not authorized")
    chat_ids = [str(x).strip() for x in (cfg.sync_chat_ids or []) if str(x).strip()]
    if not chat_ids:
        return {}

    async def _fetch() -> dict[str, list[Any]]:
        client = await _build_client(user_id=user_id)
        out: dict[str, list[Any]] = {}
        try:
            if not await client.is_user_authorized():
                raise TelegramAuthRequired("Telegram session not authorized")
            for chat_id in chat_ids:
                try:
                    entity = await client.get_entity(int(chat_id))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Telegram entity lookup failed for %s: %s", chat_id, exc)
                    continue
                contact = (
                    str(getattr(entity, "title", "") or "").strip()
                    or str(getattr(entity, "first_name", "") or "").strip()
                    or chat_id
                )
                chat_type = _entity_chat_type(entity)
                watermark = float(watermark_by_chat.get(chat_id, 0.0))
                collected: list[Any] = []
                async for msg in client.iter_messages(entity, limit=max(1, per_chat_limit)):
                    parsed = _message_from_telethon(
                        msg,
                        chat_id=chat_id,
                        contact=contact,
                        chat_type=chat_type,
                    )
                    if parsed is None:
                        continue
                    if parsed.timestamp <= watermark:
                        break
                    collected.append(parsed)
                if collected:
                    collected.reverse()
                    out[chat_id] = collected
            return out
        finally:
            await client.disconnect()

    return _run(_fetch())
