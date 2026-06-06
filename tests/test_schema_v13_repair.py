"""Repair raw_items when schema_migrations says v11+ but UNIQUE(url) remains."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def broken_v11_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "broken.db"
    monkeypatch.setenv("ON1Y_DB_PATH", str(db))
    monkeypatch.setenv("ON1Y_DATA_DIR", str(tmp_path))
    from on1y.config import get_settings

    get_settings.cache_clear()

    import sqlite3

    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY);
        INSERT INTO schema_migrations (version) VALUES (12);
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        INSERT INTO users (id, username) VALUES (1, 'admin');
        CREATE TABLE themes (id INTEGER PRIMARY KEY, slug TEXT, name TEXT, is_active INTEGER);
        CREATE TABLE raw_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL,
            source TEXT NOT NULL,
            raw_title TEXT,
            body_text TEXT,
            content_type TEXT NOT NULL,
            extract_status TEXT NOT NULL,
            extract_error TEXT,
            word_count INTEGER,
            source_meta TEXT,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            theme_id INTEGER,
            theme_source TEXT NOT NULL DEFAULT 'llm',
            deleted_at TEXT,
            user_id INTEGER
        );
        """
    )
    conn.close()
    return db


def test_schema_v13_repairs_raw_items_unique(broken_v11_db: Path) -> None:
    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(broken_v11_db)
    conn = storage._connect()
    assert not storage._raw_items_has_per_user_url_unique(conn)
    storage._apply_schema_v11(conn)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='raw_items'"
    ).fetchone()
    assert row is not None
    assert "UNIQUE (user_id, url)" in str(row[0])
    storage.close()
