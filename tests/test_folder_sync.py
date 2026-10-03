"""Independent Mac/Windows databases, unordered cloud delivery, and real attachments."""

import json
import shutil
from pathlib import Path

import pytest
from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.auth.context import user_context
from on1y.books.models import BookLink, BookShelfCreate, BookShelfUpdate
from on1y.books.shelf import create_shelf_item, list_shelf_items, update_shelf_item
from on1y.folder_sync.engine import MANIFEST, FolderSync
from on1y.papers.models import PaperCreate, PaperUpdate
from on1y.papers.shelf import create_paper, delete_paper, list_papers, update_paper


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ON1Y_BOOTSTRAP_PASSWORD", "test-only-password")
    from on1y.config import get_settings

    get_settings.cache_clear()
    stores = []
    for name in ("mac", "windows"):
        directory = tmp_path / name
        directory.mkdir()
        store = SqliteStorage(directory / "on1y.db")
        store.initialize()
        stores.append(store)
    a, b = [FolderSync(store) for store in stores]
    cloud = tmp_path / "cloud"
    a.configure(1, str(cloud), True, create=True)
    b.configure(1, str(cloud), True)
    yield a, b, cloud
    for store in stores:
        store.close()
    get_settings.cache_clear()


def cycle(a, b):
    for sync in (a, b, a, b):
        sync.sync(1)


def paper(sync, tmp_path, title="Paper", doi="10.1000/testing"):
    pdf = tmp_path / (title + ".pdf")
    pdf.write_bytes(b"%PDF-1.4\nTest attachment\n%%EOF")
    return create_paper(
        sync.storage,
        1,
        PaperCreate(
            title=title,
            doi=doi,
            pdf_path=str(pdf),
            authors=["Author"],
            tags=["science"],
        ),
    )


def test_paper_file_metadata_and_bidirectional_notes(pair, tmp_path):
    a, b, cloud = pair
    original = paper(a, tmp_path)
    update_paper(a.storage, 1, original.id, PaperUpdate(user_note_html="Mac note"))
    cycle(a, b)
    received = list_papers(b.storage, 1)[0]
    assert received.title == "Paper"
    assert received.user_note_html == "Mac note"
    assert received.tags == ["science"]
    assert received.raw_id is not None
    assert Path(received.pdf_path).read_bytes() == Path(original.pdf_path).read_bytes()
    assert received.pdf_path != original.pdf_path
    update_paper(
        b.storage, 1, received.id, PaperUpdate(user_note_html="Windows note", status="read")
    )
    cycle(b, a)
    result = list_papers(a.storage, 1)[0]
    assert result.user_note_html == "Windows note"
    assert result.status == "read"
    assert not a.status(1)["conflicts"]
    files = list(cloud.rglob("*"))
    assert not any(p.suffix in {".db", ".sqlite3"} for p in files)
    text = "".join(p.read_text() for p in (cloud / "events").glob("*.json"))
    assert str(tmp_path) not in text
    count = len(list((cloud / "events").glob("*.json")))
    cycle(a, b)
    assert len(list((cloud / "events").glob("*.json"))) == count


def test_book_file_and_local_ids_do_not_collide(pair, tmp_path):
    a, b, cloud = pair
    for sync, title in ((a, "Book A"), (b, "Book B")):
        path = tmp_path / (title + ".epub")
        path.write_bytes(title.encode())
        create_shelf_item(
            sync.storage,
            1,
            BookShelfCreate(
                title=title,
                author="Author",
                links=[BookLink(label="local", url=path.as_uri())],
                notes="My note\ncached: " + str(path),
                tags=[title],
            ),
        )
    cycle(a, b)
    for sync in (a, b):
        books = list_shelf_items(sync.storage, 1)
        assert {book.title for book in books} == {"Book A", "Book B"}
        assert all(Path(book.local_path).read_text() == book.title for book in books)
    item = next(v for v in list_shelf_items(b.storage, 1) if v.title == "Book A")
    update_shelf_item(
        b.storage, 1, item.id, BookShelfUpdate(user_note_html="Book note", status="read")
    )
    cycle(b, a)
    result = next(v for v in list_shelf_items(a.storage, 1) if v.title == "Book A")
    assert result.user_note_html == "Book note" and result.status == "read"
    assert str(tmp_path) not in "".join(p.read_text() for p in (cloud / "events").glob("*.json"))


def test_offline_conflicts_converge_and_can_resolve(pair, tmp_path):
    a, b, _ = pair
    paper(a, tmp_path)
    cycle(a, b)
    for sync, note in ((a, "Mac edit"), (b, "Windows edit")):
        item = list_papers(sync.storage, 1)[0]
        update_paper(sync.storage, 1, item.id, PaperUpdate(user_note_html=note))
        sync.capture(1)
    cycle(a, b)
    assert (
        list_papers(a.storage, 1)[0].user_note_html == list_papers(b.storage, 1)[0].user_note_html
    )
    conflict = next(c for c in a.status(1)["conflicts"] if c["field"] == "meta/user_note_html")
    assert {v["value"] for v in conflict["versions"]} == {"Mac edit", "Windows edit"}
    chosen = next(v for v in conflict["versions"] if v["value"] == "Windows edit")
    a.resolve(1, conflict["key"], conflict["field"], chosen["id"])
    cycle(a, b)
    assert list_papers(a.storage, 1)[0].user_note_html == "Windows edit"
    assert not b.status(1)["conflicts"]


def test_delete_and_explicit_restore_preserve_attachment(pair, tmp_path):
    a, b, _ = pair
    original = paper(a, tmp_path)
    cycle(a, b)
    target = Path(list_papers(b.storage, 1)[0].pdf_path)
    delete_paper(a.storage, 1, original.id)
    cycle(a, b)
    assert not list_papers(a.storage, 1)
    assert not list_papers(b.storage, 1)
    assert target.exists()
    deleted = b.status(1)["deleted"][0]
    b.restore(1, deleted["key"])
    cycle(b, a)
    assert len(list_papers(a.storage, 1)) == len(list_papers(b.storage, 1)) == 1
    assert Path(list_papers(a.storage, 1)[0].pdf_path).read_bytes() == target.read_bytes()


def test_attachment_delayed_then_downloaded(pair, tmp_path):
    a, b, cloud = pair
    paper(a, tmp_path)
    a.sync(1)
    object_file = next((cloud / "objects").iterdir())
    data = object_file.read_bytes()
    object_file.unlink()
    result = b.sync(1)
    assert result["pending_files"] == 1
    assert list_papers(b.storage, 1)[0].pdf_path is None
    object_file.write_bytes(data)
    b.sync(1)
    assert b.status(1)["pending_files"] == 0
    assert Path(list_papers(b.storage, 1)[0].pdf_path).read_bytes() == data


def test_pdf_external_edit_is_versioned(pair, tmp_path):
    a, b, cloud = pair
    paper(a, tmp_path)
    cycle(a, b)
    path = Path(list_papers(b.storage, 1)[0].pdf_path)
    path.write_bytes(b"%PDF-1.4\nAnnotated in Windows\n%%EOF")
    cycle(b, a)
    assert Path(list_papers(a.storage, 1)[0].pdf_path).read_bytes() == path.read_bytes()
    assert len(list((cloud / "objects").iterdir())) == 2


def test_missing_folder_marker_never_recreates_library(pair):
    a, _, cloud = pair
    (cloud / MANIFEST).unlink()
    with pytest.raises(ValueError, match="不可用"):
        a.sync(1)
    assert not (cloud / MANIFEST).exists()
    a.configure(1, str(cloud), False)
    assert not a.status(1)["enabled"]


def test_feed_and_theme_roundtrip_and_secret_exclusion(pair):
    from on1y.models.enums import SourceType
    from on1y.models.raw import RawItemCreate

    a, b, cloud = pair
    with user_context(1):
        item = a.storage.upsert_raw_item(
            RawItemCreate(
                url="https://example.org/article",
                platform="web",
                source=SourceType.MANUAL,
                content_type="article",
                extract_status="ok",
                raw_title="Article",
                body_text="Body",
                source_meta={"cookie": "SECRET", "user_note_html": "Note"},
            )
        )
    a.storage.create_theme(slug="custom", name_zh="主题", name_en="Topic")
    a.storage.set_item_theme_by_slug(item.id, "custom", source="manual")
    cycle(a, b)
    assert b.storage.get_raw_by_url("https://example.org/article").raw_title == "Article"
    assert "SECRET" not in "".join(p.read_text() for p in (cloud / "events").glob("*.json"))


def test_wrong_library_and_unsafe_folder_rejected(pair, tmp_path):
    a, _, cloud = pair
    with pytest.raises(ValueError, match="分开"):
        a.configure(1, str(a.storage.db_path.parent), True)
    marker = json.loads((cloud / MANIFEST).read_text())
    marker["library_id"] = "00000000-0000-0000-0000-000000000000"
    (cloud / MANIFEST).write_text(json.dumps(marker))
    with pytest.raises(ValueError, match="标识"):
        a.sync(1)


def test_two_separate_cloud_folders_exchange_events_out_of_order(pair, tmp_path):
    a, b, cloud = pair
    second = tmp_path / "windows-cloud"
    second.mkdir()
    shutil.copyfile(cloud / MANIFEST, second / MANIFEST)
    b.configure(1, str(second), True)
    item = paper(a, tmp_path)
    a.sync(1)
    update_paper(a.storage, 1, item.id, PaperUpdate(user_note_html="Later"))
    a.sync(1)
    events = sorted(
        (cloud / "events").glob("*.json"), key=lambda p: json.loads(p.read_text())["clock"]
    )
    (second / "events").mkdir()
    shutil.copyfile(events[-1], second / "events" / events[-1].name)
    assert b.sync(1)["pending_events"] == 1
    assert not list_papers(b.storage, 1)
    for event in events:
        shutil.copyfile(event, second / "events" / event.name)
    shutil.copytree(cloud / "objects", second / "objects")
    b.sync(1)
    assert list_papers(b.storage, 1)[0].user_note_html == "Later"


def test_changes_during_cloud_io_are_not_lost(pair, tmp_path, monkeypatch):
    from on1y.folder_sync import engine

    a, b, _ = pair
    paper(a, tmp_path)
    cycle(a, b)
    bitem = list_papers(b.storage, 1)[0]
    update_paper(a.storage, 1, list_papers(a.storage, 1)[0].id, PaperUpdate(status="read"))
    a.sync(1)
    actual = engine.receive_blob

    def edit_during_download(*args):
        update_paper(b.storage, 1, bitem.id, PaperUpdate(user_note_html="Edited in flight"))
        return actual(*args)

    monkeypatch.setattr(engine, "receive_blob", edit_during_download)
    b.sync(1)
    monkeypatch.setattr(engine, "receive_blob", actual)
    cycle(b, a)
    result = list_papers(a.storage, 1)[0]
    assert result.user_note_html == "Edited in flight"
    assert result.status == "read"


def test_repeated_sync_does_not_reorder_books(pair, tmp_path):
    a, b, _ = pair
    paper(a, tmp_path)
    cycle(a, b)
    with b.conn:
        b.conn.execute("UPDATE paper_items SET updated_at='2020-01-01'")
    cycle(a, b)
    assert list_papers(b.storage, 1)[0].updated_at == "2020-01-01"


def test_upload_retry_preserves_edit_after_failure(pair, tmp_path, monkeypatch):
    from on1y.folder_sync import engine

    a, b, _ = pair
    item = paper(a, tmp_path)
    actual = engine.atomic_write

    def fail(*args):
        raise OSError("offline")

    monkeypatch.setattr(engine, "atomic_write", fail)
    with pytest.raises(OSError):
        a.sync(1)
    update_paper(a.storage, 1, item.id, PaperUpdate(user_note_html="Edited after failed upload"))
    monkeypatch.setattr(engine, "atomic_write", actual)
    cycle(a, b)
    assert list_papers(b.storage, 1)[0].user_note_html == "Edited after failed upload"
    assert not a.status(1)["conflicts"]


def test_apply_failure_is_transactional(pair, tmp_path, monkeypatch):
    from on1y.folder_sync import records

    a, b, _ = pair
    paper(a, tmp_path)
    a.sync(1)
    actual = records.write_record

    def fail(*args, **kwargs):
        actual(*args, **kwargs)
        raise RuntimeError("interrupted")

    monkeypatch.setattr(records, "write_record", fail)
    with pytest.raises(RuntimeError):
        b.sync(1)
    assert not list_papers(b.storage, 1)
    monkeypatch.setattr(records, "write_record", actual)
    b.sync(1)
    assert len(list_papers(b.storage, 1)) == 1


def test_cloud_notes_cannot_bind_an_arbitrary_local_file(pair, tmp_path):
    from on1y.device_sync.protocol import record_key
    from on1y.folder_sync import records

    a, _, _ = pair
    secret = tmp_path / "private.pdf"
    secret.write_bytes(b"private data")
    record = {
        "key": record_key("book", "test"),
        "kind": "book",
        "identity": "test",
        "fields": {
            "library/title": "Cloud book",
            "library/status": "reading",
            "library/notes": "cached: " + str(secret),
            "_deleted": False,
        },
    }
    with a.conn:
        records.write_record(a.conn, 1, record)
    assert list_shelf_items(a.storage, 1)[0].local_path is None


def test_relay_and_folder_sync_cannot_both_be_enabled(pair):
    from on1y.device_sync.client import DeviceSync

    a, _, cloud = pair
    relay = DeviceSync(a.storage)
    with pytest.raises(ValueError, match="关闭文件夹"):
        relay.configure(1, "http://localhost:8787", "x" * 40, True)
    a.configure(1, str(cloud), False)
    relay.configure(1, "http://localhost:8787", "x" * 40, True)
    with pytest.raises(ValueError, match="关闭服务"):
        a.configure(1, str(cloud), True)


def test_concurrent_attachment_versions_are_retained(pair, tmp_path):
    a, b, cloud = pair
    paper(a, tmp_path)
    cycle(a, b)
    for sync, data in ((a, b"Mac PDF"), (b, b"Windows PDF")):
        Path(list_papers(sync.storage, 1)[0].pdf_path).write_bytes(data)
        sync.capture(1)
    cycle(a, b)
    conflicts = a.status(1)["conflicts"]
    attachment = next(c for c in conflicts if c["field"] == "attachment")
    assert len(attachment["versions"]) == 2
    assert {p.read_bytes() for p in (cloud / "objects").iterdir()} >= {b"Mac PDF", b"Windows PDF"}
    assert (
        Path(list_papers(a.storage, 1)[0].pdf_path).read_bytes()
        == Path(list_papers(b.storage, 1)[0].pdf_path).read_bytes()
    )


def test_restoring_original_attachment_does_not_reuse_a_modified_copy(pair, tmp_path):
    a, b, _ = pair
    original = paper(a, tmp_path)
    original_bytes = Path(original.pdf_path).read_bytes()
    cycle(a, b)
    state, _ = a.state()
    record = next(r for r in state.values() if r["kind"] == "paper")
    original_ref = record["fields"]["attachment"]
    old_path = Path(list_papers(a.storage, 1)[0].pdf_path)
    old_path.write_bytes(b"Changed PDF")
    cycle(a, b)
    state, _ = a.state()
    record = state[record["key"]]
    with a.conn:
        a.add_event(record, {"attachment": original_ref}, record["heads"])
    cycle(a, b)
    assert Path(list_papers(a.storage, 1)[0].pdf_path).read_bytes() == original_bytes
    assert old_path.read_bytes() == b"Changed PDF"


def test_authenticated_folder_routes(pair, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from on1y.auth.tokens import create_access_token
    from on1y.config import get_settings
    from on1y.folder_sync.routes import register_folder_sync_routes
    from on1y.web.auth_http import install_auth_middleware

    a, _, cloud = pair
    monkeypatch.setenv("ON1Y_DB_PATH", str(a.storage.db_path))
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "true")
    monkeypatch.setenv("ON1Y_SINGLE_USER_MODE", "false")
    get_settings.cache_clear()
    app = FastAPI()
    install_auth_middleware(app)
    register_folder_sync_routes(app)
    username = a.conn.execute("SELECT username FROM users WHERE id=1").fetchone()[0]
    token = create_access_token(user_id=1, username=username)
    with TestClient(app) as client:
        assert client.get("/api/folder-sync").status_code == 401
        client.headers["Authorization"] = f"Bearer {token}"
        assert client.get("/api/folder-sync").json()["folder"] == str(cloud)
        assert client.post("/api/folder-sync/run").status_code == 200
        result = client.post("/api/folder-sync", json={"folder": str(cloud), "enabled": False})
        assert result.status_code == 200 and result.json()["enabled"] is False
        assert client.post("/api/folder-sync/run").status_code == 400


def test_user_scope_and_unknown_cloud_fields(pair, tmp_path):
    from uuid import uuid4

    from on1y.folder_sync.protocol import Event

    a, _, _ = pair
    with pytest.raises(ValueError, match="账号"):
        a.status(2)
    for field, value in (
        ("pdf_path", "/private/secret.pdf"),
        ("library/pdf_path", "secret"),
        ("meta/api_key", "secret"),
        ("attachment", {"sha256": "../../secret"}),
    ):
        with pytest.raises(ValueError):
            Event(
                library_id=a.config()["library_id"],
                id=uuid4(),
                device_id=uuid4(),
                clock=1,
                kind="paper",
                identity="test",
                patch={field: value},
                parents={field: []},
            )
