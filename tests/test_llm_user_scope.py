"""Per-user LLM settings and distill candidate scoping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from on1y.auth.context import user_context


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ON1Y_LLM_API_KEY", "sk-global-user1-only")
    from on1y.config import get_settings

    get_settings.cache_clear()
    return db


def test_user2_llm_key_not_from_global_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_LLM_API_KEY", "sk-global-user1-only")
    from on1y.config import get_settings
    from on1y.llm.settings import resolve_llm_settings

    get_settings.cache_clear()

    user2_llm = tmp_path / "users" / "2" / "llm_settings.json"
    user2_llm.parent.mkdir(parents=True)
    user2_llm.write_text(
        json.dumps(
            {
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-flash",
                "api_key": "sk-user2-private",
            }
        ),
        encoding="utf-8",
    )

    cfg = resolve_llm_settings(user_id=2)
    assert cfg.api_key == "sk-user2-private"
    assert cfg.api_key_set is True


def test_distill_candidates_scoped_per_user(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.distill.prompts import PROMPT_VERSION
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
    from on1y.user.accounts import UserStore

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    alice = store.create_user(username="alice", password="password123")
    bob = store.create_user(username="bob", password="password456")
    item = RawItemCreate(
        url="https://example.com/a",
        platform="web",
        source=SourceType.MANUAL,
        raw_title="t",
        body_text="x" * 80,
        content_type=ContentType.ARTICLE,
        extract_status=ExtractStatus.OK,
    )
    with user_context(alice.id):
        storage.upsert_raw_item(item)
    with user_context(bob.id):
        ids = storage.list_raw_ids_needing_distill(prompt_version=PROMPT_VERSION, limit=10)
        assert ids == []
    with user_context(alice.id):
        ids = storage.list_raw_ids_needing_distill(prompt_version=PROMPT_VERSION, limit=10)
        assert len(ids) == 1
    storage.close()


def test_distill_candidates_platform_filter_matches_user_scope(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.distill.prompts import PROMPT_VERSION
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
    from on1y.user.accounts import UserStore

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    user = store.create_user(username="biliuser", password="password123")
    item = RawItemCreate(
        url="https://www.bilibili.com/video/BVtest123",
        platform="bilibili",
        source=SourceType.BILIBILI_FEED,
        raw_title="video",
        body_text="x" * 80,
        content_type=ContentType.VIDEO,
        extract_status=ExtractStatus.OK,
        source_meta={"subtitle_status": "ready"},
    )
    with user_context(user.id):
        storage.upsert_raw_item(item)
        all_ids = storage.list_raw_ids_needing_distill(prompt_version=PROMPT_VERSION, limit=10)
        bili_ids = storage.list_raw_ids_needing_distill(
            prompt_version=PROMPT_VERSION, limit=10, platform="bilibili"
        )
        assert len(all_ids) == 1
        assert bili_ids == all_ids
    storage.close()
