from __future__ import annotations

from fastapi.testclient import TestClient

from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.web.app import create_app


def _seed(storage):
    obsidian = storage.upsert_raw_item(
        RawItemCreate(
            url="on1y://obsidian/demo-note",
            platform="obsidian",
            source=SourceType.MANUAL,
            raw_title="Obsidian 笔记",
            body_text="这是一条 Obsidian 笔记。",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={"obsidian_path": "Inbox/Clippings/demo.md", "obsidian_stream": True},
        )
    )
    web = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/page",
            platform="zhihu",
            source=SourceType.MANUAL,
            raw_title="网页条目",
            body_text="网页内容正文。",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    return obsidian.id, web.id


def test_obsidian_items_stay_in_main_feed(storage) -> None:
    _seed(storage)
    client = TestClient(create_app())

    feed = client.get("/api/knowledge/items?collection=feed")
    assert feed.status_code == 200
    assert any(item["platform"] == "obsidian" for item in feed.json()["items"])


def test_create_and_list_item_relations(storage) -> None:
    obsidian_id, web_id = _seed(storage)
    client = TestClient(create_app())

    created = client.post(
        "/api/knowledge/relations",
        json={
            "from_raw_id": obsidian_id,
            "to_raw_id": web_id,
            "relation_type": "obsidian_link",
            "note": "manual-link",
            "confidence": 1,
        },
    )
    assert created.status_code == 200
    assert created.json()["ok"] is True

    rels = client.get(f"/api/knowledge/items/{obsidian_id}/relations")
    assert rels.status_code == 200
    payload = rels.json()
    assert payload["count"] >= 1
    assert any(row["relation_type"] == "obsidian_link" for row in payload["items"])
