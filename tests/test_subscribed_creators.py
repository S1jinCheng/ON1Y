"""Subscribed creator sidebar includes Bilibili followings with zero items."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    from on1y.config import get_settings

    get_settings.cache_clear()
    return db


def test_list_subscribed_creators_includes_bilibili_follow_with_zero_items(
    isolated_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.user.accounts import UserStore
    from on1y.user.paths import user_feeds_path

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    user = UserStore(storage).create_user(username="alice", password="password123")

    feeds_path = user_feeds_path(user.id)
    feeds_path.write_text(
        yaml.safe_dump(
            {
                "feeds": [
                    {
                        "url": "https://rsshub.app/bilibili/user/video/999001",
                        "label": "bili-up-silent-up",
                        "display_name": "沉默的UP",
                        "enabled": True,
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with user_context(user.id):
        creators = storage.list_subscribed_creators(enrich_avatars=False)

    keys = {row["key"] for row in creators}
    assert "bili:https://space.bilibili.com/999001" in keys
    silent = next(row for row in creators if row["key"].endswith("999001"))
    assert silent["name"] == "沉默的UP"
    assert silent["item_count"] == 0
    storage.close()
