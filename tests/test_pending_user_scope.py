"""Per-user pending_urls queue isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from on1y.auth.context import user_context
from on1y.models.enums import SourceType
from on1y.models.queue import QueueEnqueue


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ON1Y_AUTH_SECRET_KEY", "test-secret-key")
    from on1y.config import get_settings

    get_settings.cache_clear()
    return db


def test_pending_queue_scoped_per_user(isolated_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.user.accounts import UserStore

    storage = SqliteStorage(isolated_db)
    storage.initialize()
    store = UserStore(storage)
    alice = store.create_user(username="alice", password="password123")
    bob = store.create_user(username="bob", password="password456")

    url = "https://www.bilibili.com/video/BVshared"
    item = QueueEnqueue(url=url, source=SourceType.RSS, source_meta={"title": "t"})

    with user_context(alice.id):
        alice_id = storage.enqueue(item)
        assert storage.url_in_rss_queue(url) is True
        assert storage.count_pending_for_platform("bilibili", status="pending") >= 0

    with user_context(bob.id):
        assert storage.url_in_rss_queue(url) is False
        bob_id = storage.enqueue(item)
        assert storage.url_in_rss_queue(url) is True
        assert bob_id != alice_id

    with user_context(alice.id):
        claimed = storage.claim_next_pending()
        assert claimed is not None
        assert claimed.id == alice_id

    with user_context(bob.id):
        claimed = storage.claim_next_pending()
        assert claimed is not None
        assert claimed.id == bob_id

    storage.close()


def test_resolve_feeds_config_path_user2_empty_without_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings
    from on1y.user.feeds_config import resolve_feeds_config_path

    get_settings.cache_clear()
    settings = get_settings()

    global_feeds = tmp_path.parent / "config" / "feeds.yaml"
    # user 2 should not inherit global config/feeds.yaml
    with user_context(2):
        path = resolve_feeds_config_path(settings, user_id=2)
    assert path == tmp_path / "users" / "2" / "feeds.yaml"
    assert not path.is_file()
