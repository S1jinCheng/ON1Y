from __future__ import annotations

import json
from pathlib import Path

from on1y.auth.context import user_context
from on1y.ingestion.telegram_import import import_telegram_batch, sessionize, _flatten_text
from on1y.telegram.settings import save_settings


def _write_export(export_dir: Path, *, contact: str = "Alice", chat_id: int = 1001) -> None:
    chat_dir = export_dir / "ChatExport"
    chat_dir.mkdir(parents=True, exist_ok=True)
    messages = []
    base_ts = 1_700_000_000
    lines = [
        "我觉得这个架构方案可以分成三层来处理。",
        "第一层是采集，第二层是归档，第三层是蒸馏。",
        "采集层负责从 Telegram 导出 JSON。",
        "归档层把会话切成 session 再入库。",
        "蒸馏层负责书面化和主题分类。",
        "你觉得先做导出扫描还是直接接 API？",
        "我建议先用 Desktop 导出验证 pipeline。",
        "同意，等书面化效果稳定再上 Telethon。",
    ]
    for idx, text in enumerate(lines):
        messages.append(
            {
                "id": idx + 1,
                "type": "message",
                "date": f"2024-01-01T12:{idx:02d}:00",
                "date_unixtime": str(base_ts + idx * 120),
                "from": "Alice" if idx % 2 == 0 else "Bob",
                "text": text,
            }
        )
    payload = {
        "name": contact,
        "type": "personal_chat",
        "id": chat_id,
        "messages": messages,
    }
    (chat_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_flatten_text_handles_rich_segments() -> None:
    assert _flatten_text("plain") == "plain"
    assert _flatten_text(["Hello ", {"type": "bold", "text": "world"}, "!"]) == "Hello world!"


def test_sessionize_splits_by_gap() -> None:
    from on1y.ingestion.telegram_import import TelegramMessage

    msgs = [
        TelegramMessage("1", "Alice", "personal_chat", "Alice", 100.0, "text", "a" * 20, False),
        TelegramMessage("1", "Alice", "personal_chat", "Bob", 200.0, "text", "b" * 20, False),
        TelegramMessage("1", "Alice", "personal_chat", "Alice", 5000.0, "text", "c" * 20, False),
    ]
    sessions = sessionize(msgs, gap_minutes=30)
    assert len(sessions) == 2
    assert sessions[0].msg_count == 2
    assert sessions[1].msg_count == 1


def test_import_dense_session_archives_telegram_item(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    export_dir = tmp_path / "telegram_exports"
    _write_export(export_dir)

    with user_context(1):
        save_settings(
            enabled=True,
            export_dir=str(export_dir),
            sync_mode="export",
            min_session_chars=200,
            min_msg_count=4,
            min_substantive_ratio=0.3,
            auto_distill=False,
        )
        report = import_telegram_batch(storage, user_id=1, auto_distill=False)

    assert report["imported"] == 1
    rows = storage.list_raw_items(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row.platform == "telegram"
    assert row.url.startswith("on1y://telegram/")
    assert row.source_meta.get("conversation") is True
    assert storage.count_collection_items("chats") == 1


def test_import_skips_low_density_session(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    export_dir = tmp_path / "telegram_exports"
    chat_dir = export_dir / "ChatExport"
    chat_dir.mkdir(parents=True)
    payload = {
        "name": "Bob",
        "type": "personal_chat",
        "id": 2002,
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date_unixtime": "1700000000",
                "from": "Bob",
                "text": "嗯",
            },
            {
                "id": 2,
                "type": "message",
                "date_unixtime": "1700000060",
                "from": "Bob",
                "text": "好",
            },
        ],
    }
    (chat_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")

    with user_context(1):
        save_settings(enabled=True, export_dir=str(export_dir), sync_mode="export", auto_distill=False)
        report = import_telegram_batch(storage, user_id=1, auto_distill=False)

    assert report["imported"] == 0
    assert report["skipped"] >= 1


def test_import_is_idempotent_via_hash(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    export_dir = tmp_path / "telegram_exports"
    _write_export(export_dir)

    with user_context(1):
        save_settings(
            enabled=True,
            export_dir=str(export_dir),
            sync_mode="export",
            min_session_chars=200,
            min_msg_count=4,
            min_substantive_ratio=0.3,
            auto_distill=False,
        )
        first = import_telegram_batch(storage, user_id=1, auto_distill=False)
        from on1y.telegram.state import load_state, save_state

        state = load_state(user_id=1)
        state["chats"] = {}
        save_state(state, user_id=1)
        second = import_telegram_batch(storage, user_id=1, auto_distill=False)

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert len(storage.list_raw_items(limit=10)) == 1
