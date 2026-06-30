"""Per-user Telegram import watermark stored in data/users/<id>/telegram_state.json.

Keys are chat_id strings; values are the latest message timestamp processed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from on1y.auth.context import get_effective_user_id
from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)


def state_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    return user_dir(uid) / "telegram_state.json"


def load_state(*, user_id: int | None = None) -> dict[str, Any]:
    path = state_file_path(user_id=user_id)
    if not path.is_file():
        return {"chats": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Invalid Telegram state file: %s", path)
        return {"chats": {}}
    if not isinstance(payload, dict):
        return {"chats": {}}
    chats = payload.get("chats")
    if not isinstance(chats, dict):
        payload["chats"] = {}
    return payload


def save_state(state: dict[str, Any], *, user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_effective_user_id()
    path = state_file_path(user_id=uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_chat_watermark(state: dict[str, Any], chat_id: str) -> float:
    chats = state.get("chats") or {}
    raw = chats.get(chat_id, 0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def set_chat_watermark(state: dict[str, Any], chat_id: str, ts: float) -> None:
    chats = state.setdefault("chats", {})
    if not isinstance(chats, dict):
        chats = {}
        state["chats"] = chats
    chats[chat_id] = ts
