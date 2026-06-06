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
    from on1y.user.paths import user_cookie_path

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    user = store.create_user(username="alice", password="password123", email="a@example.com")
    with user_context(user.id):
        profile = load_user_profile()
        assert profile["owner"] == "alice"
        cookies = profile["integrations"]["cookies"]
        assert Path(cookies["bilibili"]) == user_cookie_path(user.id, "bilibili")
        patch_user_profile(kindle={"send_to": "kindle@kindle.com"})
        updated = load_user_profile()
        assert updated["kindle"]["send_to"] == "kindle@kindle.com"
    storage.close()


def test_same_url_different_users(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    alice = store.create_user(username="alice", password="password123")
    bob = store.create_user(username="bob", password="password456")
    url = "https://www.bilibili.com/video/BV1test"
    item = RawItemCreate(
        url=url,
        platform="bilibili",
        source=SourceType.MANUAL,
        raw_title="shared title",
        body_text="body",
        content_type=ContentType.VIDEO,
        extract_status=ExtractStatus.OK,
    )
    with user_context(alice.id):
        a_item = storage.upsert_raw_item(item)
    with user_context(bob.id):
        b_item = storage.upsert_raw_item(item)
    assert a_item.id != b_item.id
    assert a_item.url == b_item.url == url
    storage.close()


def test_skip_bootstrap_when_auth_without_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "fresh.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_REQUIRED", "true")
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ON1Y_BOOTSTRAP_PASSWORD", "")
    from on1y.config import get_settings

    get_settings.cache_clear()

    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(db)
    storage.initialize()
    store = UserStore(storage)
    assert store.count_users() == 0
    storage.close()


def test_theme_counts_scoped_per_user(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context
    from on1y.models.enums import ContentType, ExtractStatus, SourceType
    from on1y.models.raw import RawItemCreate

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    alice = store.create_user(username="alice", password="password123")
    bob = store.create_user(username="bob", password="password456")
    themes = storage.list_themes_with_counts()
    theme_id = next(t["id"] for t in themes if t["slug"] == "research")
    item = RawItemCreate(
        url="https://example.com/a",
        platform="web",
        source=SourceType.MANUAL,
        raw_title="t",
        body_text="b",
        content_type=ContentType.ARTICLE,
        extract_status=ExtractStatus.OK,
    )
    with user_context(alice.id):
        raw = storage.upsert_raw_item(item)
        storage.set_item_theme(raw.id, theme_id)
        alice_counts = {r["slug"]: int(r["item_count"]) for r in storage.list_themes_with_counts()}
    with user_context(bob.id):
        bob_counts = {r["slug"]: int(r["item_count"]) for r in storage.list_themes_with_counts()}
    assert alice_counts.get("research", 0) >= 1
    assert bob_counts.get("research", 0) == 0
    storage.close()


def test_list_users_public(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    store.create_user(username="alice", password="password123")
    store.create_user(username="bob", password="password456")
    users = store.list_users_public()
    assert len(users) == 3  # bootstrap + alice + bob
    names = {u.username for u in users}
    assert "alice" in names
    assert "bob" in names
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
