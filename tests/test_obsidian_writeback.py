from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from on1y.auth.context import user_context
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.obsidian.settings import save_settings
from on1y.obsidian.writeback import apply_writeback_queue, build_writeback_block, enqueue_writeback
from on1y.web.app import create_app


def test_obsidian_writeback_append_and_status(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    vault = tmp_path / "vault"
    (vault / "Inbox" / "Clippings").mkdir(parents=True)
    note = vault / "Inbox" / "Clippings" / "demo.md"
    note.write_text("# Demo\n\nOriginal body.\n", encoding="utf-8")

    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/source",
            platform="zhihu",
            source=SourceType.MANUAL,
            raw_title="source",
            body_text="source body",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )

    with user_context(1):
        save_settings(
            enabled=True,
            vault_path=str(vault),
            inbox_relpath="Inbox/Clippings",
            writeback_enabled=True,
        )
        enqueue_writeback(
            storage,
            target_rel_path="Inbox/Clippings/demo.md",
            content_md="\n## On1y 关联\n- test block\n",
            link_raw_id=raw.id,
        )
        report = apply_writeback_queue(storage, user_id=1, limit=10)

    assert report["applied"] == 1
    content = note.read_text(encoding="utf-8")
    assert "On1y 关联" in content
    refreshed = storage.get_raw_by_id(raw.id)
    assert refreshed is not None
    assert refreshed.source_meta.get("obsidian_writeback_status") == "applied"


def test_manual_relation_passively_enqueues_writeback(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    vault = tmp_path / "vault"
    (vault / "Inbox" / "Clippings").mkdir(parents=True)
    note = vault / "Inbox" / "Clippings" / "manual.md"
    note.write_text("# Manual Note\n\nBody\n", encoding="utf-8")

    with user_context(1):
        save_settings(
            enabled=True,
            vault_path=str(vault),
            inbox_relpath="Inbox/Clippings",
            writeback_enabled=True,
        )
        obsidian_raw = storage.upsert_raw_item(
            RawItemCreate(
                url="on1y://obsidian/manual-note",
                platform="obsidian",
                source=SourceType.MANUAL,
                raw_title="obsidian note",
                body_text="obsidian body",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
                source_meta={"obsidian_path": "Inbox/Clippings/manual.md"},
            )
        )
        web_raw = storage.upsert_raw_item(
            RawItemCreate(
                url="https://example.com/r",
                platform="zhihu",
                source=SourceType.MANUAL,
                raw_title="linked source",
                body_text="linked body",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
                source_meta={},
            )
        )
        client = TestClient(create_app())
        created = client.post(
            "/api/knowledge/relations",
            json={
                "from_raw_id": obsidian_raw.id,
                "to_raw_id": web_raw.id,
                "relation_type": "obsidian_link",
                "confidence": 1,
            },
        )
        assert created.status_code == 200
        applied = storage.list_obsidian_writeback_queue(status="applied", limit=20)
        assert applied, "manual relation should trigger writeback apply"
    content = note.read_text(encoding="utf-8")
    assert "On1y 关联" in content


def test_writeback_overwrites_same_link_block(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    vault = tmp_path / "vault"
    (vault / "Inbox" / "Clippings").mkdir(parents=True)
    note = vault / "Inbox" / "Clippings" / "overwrite.md"
    note.write_text("# Overwrite\n\nBase text\n", encoding="utf-8")
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/overwrite",
            platform="zhihu",
            source=SourceType.MANUAL,
            raw_title="overwrite source",
            body_text="overwrite body",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    with user_context(1):
        save_settings(enabled=True, vault_path=str(vault), inbox_relpath="Inbox/Clippings", writeback_enabled=True)
        first = build_writeback_block(
            on1y_url=raw.url,
            relation_type="obsidian_link",
            summary="first summary",
            context=None,
            link_raw_id=raw.id,
        )
        enqueue_writeback(
            storage,
            target_rel_path="Inbox/Clippings/overwrite.md",
            content_md=first,
            link_raw_id=raw.id,
        )
        apply_writeback_queue(storage, user_id=1, limit=20)
        second = build_writeback_block(
            on1y_url=raw.url,
            relation_type="obsidian_link",
            summary="second summary",
            context="new context",
            link_raw_id=raw.id,
        )
        enqueue_writeback(
            storage,
            target_rel_path="Inbox/Clippings/overwrite.md",
            content_md=second,
            link_raw_id=raw.id,
        )
        apply_writeback_queue(storage, user_id=1, limit=20)
    content = note.read_text(encoding="utf-8")
    assert content.count("ON1Y_LINK_BEGIN") == 1
    assert "second summary" in content
    assert "first summary" not in content


def test_unlink_relation_removes_obsidian_writeback_block(storage, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()
    vault = tmp_path / "vault"
    (vault / "Inbox" / "Clippings").mkdir(parents=True)
    note = vault / "Inbox" / "Clippings" / "unlink.md"
    note.write_text("# Unlink\n\nBase text\n", encoding="utf-8")
    with user_context(1):
        save_settings(enabled=True, vault_path=str(vault), inbox_relpath="Inbox/Clippings", writeback_enabled=True)
        obsidian_raw = storage.upsert_raw_item(
            RawItemCreate(
                url="on1y://obsidian/unlink-note",
                platform="obsidian",
                source=SourceType.MANUAL,
                raw_title="unlink obsidian",
                body_text="obsidian body",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
                source_meta={"obsidian_path": "Inbox/Clippings/unlink.md"},
            )
        )
        web_raw = storage.upsert_raw_item(
            RawItemCreate(
                url="https://example.com/unlink",
                platform="zhihu",
                source=SourceType.MANUAL,
                raw_title="unlink source",
                body_text="source body",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
                source_meta={},
            )
        )
        client = TestClient(create_app())
        created = client.post(
            "/api/knowledge/relations",
            json={
                "from_raw_id": obsidian_raw.id,
                "to_raw_id": web_raw.id,
                "relation_type": "obsidian_link",
                "confidence": 1,
            },
        )
        assert created.status_code == 200
        content = note.read_text(encoding="utf-8")
        assert f"ON1Y_LINK_BEGIN:{web_raw.id}" in content
        rel = storage.list_item_relations(obsidian_raw.id)
        relation_id = int(rel[0]["id"])
        deleted = client.delete(
            f"/api/knowledge/relations/{relation_id}",
            params={"raw_id": obsidian_raw.id},
        )
        assert deleted.status_code == 200
    content_after = note.read_text(encoding="utf-8")
    assert f"ON1Y_LINK_BEGIN:{web_raw.id}" not in content_after
