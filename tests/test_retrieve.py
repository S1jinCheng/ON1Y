from __future__ import annotations

from fastapi.testclient import TestClient

from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.web.app import create_app


def _seed(storage) -> int:
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/retrieve",
            platform="zhihu",
            source=SourceType.MANUAL,
            raw_title="Retrieve foundation test",
            body_text="This body is for retrieve API verification. " * 8,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={"author": "tester"},
        )
    )
    storage.upsert_distilled(
        raw_id=raw.id,
        summary="retrieve api summary",
        key_points=[],
        topics=[],
        model="test",
        prompt_version="v-test",
        status="ok",
        error=None,
    )
    storage.set_item_classification(raw.id, theme_slug="research", tags=["retrieve"], source="manual")
    return raw.id


def test_retrieve_and_context_api(storage) -> None:
    raw_id = _seed(storage)
    client = TestClient(create_app())

    retrieve_resp = client.post(
        "/api/knowledge/retrieve",
        json={"query": "retrieve", "mode": "keyword", "limit": 10, "collection": "feed"},
    )
    assert retrieve_resp.status_code == 200
    payload = retrieve_resp.json()
    assert payload["hits"]
    assert any(int(hit["raw_id"]) == raw_id for hit in payload["hits"])

    context_resp = client.get(f"/api/knowledge/retrieve/context?raw_ids={raw_id}")
    assert context_resp.status_code == 200
    context_payload = context_resp.json()
    assert context_payload["count"] == 1
    assert context_payload["contexts"][0]["raw_id"] == raw_id
