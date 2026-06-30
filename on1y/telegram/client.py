"""Telegram Client API (Telethon) — direct local sync without Desktop export."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from on1y.auth.context import get_effective_user_id
from on1y.telegram.settings import TelegramSettings, load_settings
from on1y.telegram.state import load_state, save_state
from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)


class TelegramClientError(Exception):
    pass


class TelegramAuthRequired(TelegramClientError):
    pass


def session_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    return user_dir(uid) / "telegram"


def session_authorized(*, user_id: int | None = None) -> bool:
    base = session_path(user_id=user_id)
    return base.with_suffix(".session").is_file() or Path(f"{base}.session").is_file()


def client_configured(cfg: TelegramSettings) -> bool:
    return bool(cfg.api_id and (cfg.api_hash or "").strip() and cfg.sync_chat_ids)


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
    from on1y.network.proxy import effective_ytdlp_proxy

    raw = (effective_ytdlp_proxy(user_id=user_id) or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return None
    scheme = (parsed.scheme or "http").lower()
    if scheme.startswith("socks"):
        return ("socks5", host, port)
    return ("http", host, port)


def _run(coro):
    return asyncio.run(coro)


async def _build_client(*, user_id: int | None) -> Any:
    TelegramClient, _ = _require_telethon()
    cfg = load_settings(user_id=user_id)
    if not cfg.api_id or not (cfg.api_hash or "").strip():
        raise TelegramClientError("api_id and api_hash are required")
    proxy = _proxy_tuple(user_id=user_id)
    client = TelegramClient(
        str(session_path(user_id=user_id)),
        int(cfg.api_id),
        str(cfg.api_hash).strip(),
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
