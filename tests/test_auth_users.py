"""Multi-user auth and profile tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from on1y.auth.context import user_context
from on1y.auth.passwords import hash_password, verify_password
from on1y.user.accounts import UserStore, bootstrap_default_user
from on1y.user.profile import load_user_profile, patch_user_profile


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ON1Y_BOOTSTRAP_USERNAME", "testadmin")
    monkeypatch.setenv("ON1Y_BOOTSTRAP_PASSWORD", "testpass123")
    from on1y.config import get_settings

    get_settings.cache_clear()
    return db


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("secretpass")
    assert verify_password("secretpass", hashed)
    assert not verify_password("wrong", hashed)


def test_create_user_and_profile(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    user = store.create_user(username="alice", password="password123", email="a@example.com")
    with user_context(user.id):
        profile = load_user_profile()
        assert profile["owner"] == "alice"
        patch_user_profile(kindle={"send_to": "kindle@kindle.com"})
        updated = load_user_profile()
        assert updated["kindle"]["send_to"] == "kindle@kindle.com"
    storage.close()


def test_bootstrap_migrates_legacy(isolated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cookies_dir = isolated_db.parent / "cookies"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    (cookies_dir / "zhihu.json").write_text('{"cookies": []}', encoding="utf-8")

    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    assert store.count_users() >= 1
    user = store.get_user_by_username("testadmin")
    assert user is not None
    storage.close()
