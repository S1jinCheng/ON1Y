"""Pytest fixtures — isolated SQLite per test."""

from __future__ import annotations

from pathlib import Path

import pytest
from on1y.adapters.sqlite_storage import SqliteStorage


@pytest.fixture(autouse=True)
def _disable_auth_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most API tests use TestClient without login; individual tests may override."""
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "false")
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ON1Y_DISABLE_DOTENV", "1")
    from on1y.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_on1y.db"


@pytest.fixture
def storage(tmp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> SqliteStorage:
    monkeypatch.setenv("ON1Y_DB_PATH", str(tmp_db_path))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_db_path.parent))
    from on1y.config import get_settings

    get_settings.cache_clear()
    store = SqliteStorage(db_path=tmp_db_path)
    store.initialize()
    yield store
    store.close()
    get_settings.cache_clear()
