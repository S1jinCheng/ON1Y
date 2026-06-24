"""Cross-platform video dedup (prefer Bilibili)."""

from __future__ import annotations

from pathlib import Path

import pytest

from on1y.utils.video_dedup import (
    find_bilibili_duplicate,
    find_youtube_duplicate,
    normalize_video_title,
    purge_youtube_duplicates_of_bilibili,
)


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    from on1y.config import get_settings

    get_settings.cache_clear()
    return db


def test_normalize_video_title_strips_punctuation() -> None:
    assert normalize_video_title("Hello World!") == "helloworld"


def test_find_bilibili_duplicate_by_title(isolated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
    from on1y.user.accounts import UserStore

    monkeypatch.setenv("ON1Y_DB_PATH", str(isolated_db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(isolated_db.parent))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    from on1y.config import get_settings

    get_settings.cache_clear()

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    user = UserStore(storage).create_user(username="u", password="password123")
    with user_context(user.id):
        bili = storage.upsert_raw_item(
            RawItemCreate(
                url="https://www.bilibili.com/video/BV1test001",
                platform="bilibili",
                source=SourceType.MANUAL,
                raw_title="Same Title",
                body_text="",
                content_type=ContentType.VIDEO,
                extract_status=ExtractStatus.OK,
                source_meta={"duration_sec": 600},
            )
        )
        dup = find_bilibili_duplicate(
            storage,
            title="Same Title",
            duration_sec=600,
        )
        assert dup == bili.id
    storage.close()


def test_purge_youtube_duplicates_of_bilibili(isolated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
    from on1y.user.accounts import UserStore

    monkeypatch.setenv("ON1Y_DB_PATH", str(isolated_db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(isolated_db.parent))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    from on1y.config import get_settings

    get_settings.cache_clear()

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    user = UserStore(storage).create_user(username="u2", password="password123")
    with user_context(user.id):
        storage.upsert_raw_item(
            RawItemCreate(
                url="https://www.bilibili.com/video/BV1test002",
                platform="bilibili",
                source=SourceType.MANUAL,
                raw_title="Dup Clip",
                body_text="",
                content_type=ContentType.VIDEO,
                extract_status=ExtractStatus.OK,
                source_meta={"duration_sec": 120},
            )
        )
        yt = storage.upsert_raw_item(
            RawItemCreate(
                url="https://www.youtube.com/watch?v=dupclip1",
                platform="youtube",
                source=SourceType.MANUAL,
                raw_title="Dup Clip",
                body_text="",
                content_type=ContentType.VIDEO,
                extract_status=ExtractStatus.OK,
                source_meta={"duration_sec": 120},
            )
        )
        stats = purge_youtube_duplicates_of_bilibili(storage)
        assert stats["removed"] == 1
        row = storage._connect().execute(
            "SELECT deleted_at FROM raw_items WHERE id = ?", (yt.id,)
        ).fetchone()
        assert row is not None and row["deleted_at"]
    storage.close()


def test_find_youtube_duplicate_for_bilibili_ingest(isolated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate
    from on1y.user.accounts import UserStore

    monkeypatch.setenv("ON1Y_DB_PATH", str(isolated_db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(isolated_db.parent))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    from on1y.config import get_settings

    get_settings.cache_clear()

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    user = UserStore(storage).create_user(username="u3", password="password123")
    with user_context(user.id):
        yt = storage.upsert_raw_item(
            RawItemCreate(
                url="https://www.youtube.com/watch?v=dupclip2",
                platform="youtube",
                source=SourceType.MANUAL,
                raw_title="Mirror",
                body_text="",
                content_type=ContentType.VIDEO,
                extract_status=ExtractStatus.OK,
                source_meta={"duration_sec": 90},
            )
        )
        dup = find_youtube_duplicate(
            storage,
            title="Mirror",
            duration_sec=90,
        )
        assert dup == yt.id
    storage.close()
