"""Import Telegram Desktop chat exports into raw_items as written-up conversations.

The user exports chats with Telegram Desktop (JSON format) into ``export_dir``.
On1y scans for ``result.json`` files, groups messages per chat, splits them into
sessions by time gap, drops low-density sessions, archives the rest with a synthetic
``on1y://telegram/<hash>`` URL, and optionally distills them (write-up via reader_text).
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from on1y.distill.processor import distill_raw_item
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.ports.storage import StoragePort
from on1y.telegram.settings import TelegramSettings, load_settings
from on1y.telegram.state import (
    get_chat_watermark,
    load_state,
    save_state,
    set_chat_watermark,
)

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 64 * 1024 * 1024
_TELEGRAM_AVATAR = "https://telegram.org/img/t_logo.png"

_PLACEHOLDER = {
    "photo": "[图片]",
    "video_file": "[视频]",
    "voice_message": "[语音]",
    "video_message": "[视频消息]",
    "sticker": "[贴纸]",
    "animation": "[动图]",
    "file": "[文件]",
    "poll": "[投票]",
    "contact": "[联系人]",
    "location": "[位置]",
}
_REACTION_TOKENS = {
    "哈哈", "哈哈哈", "嗯", "嗯嗯", "哦", "哦哦", "好", "好的", "好滴", "ok", "okk",
    "收到", "在", "嗯呢", "啊", "啊这", "666", "?", "？", ".", "+1", "lol", "haha",
}


@dataclass(slots=True)
class TelegramMessage:
    chat_id: str
    contact: str
    chat_type: str
    sender: str
    timestamp: float
    kind: str
    content: str
    is_self: bool


@dataclass(slots=True)
class TelegramSession:
    chat_id: str
    contact: str
    chat_type: str
    messages: list[TelegramMessage] = field(default_factory=list)

    @property
    def start_ts(self) -> float:
        return self.messages[0].timestamp if self.messages else 0.0

    @property
    def end_ts(self) -> float:
        return self.messages[-1].timestamp if self.messages else 0.0

    @property
    def msg_count(self) -> int:
        return len(self.messages)

    @property
    def text_messages(self) -> list[TelegramMessage]:
        return [m for m in self.messages if m.kind == "text" and m.content.strip()]

    @property
    def char_count(self) -> int:
        return sum(len(m.content.strip()) for m in self.text_messages)

    @property
    def substantive_count(self) -> int:
        return sum(1 for m in self.messages if _is_substantive(m))

    @property
    def substantive_ratio(self) -> float:
        if not self.messages:
            return 0.0
        return self.substantive_count / len(self.messages)

    @property
    def median_text_len(self) -> float:
        lengths = [len(m.content.strip()) for m in self.text_messages]
        return float(statistics.median(lengths)) if lengths else 0.0

    @property
    def duration_minutes(self) -> float:
        return max(0.0, (self.end_ts - self.start_ts) / 60.0)

    def is_dense(self, cfg: TelegramSettings) -> bool:
        return (
            self.char_count >= cfg.min_session_chars
            and self.msg_count >= cfg.min_msg_count
            and self.substantive_ratio >= cfg.min_substantive_ratio
        )

    def content_hash(self) -> str:
        joined = "\n".join(f"{m.timestamp:.0f}|{int(m.is_self)}|{m.content}" for m in self.messages)
        seed = f"{self.chat_id}|{self.start_ts:.0f}|{self.end_ts:.0f}|{joined}"
        return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()


def import_telegram_batch(
    storage: StoragePort,
    *,
    user_id: int | None = None,
    limit: int = 200,
    auto_distill: bool | None = None,
) -> dict[str, Any]:
    """Import Telegram chats via client API or Desktop JSON exports."""
    cfg = load_settings(user_id=user_id)
    report: dict[str, Any] = {
        "enabled": cfg.enabled,
        "reason": "ok",
        "sync_mode": cfg.sync_mode,
        "scanned": 0,
        "sessions": 0,
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "distilled": 0,
        "errors": [],
    }
    if not cfg.enabled:
        report["reason"] = "disabled"
        return report

    should_distill = cfg.auto_distill if auto_distill is None else bool(auto_distill)

    if cfg.sync_mode == "client":
        return _import_from_client(
            storage,
            cfg=cfg,
            user_id=user_id,
            limit=limit,
            should_distill=should_distill,
            report=report,
        )
    return _import_from_export(
        storage,
        cfg=cfg,
        user_id=user_id,
        limit=limit,
        should_distill=should_distill,
        report=report,
    )


def _import_from_export(
    storage: StoragePort,
    *,
    cfg: TelegramSettings,
    user_id: int | None,
    limit: int,
    should_distill: bool,
    report: dict[str, Any],
) -> dict[str, Any]:
    export_raw = (cfg.export_dir or "").strip()
    if not export_raw:
        report["reason"] = "export_dir_missing"
        return report
    export_dir = Path(export_raw).expanduser()
    if not export_dir.is_dir():
        report["reason"] = "export_dir_not_found"
        report["export_dir"] = str(export_dir)
        return report

    messages: list[TelegramMessage] = []
    for file_path in _collect_export_files(export_dir):
        report["scanned"] += 1
        try:
            messages.extend(_parse_export_file(file_path))
        except Exception as exc:  # noqa: BLE001
            report["failed"] += 1
            report["errors"].append(f"{file_path.name}: {exc}")
            logger.warning("Telegram export parse failed for %s: %s", file_path, exc)

    by_chat: dict[str, list[TelegramMessage]] = {}
    for msg in messages:
        by_chat.setdefault(msg.chat_id, []).append(msg)

    state = load_state(user_id=user_id)
    _process_chat_messages(
        storage,
        cfg=cfg,
        by_chat=by_chat,
        state=state,
        limit=limit,
        should_distill=should_distill,
        report=report,
    )
    save_state(state, user_id=user_id)
    report["error_count"] = len(report["errors"])
    return report


def _import_from_client(
    storage: StoragePort,
    *,
    cfg: TelegramSettings,
    user_id: int | None,
    limit: int,
    should_distill: bool,
    report: dict[str, Any],
) -> dict[str, Any]:
    from on1y.telegram.client import (
        TelegramAuthRequired,
        TelegramClientError,
        client_configured,
        fetch_incremental_messages,
        session_authorized,
    )

    if not client_configured(cfg):
        report["reason"] = "client_not_configured"
        return report
    if not session_authorized(user_id=user_id):
        report["reason"] = "session_unauthorized"
        return report

    state = load_state(user_id=user_id)
    chats = state.get("chats") if isinstance(state.get("chats"), dict) else {}
    watermark_by_chat = {str(k): float(v) for k, v in chats.items()}

    try:
        by_chat = fetch_incremental_messages(
            cfg,
            user_id=user_id,
            watermark_by_chat=watermark_by_chat,
        )
    except TelegramAuthRequired:
        report["reason"] = "session_unauthorized"
        return report
    except TelegramClientError as exc:
        report["reason"] = "client_error"
        report["failed"] += 1
        report["errors"].append(str(exc))
        report["error_count"] = len(report["errors"])
        return report
    except Exception as exc:  # noqa: BLE001
        report["reason"] = "client_error"
        report["failed"] += 1
        report["errors"].append(str(exc))
        logger.exception("Telegram client sync failed")
        report["error_count"] = len(report["errors"])
        return report

    report["scanned"] = len(by_chat)
    _process_chat_messages(
        storage,
        cfg=cfg,
        by_chat=by_chat,
        state=state,
        limit=limit,
        should_distill=should_distill,
        report=report,
    )
    save_state(state, user_id=user_id)
    report["error_count"] = len(report["errors"])
    return report


def _process_chat_messages(
    storage: StoragePort,
    *,
    cfg: TelegramSettings,
    by_chat: dict[str, list[TelegramMessage]],
    state: dict[str, Any],
    limit: int,
    should_distill: bool,
    report: dict[str, Any],
) -> None:
    imported = 0
    for chat_id, chat_msgs in by_chat.items():
        if imported >= limit:
            break
        watermark = get_chat_watermark(state, chat_id)
        fresh = sorted((m for m in chat_msgs if m.timestamp > watermark), key=lambda m: m.timestamp)
        if not fresh:
            continue
        sessions = sessionize(fresh, gap_minutes=cfg.session_gap_minutes)
        max_ts = watermark
        for session in sessions:
            report["sessions"] += 1
            max_ts = max(max_ts, session.end_ts)
            if not session.is_dense(cfg):
                report["skipped"] += 1
                continue
            try:
                raw_id, created = _upsert_session(storage, session)
                if not created:
                    report["skipped"] += 1
                    continue
                report["imported"] += 1
                imported += 1
                if should_distill:
                    try:
                        distill_raw_item(storage, raw_id)
                        report["distilled"] += 1
                    except Exception as exc:  # noqa: BLE001
                        report["errors"].append(f"distill #{raw_id}: {exc}")
                if imported >= limit:
                    break
            except Exception as exc:  # noqa: BLE001
                report["failed"] += 1
                report["errors"].append(f"{session.contact}@{session.start_ts:.0f}: {exc}")
                logger.warning("Telegram session import failed for %s: %s", session.contact, exc)
        if max_ts > watermark:
            set_chat_watermark(state, chat_id, max_ts)


def sessionize(messages: list[TelegramMessage], *, gap_minutes: int) -> list[TelegramSession]:
    """Split a chat's time-sorted messages into sessions by idle gap."""
    if not messages:
        return []
    gap_seconds = max(1, gap_minutes) * 60
    sessions: list[TelegramSession] = []
    head = messages[0]
    current = TelegramSession(
        chat_id=head.chat_id,
        contact=head.contact,
        chat_type=head.chat_type,
        messages=[head],
    )
    for prev, msg in zip(messages, messages[1:]):
        if msg.timestamp - prev.timestamp > gap_seconds:
            sessions.append(current)
            current = TelegramSession(
                chat_id=msg.chat_id,
                contact=msg.contact,
                chat_type=msg.chat_type,
                messages=[msg],
            )
        else:
            current.messages.append(msg)
    sessions.append(current)
    return sessions


def _upsert_session(storage: StoragePort, session: TelegramSession) -> tuple[int, bool]:
    content_hash = session.content_hash()
    url = f"on1y://telegram/{content_hash}"
    existing = storage.get_raw_by_url(url)
    if existing is not None:
        return int(existing.id), False

    body_text = _build_transcript(session)
    title = _build_title(session)
    is_group = session.chat_type not in {"personal_chat", "private_chat", "bot_chat"}
    source_meta = {
        "clip_source": "telegram",
        "telegram_chat": session.contact,
        "telegram_chat_id": session.chat_id,
        "telegram_chat_type": session.chat_type,
        "telegram_hash": content_hash,
        "telegram_start_ts": session.start_ts,
        "telegram_end_ts": session.end_ts,
        "telegram_msg_count": session.msg_count,
        "telegram_char_count": session.char_count,
        "telegram_substantive_ratio": round(session.substantive_ratio, 3),
        "telegram_median_text_len": round(session.median_text_len, 1),
        "telegram_duration_minutes": round(session.duration_minutes, 1),
        "telegram_is_group": is_group,
        "conversation": True,
        "author": session.contact,
        "author_avatar": _TELEGRAM_AVATAR,
    }
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url=url,
            platform="telegram",
            source=SourceType.TELEGRAM,
            raw_title=title,
            body_text=body_text,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            extract_error=None,
            source_meta=source_meta,
        )
    )
    return int(raw.id), True


def _build_transcript(session: TelegramSession) -> str:
    lines: list[str] = []
    for msg in session.messages:
        name = "我" if msg.is_self else (msg.sender or session.contact)
        stamp = _format_ts(msg.timestamp)
        text = _render_content(msg)
        if not text:
            continue
        lines.append(f"[{stamp}] {name}：{text}")
    return "\n".join(lines).strip()


def _render_content(msg: TelegramMessage) -> str:
    if msg.kind == "text":
        return msg.content.strip()
    placeholder = _PLACEHOLDER.get(msg.kind)
    if placeholder:
        return placeholder
    return msg.content.strip() or "[非文本消息]"


def _build_title(session: TelegramSession) -> str:
    day = _format_day(session.start_ts)
    is_group = session.chat_type not in {"personal_chat", "private_chat", "bot_chat"}
    if is_group:
        return f"{session.contact} 群聊 · {day}"[:500]
    return f"与 {session.contact} 的对话 · {day}"[:500]


def _collect_export_files(export_dir: Path) -> list[Path]:
    files: list[Path] = []
    for candidate in export_dir.rglob("result.json"):
        if not candidate.is_file():
            continue
        try:
            if candidate.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        files.append(candidate)
    return sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def _parse_export_file(path: Path) -> list[TelegramMessage]:
    text = path.read_text(encoding="utf-8", errors="replace")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("export root must be a JSON object")
    contact = str(data.get("name") or path.parent.name).strip() or path.parent.name
    chat_type = str(data.get("type") or "unknown").strip()
    chat_id = str(data.get("id") or contact)
    rows = data.get("messages")
    if not isinstance(rows, list):
        return []
    out: list[TelegramMessage] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        msg = _row_to_message(row, contact=contact, chat_id=chat_id, chat_type=chat_type)
        if msg is not None:
            out.append(msg)
    return out


def _row_to_message(
    row: dict[str, Any],
    *,
    contact: str,
    chat_id: str,
    chat_type: str,
) -> TelegramMessage | None:
    row_type = str(row.get("type") or "").strip().lower()
    if row_type == "service":
        return None
    if row_type and row_type != "message":
        return None

    ts = _parse_timestamp(row.get("date_unixtime") or row.get("date"))
    if ts <= 0:
        return None

    media_type = str(row.get("media_type") or "").strip().lower()
    if media_type:
        kind = media_type
        content = str(row.get("text") or row.get("caption") or "").strip()
    else:
        text = _flatten_text(row.get("text"))
        if text:
            kind = "text"
            content = text
        else:
            kind = "unknown"
            content = ""

    if kind == "text" and not content:
        return None

    sender = str(row.get("from") or row.get("actor") or "").strip()
    from_id = str(row.get("from_id") or row.get("actor_id") or "").strip()
    is_self = from_id.startswith("user") and sender and sender != contact and chat_type in {
        "personal_chat",
        "private_chat",
    }
    if chat_type in {"personal_chat", "private_chat"} and sender:
        is_self = sender != contact
    if not sender:
        sender = "我" if is_self else contact

    return TelegramMessage(
        chat_id=chat_id,
        contact=contact,
        chat_type=chat_type,
        sender=sender,
        timestamp=ts,
        kind=kind,
        content=content,
        is_self=is_self,
    )


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts).strip()
    return str(value).strip()


def _parse_timestamp(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        ts = float(value)
        return ts / 1000.0 if ts > 1e12 else ts
    text = str(value).strip()
    if not text:
        return 0.0
    if text.isdigit():
        ts = float(text)
        return ts / 1000.0 if ts > 1e12 else ts
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def _is_substantive(msg: TelegramMessage) -> bool:
    if msg.kind != "text":
        return False
    content = msg.content.strip()
    if len(content) < 4:
        return False
    if content.lower() in _REACTION_TOKENS:
        return False
    return True


def _format_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%m-%d %H:%M")


def _format_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d")
