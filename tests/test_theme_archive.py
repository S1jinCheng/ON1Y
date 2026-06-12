"""Theme archive (delete) behavior."""

from __future__ import annotations

import pytest

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.exceptions import StorageError
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.taxonomy.constants import OTHER_THEME_SLUG


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = SqliteStorage(db)
    s.initialize()
    yield s
    s.close()


def test_archive_theme_remaps_items(storage: SqliteStorage) -> None:
    created = storage.create_theme(
        slug="temp-topic",
        name_zh="临时",
        name_en="Temp",
    )
    theme_id = int(created["id"])
    other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
    assert other_id is not None

    raw = storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/a",
            platform="manual",
            source=SourceType.MANUAL,
            raw_title="t",
            body_text="body",
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta={},
        )
    )
    storage.set_item_theme(raw.id, theme_id, source="user")

    remapped = storage.archive_theme(theme_id)
    assert remapped == 1

    themes = storage.list_themes_with_counts()
    assert all(int(t["id"]) != theme_id for t in themes)

    assert raw.id in storage.list_raw_ids_by_theme(other_id)

    with pytest.raises(StorageError, match="built-in"):
        storage.archive_theme(other_id)


def test_reorder_themes(storage: SqliteStorage) -> None:
    rows = storage.list_themes_with_counts()
    assert len(rows) >= 2
    ids = [int(r["id"]) for r in rows]
    reversed_ids = list(reversed(ids))
    storage.reorder_themes(reversed_ids)
    after = [int(r["id"]) for r in storage.list_themes_with_counts()]
    assert after == reversed_ids


def test_archive_theme_rejects_builtin(storage: SqliteStorage) -> None:
    other_id = storage.get_theme_id_by_slug(OTHER_THEME_SLUG)
    assert other_id is not None
    with pytest.raises(StorageError, match="built-in"):
        storage.archive_theme(other_id)
