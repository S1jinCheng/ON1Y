"""FTS5 trigram search tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.search.fts import prepare_fts_query, rebuild_knowledge_fts, search_knowledge_fts
from on1y.web.app import create_app


def _seed_search_corpus(storage) -> tuple[int, int]:
    alpha = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/alpha",
            platform="bilibili",
            source=SourceType.MANUAL,
            raw_title="深度学习在计算机视觉中的应用",
            body_text="本文讨论卷积神经网络与目标检测。" * 6,
            content_type=ContentType.VIDEO,
            extract_status=ExtractStatus.OK,
            source_meta={"author": "张三"},
        )
    )
    beta = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/beta",
            platform="zhihu",
            source=SourceType.MANUAL,
            raw_title="行为经济学入门",
            body_text="锚定效应与损失厌恶是经典话题。" * 6,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={"author": "李四"},
        )
    )
    storage.upsert_distilled(
        raw_id=alpha.id,
        summary="概述 CNN 在图像识别中的实践。",
        key_points=[],
        topics=[],
        model="test",
        prompt_version="v-test",
        status="ok",
        error=None,
    )
    storage.upsert_distilled(
        raw_id=beta.id,
        summary="介绍行为经济学核心概念。",
        key_points=[],
        topics=[],
        model="test",
        prompt_version="v-test",
        status="ok",
        error=None,
    )
    storage.set_item_classification(beta.id, theme_slug="research", tags=["认知科学"], source="manual")
    return alpha.id, beta.id


def test_prepare_fts_query_ands_terms() -> None:
    assert prepare_fts_query("深度学习 视觉") == '"深度学习" AND "视觉"'
    assert prepare_fts_query('"exact phrase"') == '"exact phrase"'


def test_fts_ranking_and_snippets(storage) -> None:
    alpha_id, beta_id = _seed_search_corpus(storage)
    conn = storage._connect()
    rebuild_knowledge_fts(conn)
    conn.commit()

    hits, total = search_knowledge_fts(conn, user_query="深度学习")
    assert total == 1
    assert hits[0]["raw_id"] == alpha_id
    assert "<mark>" in (hits[0]["search_title_html"] or "")

    hits_body, total_body = search_knowledge_fts(conn, user_query="锚定")
    assert total_body == 1
    assert hits_body[0]["raw_id"] == beta_id

    hits_tag, _ = search_knowledge_fts(conn, user_query="认知")
    assert any(h["raw_id"] == beta_id for h in hits_tag)


def test_search_knowledge_items_api(storage) -> None:
    _seed_search_corpus(storage)
    client = TestClient(create_app())
    response = client.get("/api/knowledge/items?query=深度学习")
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"] == "fts5"
    assert payload["total"] == 1
    assert payload["items"][0]["search_title_html"]


def test_search_rebuild_api(storage) -> None:
    _seed_search_corpus(storage)
    client = TestClient(create_app())
    response = client.post("/api/knowledge/search/rebuild")
    assert response.status_code == 200
    assert response.json()["rebuilt"] >= 2
