"""Theme discovery, prefilter, and orchestrated absorb."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.taxonomy.absorb import orchestrate_theme_absorb
from on1y.taxonomy.constants import OTHER_THEME_SLUG
from on1y.taxonomy.discover import (
    merge_known_pairs,
    prefilter_candidates,
    score_item_for_prefilter,
)


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = SqliteStorage(db)
    s.initialize()
    yield s
    s.close()


def _seed_item(
    storage: SqliteStorage,
    *,
    url: str,
    title: str,
    body: str,
    theme_id: int,
    theme_source: str = "llm",
) -> int:
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url=url,
            platform="manual",
            source=SourceType.MANUAL,
            raw_title=title,
            body_text=body,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    storage.set_item_theme(raw.id, theme_id, source=theme_source)
    return raw.id


def test_merge_known_pairs_adds_research_for_tech_slug(storage: SqliteStorage) -> None:
    research = storage.get_theme_by_id(storage.get_theme_id_by_slug("research"))
    assert research is not None
    tech_theme = {
        "id": 99,
        "slug": "科技",
        "name_zh": "科技",
        "name_en": "Technology",
        "description_zh": "产业资讯",
        "description_en": "",
    }
    themes_by_slug = {"research": research}
    merged = merge_known_pairs(
        {"keywords": [], "scan_sources": [], "disambiguation": []},
        theme=tech_theme,
        themes_by_slug=themes_by_slug,
    )
    slugs = {item["slug"] for item in merged["scan_sources"]}
    assert "research" in slugs
    assert merged["disambiguation"]
    assert merged["keywords"]


def test_prefilter_skips_unrelated_items(storage: SqliteStorage) -> None:
    shopping_id = storage.get_theme_id_by_slug("shopping")
    assert shopping_id is not None
    hit = _seed_item(
        storage,
        url="https://example.com/shop",
        title="双十一购物清单",
        body="好物分享与评测。",
        theme_id=shopping_id,
    )
    miss = _seed_item(
        storage,
        url="https://example.com/macro",
        title="美联储利率决议",
        body="宏观经济与货币政策分析。",
        theme_id=shopping_id,
    )
    candidates, hits = prefilter_candidates(
        storage,
        [hit, miss],
        ["购物", "好物", "评测"],
        relation="subset_source",
        max_candidates=50,
    )
    assert hits == 1
    assert hit in candidates
    assert miss not in candidates


def test_score_item_uses_title_and_tags(storage: SqliteStorage) -> None:
    other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
    assert other_id is not None
    raw_id = _seed_item(
        storage,
        url="https://example.com/ai-product",
        title="大模型产品发布",
        body="行业动态",
        theme_id=other_id,
    )
    storage.merge_llm_tags(raw_id, ["人工智能", "产品"])
    score = score_item_for_prefilter(storage, raw_id, ["人工智能", "产品", "科技"])
    assert score >= 2


@patch("on1y.llm.settings.resolve_llm_settings")
@patch("on1y.taxonomy.discover.get_llm_client")
@patch("on1y.taxonomy.absorb.get_llm_client")
def test_orchestrate_absorb_skips_shopping_for_economics_theme(
    mock_absorb_client_factory,
    mock_discover_client_factory,
    mock_llm_settings,
    storage: SqliteStorage,
) -> None:
    mock_llm_settings.return_value.api_key_set = True
    economics = storage.create_theme(
        slug="macro-econ",
        name_zh="宏观经济",
        name_en="Macro",
        description_zh="货币政策与市场分析",
    )
    economics_id = int(economics["id"])
    shopping_id = storage.get_theme_id_by_slug("shopping")
    assert shopping_id is not None
    _seed_item(
        storage,
        url="https://example.com/buy",
        title="购物节攻略",
        body="好物清单",
        theme_id=shopping_id,
    )

    discover_client = MagicMock()
    discover_client.chat_json.return_value = {
        "keywords": ["宏观", "经济", "货币政策"],
        "scan_sources": [],
        "disambiguation": [],
    }
    mock_discover_client_factory.return_value = discover_client

    absorb_client = MagicMock()
    mock_absorb_client_factory.return_value = absorb_client

    report = orchestrate_theme_absorb(storage, theme_id=economics_id, locale="zh")

    assert report["related_source_count"] == 0
    assert "shopping" not in (report.get("scan_sources") or [])
    absorb_client.chat_json.assert_not_called()


@patch("on1y.llm.settings.resolve_llm_settings")
@patch("on1y.taxonomy.discover.get_llm_client")
@patch("on1y.taxonomy.absorb.get_llm_client")
def test_orchestrate_absorb_prefilters_research_for_tech_theme(
    mock_absorb_client_factory,
    mock_discover_client_factory,
    mock_llm_settings,
    storage: SqliteStorage,
) -> None:
    mock_llm_settings.return_value.api_key_set = True
    tech = storage.create_theme(
        slug="科技",
        name_zh="科技",
        name_en="Technology",
        description_zh="AI 产品与行业资讯",
    )
    tech_id = int(tech["id"])
    research_id = storage.get_theme_id_by_slug("research")
    assert research_id is not None
    other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
    assert other_id is not None

    product_raw = _seed_item(
        storage,
        url="https://example.com/ai-launch",
        title="大模型产品发布",
        body="OpenAI 发布新模型，面向消费者与企业。",
        theme_id=research_id,
    )
    paper_raw = _seed_item(
        storage,
        url="https://example.com/paper",
        title="实验方法复现",
        body="实验室对照实验与论文解读。",
        theme_id=research_id,
    )
    _seed_item(
        storage,
        url="https://example.com/unrelated",
        title="菜谱分享",
        body="家常菜做法",
        theme_id=other_id,
    )

    discover_client = MagicMock()
    discover_client.chat_json.return_value = {
        "keywords": ["科技", "AI", "产品", "行业"],
        "scan_sources": [
            {
                "slug": "research",
                "relation": "disambiguation_peer",
                "confidence": 0.9,
                "priority": 10,
            }
        ],
        "disambiguation": [],
    }
    mock_discover_client_factory.return_value = discover_client

    absorb_client = MagicMock()

    def _classify(_system: str, user: str) -> dict:
        if "大模型产品" in user:
            return {"theme_slug": "科技"}
        return {"theme_slug": "research"}

    absorb_client.chat_json.side_effect = _classify
    mock_absorb_client_factory.return_value = absorb_client

    report = orchestrate_theme_absorb(storage, theme_id=tech_id, locale="zh")

    assert report["absorbed"] >= 1
    assert product_raw in storage.list_raw_ids_by_theme(tech_id)
    assert paper_raw in storage.list_raw_ids_by_theme(research_id)
    research_stats = next(
        s for s in report["per_source_stats"] if s["slug"] == "research"
    )
    assert research_stats["llm_candidates"] < research_stats["pool_size"]
