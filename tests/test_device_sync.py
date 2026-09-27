"""Two independent desktop databases against the real authenticated relay API."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.auth.context import user_context
from on1y.device_sync.client import DeviceSync, run_sync, validate_url
from on1y.device_sync.library import snapshot
from on1y.device_sync.protocol import Operation, encode
from on1y.device_sync.server import create_sync_app
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate

KEY = "test-pairing-key-with-more-than-32-characters"
URL = "https://example.com/article"


@pytest.fixture
def pair(tmp_path, monkeypatch):
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_BOOTSTRAP_PASSWORD", "test-only-password")
    from on1y.config import get_settings

    get_settings.cache_clear()
    stores = [SqliteStorage(tmp_path / f"{name}.db") for name in ("windows", "mac")]
    for store in stores:
        store.initialize()
    a, b = [DeviceSync(store) for store in stores]
    for sync in (a, b):
        sync.configure(1, "http://127.0.0.1:8787", KEY, True)
    client = TestClient(
        create_sync_app(tmp_path / "relay.db", KEY), headers={"Authorization": f"Bearer {KEY}"}
    )
    client.headers["X-On1y-Library"] = client.get("/v1/info").json()["library_id"]
    yield a, b, client
    client.close()
    for store in stores:
        store.close()


def add(sync, url=URL, meta=None):
    with user_context(1):
        return sync.storage.upsert_raw_item(
            RawItemCreate(
                url=url,
                platform="web",
                source=SourceType.MANUAL,
                raw_title="Article title",
                body_text="Useful article body",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
                source_meta=meta or {},
            )
        ).id


def fields(sync, url=URL):
    return next(r["fields"] for r in snapshot(sync.conn, 1).values() if r["identity"] == url)


def cycle(a, b, client):
    for sync in (a, b, a):
        sync.sync(client, user_id=1)


def test_roundtrip_library_and_secrets_excluded(pair):
    a, b, client = pair
    rid = add(
        a,
        meta={
            "user_note_html": "<p>my note</p>",
            "starred": True,
            "cookie": "SECRET",
            "api_key": "SECRET",
            "pdf_path": "C:/private.pdf",
        },
    )
    a.storage.upsert_distilled(
        raw_id=rid,
        summary="Summary",
        key_points=["One"],
        topics=["Topic"],
        model="test",
        prompt_version="1",
        reader_text="Reader",
        status="ok",
        error=None,
    )
    theme = a.storage.create_theme(slug="my-topic", name_zh="我的主题", name_en="My topic")
    a.storage.set_item_theme_by_slug(rid, "my-topic", source="manual")
    tag = a.storage.ensure_flat_tag("测试标签")
    a.storage.link_item_tag(rid, tag, confidence=1, source="manual")
    cycle(a, b, client)
    assert fields(a) == fields(b)
    assert fields(b)["meta/user_note_html"] == "<p>my note</p>"
    assert fields(b)["distill/summary"] == "Summary"
    assert fields(b)["theme_slug"] == "my-topic"
    assert fields(b)["tag/测试标签"] is True
    assert "SECRET" not in encode(client.get("/v1/pull").json())
    assert "C:/private" not in encode(client.get("/v1/pull").json())
    assert a.status(1)["pending"] == 0
    assert not a.status(1)["conflicts"]
    assert theme is not None


def test_concurrent_different_fields_merge(pair):
    a, b, client = pair
    arid = add(a)
    cycle(a, b, client)
    brid = b.storage.get_raw_by_url(URL).id
    a.storage.merge_source_meta(arid, {"user_note_html": "Windows note"})
    b.storage.set_item_read_state(brid, read=True)
    cycle(a, b, client)
    assert fields(a) == fields(b)
    assert fields(b)["meta/user_note_html"] == "Windows note"
    assert fields(a)["meta/read_at"]
    assert not a.status(1)["conflicts"]


def test_concurrent_notes_keep_both_and_resolve(pair):
    a, b, client = pair
    arid = add(a, meta={"user_note_html": "base"})
    cycle(a, b, client)
    brid = b.storage.get_raw_by_url(URL).id
    a.storage.merge_source_meta(arid, {"user_note_html": "Windows"})
    b.storage.merge_source_meta(brid, {"user_note_html": "Mac"})
    cycle(a, b, client)
    conflict = a.status(1)["conflicts"][0]
    assert conflict["current"] == "Windows"
    assert conflict["incoming"] == "Mac"
    assert fields(a)["meta/user_note_html"] == fields(b)["meta/user_note_html"] == "Windows"
    assert client.post(
        f"/v1/conflicts/{conflict['id']}/resolve", json={"choice": "incoming"}
    ).is_success
    cycle(a, b, client)
    assert fields(a)["meta/user_note_html"] == fields(b)["meta/user_note_html"] == "Mac"
    assert not a.status(1)["conflicts"]


def test_delete_offline_edit_and_restore(pair):
    a, b, client = pair
    arid = add(a)
    cycle(a, b, client)
    brid = b.storage.get_raw_by_url(URL).id
    with a.conn:
        a.conn.execute("UPDATE raw_items SET deleted_at='2026-09-27' WHERE id=?", (arid,))
    b.storage.merge_source_meta(brid, {"user_note_html": "offline note"})
    cycle(a, b, client)
    assert fields(a)["_deleted"] and fields(b)["_deleted"]
    assert fields(a)["meta/user_note_html"] == "offline note"
    with b.conn:
        b.conn.execute("UPDATE raw_items SET deleted_at=NULL WHERE id=?", (brid,))
    cycle(b, a, client)
    assert not fields(a)["_deleted"]


def test_permanent_delete_does_not_resurrect(pair):
    a, b, client = pair
    rid = add(a)
    cycle(a, b, client)
    with a.conn:
        a.conn.execute("DELETE FROM raw_items WHERE id=?", (rid,))
    cycle(a, b, client)
    assert a.storage.get_raw_by_url(URL) is None
    assert fields(b)["_deleted"]
    cycle(a, b, client)
    assert a.storage.get_raw_by_url(URL) is None
    assert not a.status(1)["conflicts"]


def test_lost_ack_retry_and_restart_are_idempotent(pair):
    a, b, client = pair
    add(a)
    a.capture(1, a.config()["device_id"])
    batch = [json.loads(r[0]) for r in a.conn.execute("SELECT data FROM device_sync_outbox")]
    assert client.post("/v1/push", json=batch).is_success
    count = len(client.get("/v1/pull").json()["events"])
    path = a.storage.db_path
    a.storage.close()
    restarted_storage = SqliteStorage(path)
    try:
        restarted = DeviceSync(restarted_storage)
        restarted.sync(client, user_id=1)
        assert restarted.status(1)["pending"] == 0
        assert len(client.get("/v1/pull").json()["events"]) == count
        b.sync(client, user_id=1)
        assert fields(restarted) == fields(b)
    finally:
        restarted_storage.close()


def test_edit_while_request_in_flight_is_preserved(pair):
    a, b, client = pair
    rid = add(a, meta={"user_note_html": "first"})
    a.capture(1, a.config()["device_id"])
    batch = [json.loads(r[0]) for r in a.conn.execute("SELECT data FROM device_sync_outbox")]
    client.post("/v1/push", json=batch).raise_for_status()
    a.storage.merge_source_meta(rid, {"user_note_html": "edited during upload"})
    a.apply(client.get("/v1/pull").json()["events"], 1)
    assert fields(a)["meta/user_note_html"] == "edited during upload"
    cycle(a, b, client)
    assert fields(b)["meta/user_note_html"] == "edited during upload"
    assert not a.status(1)["conflicts"]


def test_apply_failure_rolls_back_data_and_cursor(pair, monkeypatch):
    a, b, client = pair
    add(a)
    a.sync(client, user_id=1)
    events = client.get("/v1/pull").json()["events"]
    from on1y.device_sync import client as module

    actual = module.write_record

    def broken(*args):
        actual(*args)
        raise RuntimeError("simulated crash after library write")

    monkeypatch.setattr(module, "write_record", broken)
    with pytest.raises(RuntimeError):
        b.apply(events, 1)
    assert b.status(1)["cursor"] == 0
    assert b.storage.get_raw_by_url(URL) is None
    monkeypatch.setattr(module, "write_record", actual)
    b.sync(client, user_id=1)
    assert fields(a) == fields(b)


def test_initial_existing_data_conflicts_are_retained(pair):
    a, b, client = pair
    add(a, meta={"user_note_html": "old Windows library"})
    add(b, meta={"user_note_html": "old Mac library"})
    cycle(a, b, client)
    conflicts = a.status(1)["conflicts"]
    assert any(c["incoming"] == "old Mac library" for c in conflicts)
    assert fields(a)["meta/user_note_html"] == "old Windows library"
    assert fields(a) == fields(b)


def test_tag_removal_and_parallel_additions(pair):
    a, b, client = pair
    arid = add(a)
    tag = a.storage.ensure_flat_tag("remove-me")
    a.storage.link_item_tag(arid, tag, confidence=1, source="manual")
    cycle(a, b, client)
    brid = b.storage.get_raw_by_url(URL).id
    a.storage.clear_item_tags(arid)
    for sync, rid, name in ((a, arid, "from-windows"), (b, brid, "from-mac")):
        tag = sync.storage.ensure_flat_tag(name)
        sync.storage.link_item_tag(rid, tag, confidence=1, source="manual")
    cycle(a, b, client)
    assert "tag/remove-me" not in fields(b)
    assert fields(a)["tag/from-mac"] and fields(b)["tag/from-windows"]


def test_relay_auth_and_protocol_validation(pair):
    a, b, client = pair
    assert client.get("/v1/info", headers={"Authorization": "Bearer wrong"}).status_code == 401
    op = dict(
        op_id=str(uuid4()),
        device_id="win",
        kind="item",
        identity=URL,
        patch={"meta/cookie": "secret"},
        base={"meta/cookie": 0},
    )
    assert client.post("/v1/push", json=[op]).status_code == 400
    op.update(patch={"raw_title": "A"}, base={"raw_title": 0})
    assert client.post("/v1/push", json=[op]).is_success
    op["patch"]["raw_title"] = "B"
    assert client.post("/v1/push", json=[op]).status_code == 400
    assert client.get("/v1/pull", params={"cursor": 999}).status_code == 409


def test_changed_library_blocks_upload(pair, tmp_path):
    a, b, client = pair
    add(a)
    a.sync(client, user_id=1)
    with TestClient(
        create_sync_app(tmp_path / "replacement.db", KEY),
        headers={"Authorization": f"Bearer {KEY}"},
    ) as other:
        other.headers["X-On1y-Library"] = other.get("/v1/info").json()["library_id"]
        with pytest.raises(ValueError, match="资料库已改变"):
            a.sync(other, user_id=1)
        assert other.get("/v1/pull").json()["events"] == []


def test_bound_user_and_public_settings(pair):
    a, b, client = pair
    with pytest.raises(ValueError, match="另一个本地账号"):
        a.configure(2, "http://localhost:8787", KEY, True)
    with pytest.raises(ValueError):
        a.status(2)
    assert KEY not in encode(a.status(1))
    a.configure(1, "http://localhost:8787", "", False)
    assert a.config()["token"] == KEY
    assert run_sync(a.storage.db_path) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "file:///tmp/a",
        "https://u:p@host",
        "https://host?key=secret",
        "http://192.168.1.2:8787",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_invalid_enum_rejected():
    with pytest.raises(ValueError):
        Operation(
            op_id="a",
            device_id="b",
            kind="item",
            identity=URL,
            patch={"content_type": "invalid"},
            base={"content_type": 0},
        )


def test_http_routes_use_local_auth(pair, monkeypatch):
    a, b, relay = pair
    monkeypatch.setenv("ON1Y_DB_PATH", str(a.storage.db_path))
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "true")
    from on1y.config import get_settings
    from on1y.web.app import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert client.get("/api/device-sync").status_code == 401
        assert client.post("/api/device-sync", json={"enabled": False}).status_code == 401


def test_offline_queue_survives_connection_error(pair, monkeypatch):
    a, b, relay = pair
    add(a)
    a.capture(1, a.config()["device_id"])

    class Offline:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            raise httpx.ConnectError("private URL and key must not leak")

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: Offline())
    with pytest.raises(ValueError, match="下次自动重试"):
        run_sync(a.storage.db_path)
    assert a.status(1)["pending"] == 1
    assert "private URL" not in a.status(1)["last_error"]
    cycle(a, b, relay)
    assert fields(a) == fields(b)


def test_multiple_batches_and_server_restart(pair, tmp_path):
    a, b, client = pair
    for index in range(65):
        add(a, url=f"https://example.com/{index}")
    a.sync(client, user_id=1)
    assert a.status(1)["pending"] == 15
    with TestClient(
        create_sync_app(tmp_path / "relay.db", KEY), headers={"Authorization": f"Bearer {KEY}"}
    ) as restarted:
        a.sync(restarted, user_id=1)
        b.sync(restarted, user_id=1)
        assert a.status(1)["pending"] == 0
        assert snapshot(a.conn, 1) == snapshot(b.conn, 1)
        assert b.conn.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0] == 65


def test_stale_conflict_cannot_overwrite_a_new_edit(pair):
    a, b, client = pair
    rid = add(a, meta={"user_note_html": "base"})
    cycle(a, b, client)
    a.storage.merge_source_meta(rid, {"user_note_html": "Windows"})
    b.storage.merge_source_meta(b.storage.get_raw_by_url(URL).id, {"user_note_html": "Mac"})
    cycle(a, b, client)
    conflict = a.status(1)["conflicts"][0]
    a.storage.merge_source_meta(rid, {"user_note_html": "newer"})
    cycle(a, b, client)
    endpoint = f"/v1/conflicts/{conflict['id']}/resolve"
    assert client.post(endpoint, json={"choice": "incoming"}).status_code == 409
    assert client.post(endpoint, json={"choice": "current"}).status_code == 200
    cycle(a, b, client)
    assert fields(b)["meta/user_note_html"] == "newer"
    assert not a.status(1)["conflicts"]


def test_corrupt_event_leaves_library_and_cursor_untouched(pair):
    a, b, client = pair
    add(a)
    a.sync(client, user_id=1)
    events = client.get("/v1/pull").json()["events"]
    events[0]["record"]["fields"]["raw_title"] = "changed in transit"
    with pytest.raises(ValueError, match="校验失败"):
        b.apply(events, 1)
    assert b.status(1)["cursor"] == 0
    assert b.storage.get_raw_by_url(URL) is None


def test_server_rollback_is_detected_before_upload(pair, tmp_path):
    import sqlite3

    a, b, client = pair
    add(a)
    a.sync(client, user_id=1)
    add(a, url="https://example.com/second")
    # Simulate a restored/edited server history with the same library ID.
    with sqlite3.connect(tmp_path / "relay.db") as conn:
        conn.execute("UPDATE events SET data='{}' WHERE seq=1")
    # Starlette versions use either httpx or httpx2 internally.
    with pytest.raises(Exception) as error:
        a.sync(client, user_id=1)
    assert error.value.response.status_code == 409
    with sqlite3.connect(tmp_path / "relay.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1


def test_library_header_required_even_with_correct_key(pair):
    a, b, client = pair
    assert client.post("/v1/push", json=[], headers={"X-On1y-Library": "wrong"}).status_code == 409


def test_opt_in_route_saves_masked_config_and_pauses(pair, monkeypatch):
    a, b, relay = pair
    monkeypatch.setenv("ON1Y_DB_PATH", str(a.storage.db_path))
    from on1y.config import get_settings
    from on1y.web.app import create_app

    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/device-sync",
            json={
                "server_url": "http://127.0.0.1:8787",
                "key": "",
                "enabled": False,
            },
        )
        assert response.status_code == 200
        assert response.json()["has_key"]
        assert not response.json()["enabled"]
        assert KEY not in response.text
        assert client.post("/api/device-sync/run").status_code == 400


def test_live_http_transport_roundtrip_and_wrong_key(pair, tmp_path):
    """Exercise production httpx/uvicorn, not only Starlette's in-process client."""
    import socket
    import threading
    import time

    import uvicorn

    a, b, _ = pair
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_sync_app(tmp_path / "live-relay.db", KEY),
            log_level="error",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert server.started
        for sync in (a, b):
            sync.configure(1, f"http://127.0.0.1:{port}", KEY, True)
        rid = add(a, meta={"user_note_html": "over real HTTP"})
        for sync in (a, b, a):
            run_sync(sync.storage.db_path, 1)
        assert fields(b)["meta/user_note_html"] == "over real HTTP"
        a.configure(1, f"http://127.0.0.1:{port}", "incorrect-key-that-is-at-least-32-chars", True)
        a.storage.merge_source_meta(rid, {"user_note_html": "kept offline"})
        with pytest.raises(ValueError, match="配对密钥不正确"):
            run_sync(a.storage.db_path, 1)
        assert a.status(1)["pending"] == 1
        assert fields(a)["meta/user_note_html"] == "kept offline"
        a.configure(1, f"http://127.0.0.1:{port}", KEY, True)
        run_sync(a.storage.db_path, 1)
        run_sync(b.storage.db_path, 1)
        assert fields(b)["meta/user_note_html"] == "kept offline"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
