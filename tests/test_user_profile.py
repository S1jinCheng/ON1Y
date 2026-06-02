"""Tests for user profile persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from on1y.auth.context import user_context
from on1y.user import profile as up


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ON1Y_BOOTSTRAP_USERNAME", "owner")
    monkeypatch.setenv("ON1Y_BOOTSTRAP_PASSWORD", "testpass123")
    from on1y.config import get_settings

    get_settings.cache_clear()
    return db


def test_create_profile_from_defaults(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    with user_context(1):
        payload = up._default_payload()
        payload["kindle"]["send_to"] = "test@kindle.com"
        up.save_user_profile(payload)
        loaded = up.load_user_profile(create_if_missing=False)
        assert loaded["kindle"]["send_to"] == "test@kindle.com"
    storage.close()


def test_patch_economist_edition(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    with user_context(1):
        up.save_user_profile(up._default_payload())
        up.patch_user_profile(economist={"last_synced_edition": "2026-05-30"})
        data = up.load_user_profile()
        assert data["economist"]["last_synced_edition"] == "2026-05-30"
    storage.close()
