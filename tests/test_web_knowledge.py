"""Knowledge API tests for exclusive theme taxonomy."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.web.app import create_app


def _seed_sample(storage) -> int:
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/research-llm",
            platform="zhihu",
            source=SourceType.MANUAL,
            raw_title="LLM 在科研中的应用",
            body_text="这是一篇关于科研和大模型的内容。" * 8,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={"author": "Alice"},
        )
    )
    storage.upsert_distilled(
        raw_id=raw.id,
        summary="介绍科研场景中 LLM 的效率提升。",
        key_points=[],
        topics=[],
        model="deepseek-v4-flash",
        prompt_version="v4-exclusive",
        status="ok",
        error=None,
    )
    storage.set_item_classification(
        raw.id,
        theme_slug="research",
        tags=["LLM", "认知科学"],
        source="manual",
    )
    return raw.id


def test_knowledge_taxonomy(storage) -> None:
    _seed_sample(storage)
    client = TestClient(create_app())
    response = client.get("/api/knowledge/taxonomy?locale=zh")
    assert response.status_code == 200
    payload = response.json()
    slugs = {theme["slug"] for theme in payload["themes"]}
    assert "research" in slugs
    assert "other" in slugs
    assert any(tag["name"] == "LLM" for tag in payload["tags"])


def test_knowledge_items_filter_by_theme(storage) -> None:
    raw_id = _seed_sample(storage)
    client = TestClient(create_app())
    themes = client.get("/api/knowledge/taxonomy?locale=zh").json()["themes"]
    research = next(t for t in themes if t["slug"] == "research")
    response = client.get(f"/api/knowledge/items?theme_id={research['id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["raw_id"] == raw_id
    assert payload["items"][0]["theme"]["slug"] == "research"


def test_move_item_theme(storage) -> None:
    raw_id = _seed_sample(storage)
    client = TestClient(create_app())
    film = next(
        t for t in client.get("/api/knowledge/taxonomy?locale=zh").json()["themes"]
        if t["slug"] == "film"
    )
    response = client.patch(
        f"/api/knowledge/items/{raw_id}/theme",
        json={"theme_id": film["id"]},
    )
    assert response.status_code == 200
    assert response.json()["theme"]["slug"] == "film"


def test_create_theme(storage, monkeypatch) -> None:
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    from on1y.config import get_settings

    get_settings.cache_clear()
    client = TestClient(create_app())
    with patch("on1y.taxonomy.absorb.schedule_absorb_from_other") as mock_absorb:
        mock_absorb.return_value = {"started": True, "theme_id": 99}
        response = client.post(
            "/api/knowledge/themes",
            json={"slug": "ai", "name_zh": "人工智能", "name_en": "AI"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["theme"]["slug"] == "ai"
    assert payload["absorb"]["started"] is True
    mock_absorb.assert_called_once()


def test_reader_content(storage) -> None:
    raw_id = _seed_sample(storage)
    storage.upsert_distilled(
        raw_id=raw_id,
        summary="摘要",
        key_points=[],
        topics=[],
        model="m",
        prompt_version="v4-exclusive",
        status="ok",
        error=None,
        reader_text="整理后的阅读文本。",
    )
    client = TestClient(create_app())
    response = client.get(f"/api/knowledge/items/{raw_id}/reader")
    assert response.status_code == 200
    payload = response.json()
    assert payload["reader_text"] == "整理后的阅读文本。"
    assert payload["body_text"]
