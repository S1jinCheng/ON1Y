"""Absorb from「其他」and related themes when creating a new theme."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.taxonomy.absorb import absorb_from_other_theme, orchestrate_theme_absorb
from on1y.taxonomy.constants import OTHER_THEME_SLUG


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = SqliteStorage(db)
    s.initialize()
    yield s
    s.close()


def _discovery_stub(*, keywords: list[str] | None = None) -> dict:
    return {
        "keywords": keywords or ["音乐", "爵士"],
        "scan_sources": [],
        "disambiguation": [],
    }


def _seed_in_other(storage: SqliteStorage, *, url: str, title: str, body: str) -> int:
    other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
    assert other_id is not None
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
    storage.set_item_theme(raw.id, other_id, source="llm")
    return raw.id


@patch("on1y.llm.settings.resolve_llm_settings")
@patch("on1y.taxonomy.absorb.discover_related_themes")
@patch("on1y.taxonomy.absorb.get_llm_client")
def test_absorb_moves_matching_items_only(
    mock_client_factory,
    mock_discover,
    mock_llm_settings,
    storage: SqliteStorage,
) -> None:
    mock_llm_settings.return_value.api_key_set = True
    mock_discover.return_value = _discovery_stub()
    music = storage.create_theme(
        slug="music",
        name_zh="音乐",
        name_en="Music",
        description_zh="音乐欣赏、乐评与演奏",
    )
    music_id = int(music["id"])
    other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)

    music_raw = _seed_in_other(
        storage,
        url="https://example.com/song",
        title="爵士乐入门",
        body="本文介绍爵士乐的历史与代表曲目。",
    )
    stay_raw = _seed_in_other(
        storage,
        url="https://example.com/code",
        title="Python 异步",
        body="asyncio 与并发编程。",
    )
    user_raw = _seed_in_other(
        storage,
        url="https://example.com/user-pinned",
        title="用户锁定",
        body="古典音乐合集",
    )
    storage.set_item_theme(user_raw, other_id, source="user")

    client = MagicMock()

    def _classify(_system: str, _user: str) -> dict:
        if "爵士" in _user:
            return {"theme_slug": "music"}
        return {"theme_slug": OTHER_THEME_SLUG}

    client.chat_json.side_effect = _classify
    mock_client_factory.return_value = client

    report = absorb_from_other_theme(storage, theme_id=music_id, locale="zh")

    assert report["candidates"] == 2
    assert report["absorbed"] == 1
    assert report["skipped"] == 1
    assert music_raw in storage.list_raw_ids_by_theme(music_id)
    assert stay_raw in storage.list_raw_ids_by_theme(other_id)
    assert user_raw in storage.list_raw_ids_by_theme(other_id)
    assert client.chat_json.call_count == 2


@patch("on1y.llm.settings.resolve_llm_settings")
def test_absorb_skips_without_llm(mock_llm_settings, storage: SqliteStorage) -> None:
    mock_llm_settings.return_value.api_key_set = False
    theme = storage.create_theme(slug="music", name_zh="音乐", name_en="Music")
    report = orchestrate_theme_absorb(storage, theme_id=int(theme["id"]))
    assert report["reason"] == "no_llm_key"
    assert report["absorbed"] == 0
