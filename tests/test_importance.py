"""Importance rating stored in source_meta.importance."""

from __future__ import annotations

from on1y.knowledge.importance import importance_from_meta, normalize_importance


def test_normalize_importance() -> None:
    assert normalize_importance(3) == 3
    assert normalize_importance("5") == 5
    assert normalize_importance(0) is None
    assert normalize_importance(6) is None
    assert normalize_importance(None) is None


def test_importance_from_meta() -> None:
    assert importance_from_meta({"importance": 4}) == 4
    assert importance_from_meta({}) is None


def test_patch_and_filter_importance(storage) -> None:
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate

    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/importance-test",
            platform="manual",
            source=SourceType.MANUAL,
            raw_title="Importance test",
            body_text="body",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    storage.merge_source_meta(raw.id, {"importance": 2})
    assert importance_from_meta(storage.get_raw_by_id(raw.id).source_meta) == 2

    storage.merge_source_meta(raw.id, {"importance": None})
    assert importance_from_meta(storage.get_raw_by_id(raw.id).source_meta) is None

    storage.merge_source_meta(raw.id, {"importance": 5})
    rows = storage.list_knowledge_items(collection="feed", min_importance=5, limit=50)
    assert any(int(row["raw_id"]) == raw.id for row in rows)

    storage.merge_source_meta(raw.id, {"importance": 3})
    rows_min4 = storage.list_knowledge_items(collection="feed", min_importance=4, limit=50)
    assert not any(int(row["raw_id"]) == raw.id for row in rows_min4)


def test_importance_api(storage) -> None:
    from fastapi.testclient import TestClient

    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
    from on1y.web.app import create_app

    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/importance-api",
            platform="manual",
            source=SourceType.MANUAL,
            raw_title="API importance",
            body_text="body",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    client = TestClient(create_app())
    resp = client.patch(
        f"/api/knowledge/items/{raw.id}/importance",
        json={"importance": 4},
    )
    assert resp.status_code == 200
    assert resp.json()["importance"] == 4

    listed = client.get("/api/knowledge/items", params={"min_importance": 4}).json()
    assert any(item["raw_id"] == raw.id for item in listed["items"])

    clear = client.patch(
        f"/api/knowledge/items/{raw.id}/importance",
        json={"importance": None},
    )
    assert clear.status_code == 200
    assert clear.json()["importance"] is None
