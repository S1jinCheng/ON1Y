"""User notes: search index and notes collection."""

from __future__ import annotations

from fastapi.testclient import TestClient

from on1y.knowledge.notes import has_user_note
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.search.fts import rebuild_knowledge_fts, search_knowledge_fts
from on1y.web.app import create_app


def test_note_search_and_collection(storage) -> None:
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/note-target",
            platform="bilibili",
            source=SourceType.MANUAL,
            raw_title="笔记测试",
            body_text="正文无关",
            content_type=ContentType.VIDEO,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    storage.merge_source_meta(raw.id, {"user_note_html": "<p>量子纠缠实验记录</p>"})

    conn = storage._connect()
    rebuild_knowledge_fts(conn)
    conn.commit()

    hits, total = search_knowledge_fts(conn, user_query="量子纠缠")
    assert total >= 1
    assert any(int(h["raw_id"]) == raw.id for h in hits)

    assert storage.count_collection_items("notes") >= 1
    rows = storage.list_knowledge_items(collection="notes", limit=20)
    assert any(int(r["raw_id"]) == raw.id for r in rows)
    assert all(r.get("has_note") for r in rows)

    meta = storage.get_raw_by_id(raw.id).source_meta
    assert has_user_note(meta)


def test_patch_note_api(storage) -> None:
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/note-api",
            platform="bilibili",
            source=SourceType.MANUAL,
            raw_title="API 笔记",
            body_text="b",
            content_type=ContentType.VIDEO,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    client = TestClient(create_app())
    response = client.patch(
        f"/api/knowledge/items/{raw.id}/note",
        json={"html": "<p>notetermunique 笔记内容</p>"},
    )
    assert response.status_code == 200
    assert "notetermunique" in response.json()["user_note_html"]

    search = client.get(
        "/api/knowledge/items",
        params={"query": "notetermunique", "limit": 10},
    )
    assert search.status_code == 200
    ids = [item["raw_id"] for item in search.json()["items"]]
    assert raw.id in ids

    counts = client.get("/api/knowledge/collections")
    assert counts.json()["notes"] >= 1
