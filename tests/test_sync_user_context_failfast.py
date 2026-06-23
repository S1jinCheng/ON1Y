"""Fail-fast behavior when sync user context is missing."""

from __future__ import annotations

import pytest

from on1y.subscriptions.sync_job import run_subscription_sync_blocking, start_subscription_sync_job
from on1y.user.accounts import UserStore, list_sync_user_ids, set_active_sync_user_id


def test_run_subscription_sync_blocking_requires_user_context() -> None:
    with pytest.raises(RuntimeError, match="requires user_id or active user context"):
        run_subscription_sync_blocking(platform="bilibili")


def test_start_subscription_sync_job_requires_user_context() -> None:
    result = start_subscription_sync_job(platform="bilibili")
    assert result["started"] is False
    assert "缺少用户上下文" in result["message"]


def test_list_sync_user_ids_current_user_only(tmp_path, monkeypatch) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.config import get_settings

    db = tmp_path / "test.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    storage = SqliteStorage(db)
    storage.initialize()
    store = UserStore(storage)
    user2 = store.create_user(username="user2", password="password123")
    set_active_sync_user_id(user2.id)
    assert list_sync_user_ids(storage, current_user_only=True) == [user2.id]

    set_active_sync_user_id(None)
    assert list_sync_user_ids(storage, current_user_only=True) == []
    storage.close()
