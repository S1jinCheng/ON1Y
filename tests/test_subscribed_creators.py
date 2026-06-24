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


def test_list_subscribed_creators_includes_bilibili_follow_with_enough_items(
    isolated_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
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
        for idx in range(4):
            storage.upsert_raw_item(
                RawItemCreate(
                    url=f"https://www.bilibili.com/video/BV99900{idx}",
                    platform="bilibili",
                    source=SourceType.MANUAL,
                    raw_title=f"post {idx}",
                    body_text="x",
                    content_type=ContentType.VIDEO,
                    extract_status=ExtractStatus.OK,
                    source_meta={
                        "author": "沉默的UP",
                        "author_url": "https://space.bilibili.com/999001",
                    },
                )
            )
        creators = storage.list_subscribed_creators(enrich_avatars=False)

    keys = {row["key"] for row in creators}
    assert "bili:https://space.bilibili.com/999001" in keys
    silent = next(row for row in creators if row["key"].endswith("999001"))
    assert silent["name"] == "沉默的UP"
    assert silent["item_count"] == 4
    storage.close()


def test_list_subscribed_creators_includes_twitter_authors(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
    from on1y.user.accounts import UserStore

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    user = UserStore(storage).create_user(username="bob", password="password123")

    with user_context(user.id):
        storage.upsert_raw_item(
            RawItemCreate(
                url="https://x.com/i/web/status/1",
                platform="twitter",
                source=SourceType.MANUAL,
                raw_title="Alice: hello",
                body_text="hello",
                content_type=ContentType.ARTICLE,
                extract_status=ExtractStatus.OK,
                source_meta={
                    "author": "Alice",
                    "author_url": "https://twitter.com/alice",
                    "feed_label": "x-likes",
                },
            )
        )
        creators = storage.list_subscribed_creators(enrich_avatars=False)

    row = next(row for row in creators if row["key"] == "twitter:https://x.com/alice")
    assert row["name"] == "Alice"
    assert row["platform"] == "twitter"
    assert row["item_count"] == 1
    storage.close()
