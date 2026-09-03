from __future__ import annotations

from pathlib import Path

from on1y.auth.context import user_context
from on1y.ingestion.telegram_import import import_telegram_batch
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.telegram.settings import save_settings
from on1y.telegram.tagging import apply_conversation_system_tags
from tests.test_telegram_import import _write_export


def test_apply_conversation_system_tags(storage) -> None:
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="on1y://telegram/testhash",
            platform="telegram",
            source=SourceType.TELEGRAM,
            raw_title="与 Alice 的对话",
            body_text="hello",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={"conversation": True, "author": "Alice"},
        )
    )
    apply_conversation_system_tags(
        storage,
        int(raw.id),
        contact="Alice",
        chat_type="personal_chat",
    )
    names = storage.get_item_tag_names(int(raw.id))
    assert "Alice" in names
    assert "私聊" in names


def test_import_applies_system_tags_without_distill(storage, tmp_path: Path, monkeypatch) -> None:
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
            auto_tag=False,
        )
        report = import_telegram_batch(storage, user_id=1, auto_distill=False)

    assert report["imported"] == 1
    row = storage.list_raw_items(limit=1)[0]
    names = storage.get_item_tag_names(int(row.id))
    assert "Alice" in names
