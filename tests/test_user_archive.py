"""Archive regressions, including literal Unicode separators from Windows exports."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from on1y.auth.context import user_context
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.user.archive import (
    ARCHIVE_FORMAT,
    ARCHIVE_VERSION,
    _read_archive_payload,
    export_user_archive,
    import_user_archive,
)


def archive_bytes(lines: str, count: int = 2) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": ARCHIVE_FORMAT,
                    "version": ARCHIVE_VERSION,
                    "item_count": count,
                    "include_settings": False,
                }
            ),
        )
        archive.writestr("themes.json", "[]")
        archive.writestr("items.jsonl", lines)
    return buffer.getvalue()


def sample_item(text: str, index: int = 1) -> dict:
    return {
        "url": f"https://example.com/archive/{index}",
        "platform": "web",
        "source": "manual",
        "raw_title": text,
        "body_text": text,
        "content_type": "article",
        "extract_status": "ok",
        "source_meta": {"user_note_html": text, "annotated_body_html": text},
        "distill": {"summary": text, "reader_text": text, "key_points": [text], "topics": []},
    }


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\x85"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("trailing_newline", [True, False])
def test_unicode_separators_are_content_not_record_boundaries(
    separator,
    newline,
    trailing_newline,
):
    expected = [sample_item(f'中文{separator}正文 "引号"\n换行'), sample_item("second", 2)]
    lines = newline.join(json.dumps(item, ensure_ascii=False) for item in expected)
    if trailing_newline:
        lines += newline
    manifest, items, themes, archive, _ = _read_archive_payload(archive_bytes(lines))
    try:
        assert manifest["item_count"] == len(items) == 2
        assert items == expected
        assert themes == []
    finally:
        archive.close()


def test_exported_archive_roundtrips_without_changing_unicode(storage):
    text = '前段\u2028中段\u2029尾段\x85附注\n实际换行 "引号"'
    with user_context(1):
        raw = storage.upsert_raw_item(
            RawItemCreate(
                url="https://example.com/roundtrip",
                platform="web",
                source=SourceType.MANUAL,
                raw_title=text,
                body_text=text,
                source_meta={"user_note_html": text},
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
            )
        )
        storage.upsert_distilled(
            raw_id=raw.id,
            summary=text,
            key_points=[text],
            topics=[],
            model="test",
            prompt_version="1",
            status="ok",
            error=None,
            reader_text=text,
        )
        payload = export_user_archive(storage, 1)
        result = import_user_archive(storage, 1, payload)
        assert result["imported"] == 1
        assert result["error_count"] == 0
        restored = storage.get_raw_by_id(raw.id)
        assert restored.raw_title == text
        assert restored.body_text == text
        assert restored.source_meta["user_note_html"] == text
        assert (
            storage._connect()
            .execute("SELECT summary FROM distilled_items WHERE raw_id=?", (raw.id,))
            .fetchone()[0]
            == text
        )


def test_http_import_accepts_unicode_and_preserves_record_count(storage):
    from on1y.web.app import create_app

    text = "first\u2028second\u2028third\u2028fourth"
    items = [sample_item(text), sample_item("another", 2)]
    payload = archive_bytes("\n".join(json.dumps(item, ensure_ascii=False) for item in items))
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/user/archive/import",
            files={
                "file": ("windows-export.on1y.zip", payload, "application/zip"),
            },
        )
    assert response.status_code == 200
    assert response.json()["imported"] == 2
    assert response.json()["error_count"] == 0
    with user_context(1):
        restored = storage.get_raw_by_url(items[0]["url"])
        assert restored.body_text == text
        assert restored.source_meta["user_note_html"] == text


def test_truncated_json_is_rejected_before_any_records_are_written(storage):
    from on1y.web.app import create_app

    valid = json.dumps(sample_item("valid"))
    # A genuine incomplete backup must not be silently repaired or partly imported.
    payload = archive_bytes(valid + '\n{"url":"https://example.com/broken","body_text":"truncated')
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/user/archive/import",
            files={
                "file": ("broken.on1y.zip", payload, "application/zip"),
            },
        )
    assert response.status_code == 400
    assert "items.jsonl line 2" in response.json()["detail"]
    assert storage._connect().execute("SELECT COUNT(*) FROM raw_items").fetchone()[0] == 0


def test_blank_lines_are_ignored():
    item = sample_item("valid")
    payload = archive_bytes("\r\n\n" + json.dumps(item) + "\r\n\n", count=1)
    _, items, _, archive, _ = _read_archive_payload(payload)
    try:
        assert items == [item]
    finally:
        archive.close()


def import_items(storage, items, *, on_conflict="overwrite"):
    return import_user_archive(
        storage,
        1,
        archive_bytes("\n".join(json.dumps(item) for item in items), count=len(items)),
        on_conflict=on_conflict,
    )


def relation_to(item, note):
    return {"to_url": item["url"], "relation_type": "related", "note": note, "source": "user"}


def test_skip_preserves_existing_relations_but_links_new_items(storage):
    first, second, new = sample_item("local", 1), sample_item("target", 2), sample_item("new", 3)
    first["relations"] = [relation_to(second, "local note")]
    import_items(storage, [first, second])
    first["relations"] = [relation_to(second, "backup note")]
    first["body_text"] = "backup body"
    new["relations"] = [relation_to(second, "new link")]
    result = import_items(storage, [first, second, new], on_conflict="skip")
    assert (result["imported"], result["skipped"], result["error_count"]) == (1, 2, 0)
    notes = {row[0] for row in storage._connect().execute("SELECT note FROM item_relations")}
    assert notes == {"local note", "new link"}
    with user_context(1):
        assert storage.get_raw_by_url(first["url"]).body_text == "local"


def test_skip_duplicate_url_does_not_apply_the_skipped_records_relations(storage):
    first, second = sample_item("first", 1), sample_item("second", 2)
    first["relations"] = [relation_to(second, "first note")]
    duplicate = {**first, "relations": [relation_to(second, "ignored note")]}
    result = import_items(storage, [first, second, duplicate], on_conflict="skip")
    assert (result["imported"], result["skipped"]) == (2, 1)
    assert (
        storage._connect().execute("SELECT note FROM item_relations").fetchone()[0] == "first note"
    )


@pytest.mark.parametrize("keep_relation", [False, True])
def test_overwrite_replaces_summary_theme_tags_relations_and_search_index(storage, keep_relation):
    first, second, third = (
        sample_item("first", 1),
        sample_item("second", 2),
        sample_item("third", 3),
    )
    first["distill"]["summary"] = "obsolete summary"
    first["tags"] = [{"name": "obsolete-tag"}]
    first["relations"] = [relation_to(second, "obsolete link")]
    # An incoming relation owned by an item outside this import must survive.
    third["relations"] = [relation_to(first, "incoming link")]
    theme = storage.list_active_themes()[0]
    first["theme_slug"] = theme["slug"]
    import_items(storage, [first, second, third])
    first.pop("distill")
    first["theme_slug"] = None
    first["tags"] = []
    first["relations"] = [relation_to(second, "replacement link")] if keep_relation else []
    first["body_text"] = "replacement body"
    result = import_items(storage, [first, second])
    assert result["error_count"] == 0
    with user_context(1):
        raw_id = storage.get_raw_by_url(first["url"]).id
    conn = storage._connect()
    assert (
        conn.execute("SELECT 1 FROM distilled_items WHERE raw_id=?", (raw_id,)).fetchone() is None
    )
    assert (
        conn.execute("SELECT theme_id FROM raw_items WHERE id=?", (raw_id,)).fetchone()[0] is None
    )
    assert conn.execute("SELECT 1 FROM item_themes WHERE raw_id=?", (raw_id,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM item_tags WHERE raw_id=?", (raw_id,)).fetchone() is None
    notes = {row[0] for row in conn.execute("SELECT note FROM item_relations")}
    assert notes == ({"incoming link", "replacement link"} if keep_relation else {"incoming link"})
    indexed = conn.execute(
        "SELECT summary, tags, theme, body FROM knowledge_fts WHERE rowid=?", (raw_id,)
    ).fetchone()
    assert tuple(indexed)[:3] == ("", "", "")
    assert "replacement body" in indexed[3]


def test_http_import_runs_off_event_loop_with_connection_owned_by_worker(storage, monkeypatch):
    import asyncio
    import threading

    import httpx
    import on1y.user.archive as archive_module
    import on1y.web.app as web_module

    original_import = archive_module.import_user_archive
    original_get_storage = web_module.get_storage
    started, release = threading.Event(), threading.Event()
    connection_threads = []
    loop_thread = threading.get_ident()

    def get_storage_in_worker():
        connection_threads.append(threading.get_ident())
        return original_get_storage()

    def paused_import(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        assert connection_threads[-1] == threading.get_ident()
        started.set()
        assert release.wait(5), "event loop did not service another request during import"
        return original_import(*args, **kwargs)

    monkeypatch.setattr(web_module, "get_storage", get_storage_in_worker)
    monkeypatch.setattr(archive_module, "import_user_archive", paused_import)
    payload = archive_bytes(json.dumps(sample_item("worker import")), count=1)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web_module.create_app()), base_url="http://test"
        ) as client:
            task = asyncio.create_task(
                client.post(
                    "/api/user/archive/import",
                    files={"file": ("test.on1y.zip", payload, "application/zip")},
                )
            )
            try:
                for _ in range(200):
                    if started.is_set() or task.done():
                        break
                    await asyncio.sleep(0.01)
                assert started.is_set(), "import did not start in a worker"
                health = await asyncio.wait_for(client.get("/api/auth/status"), timeout=2)
                assert health.status_code == 200
                assert not task.done()
            finally:
                release.set()
                response = await task
            assert response.status_code == 200
            assert response.json()["imported"] == 1
            assert response.json()["error_count"] == 0

    asyncio.run(check())


def test_overwrite_keeps_backup_link_to_local_target_outside_archive(storage):
    first, second = sample_item("first", 1), sample_item("local target", 2)
    import_items(storage, [first, second])
    first["relations"] = [relation_to(second, "preserved link")]
    result = import_items(storage, [first])
    assert result["error_count"] == 0
    assert (
        storage._connect().execute("SELECT note FROM item_relations").fetchone()[0]
        == "preserved link"
    )


def test_overwrite_duplicate_url_uses_last_snapshot_relations(storage):
    first, second = sample_item("first", 1), sample_item("second", 2)
    first["relations"] = [relation_to(second, "obsolete link")]
    last = {**first, "body_text": "last body", "relations": []}
    result = import_items(storage, [first, second, last])
    assert result["error_count"] == 0
    assert storage._connect().execute("SELECT COUNT(*) FROM item_relations").fetchone()[0] == 0
    with user_context(1):
        assert storage.get_raw_by_url(first["url"]).body_text == "last body"
