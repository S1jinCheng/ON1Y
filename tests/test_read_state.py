"""Read / unread state on knowledge items."""

from __future__ import annotations

from fastapi.testclient import TestClient

from on1y.knowledge.read_state import is_read_meta, read_at_from_meta
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.web.app import create_app


def _seed(storage) -> int:
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/read-test",
            platform="zhihu",
            source=SourceType.MANUAL,
            raw_title="未读文章",
            body_text="正文",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    return raw.id


def test_read_meta_helpers() -> None:
    assert not is_read_meta({})
    assert is_read_meta({"read_at": "2026-06-05T12:00:00Z"})
    assert read_at_from_meta({"read_at": "2026-06-05T12:00:00Z"}) == "2026-06-05T12:00:00Z"


def test_touch_item_reading_marks_read(storage) -> None:
    raw_id = _seed(storage)
    result = storage.touch_item_reading(raw_id)
    assert result["is_read"] is True
    assert result["read_at"]
    assert result["last_opened_at"]
    items = storage.list_knowledge_items(collection="unread", limit=10)
    assert all(int(i["raw_id"]) != raw_id for i in items)


def test_set_item_read_state_unread(storage) -> None:
    raw_id = _seed(storage)
    storage.touch_item_reading(raw_id)
    storage.set_item_read_state(raw_id, read=False)
    items = storage.list_knowledge_items(collection="unread", limit=50)
    assert any(int(i["raw_id"]) == raw_id for i in items)


def test_read_api(storage) -> None:
    raw_id = _seed(storage)
    client = TestClient(create_app())
    response = client.post(f"/api/knowledge/items/{raw_id}/read")
    assert response.status_code == 200
    assert response.json()["is_read"] is True

    unread = client.get("/api/knowledge/items", params={"unread_only": "true"}).json()
    assert all(item["raw_id"] != raw_id for item in unread["items"])

    mark_unread = client.patch(
        f"/api/knowledge/items/{raw_id}/read",
        json={"read": False},
    )
    assert mark_unread.status_code == 200
    assert mark_unread.json()["is_read"] is False


def test_collections_unread_count(storage) -> None:
    _seed(storage)
    client = TestClient(create_app())
    counts = client.get("/api/knowledge/collections").json()
    assert counts["unread"] >= 1
