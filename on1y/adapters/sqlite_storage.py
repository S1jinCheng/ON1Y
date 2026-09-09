"""SQLite implementation of StoragePort with schema versioning."""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from on1y.config import PROJECT_ROOT, get_settings
from on1y.exceptions import StorageError
from on1y.knowledge.importance import importance_from_meta
from on1y.knowledge.read_state import read_at_from_meta, utc_now_iso, unread_sql
from on1y.knowledge.notes import has_user_note
from on1y.models.distill import DistilledItem
from on1y.models.enums import ExtractStatus, PendingStatus, SourceType
from on1y.models.queue import PendingUrl, QueueEnqueue
from on1y.models.raw import RawItem, RawItemCreate
from on1y.models.subtitle_queue import PendingSubtitle
from on1y.taxonomy.constants import DEFAULT_THEMES, OTHER_THEME_SLUG, slugify_theme_name
from on1y.utils.author_meta import author_fields_from_meta
from on1y.utils.published_at import published_at_iso
from on1y.utils.json_util import dumps_json, dumps_meta, loads_json_list, loads_meta

logger = logging.getLogger(__name__)


def _source_meta_int(meta: dict[str, Any], *keys: str) -> int | None:
    social_stats = meta.get("social_stats")
    if not isinstance(social_stats, dict):
        social_stats = {}
    for key in keys:
        value = _as_int_or_none(meta.get(key))
        if value is not None:
            return value
        value = _as_int_or_none(social_stats.get(key))
        if value is not None:
            return value
    return None


SCHEMA_VERSION = 22
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"
SCHEMA_V2_PATH = PROJECT_ROOT / "sql" / "schema_v2.sql"
SCHEMA_V3_PATH = PROJECT_ROOT / "sql" / "schema_v3.sql"
SCHEMA_V4_PATH = PROJECT_ROOT / "sql" / "schema_v4.sql"
SCHEMA_V5_PATH = PROJECT_ROOT / "sql" / "schema_v5.sql"
SCHEMA_V6_PATH = PROJECT_ROOT / "sql" / "schema_v6.sql"
SCHEMA_V7_PATH = PROJECT_ROOT / "sql" / "schema_v7.sql"
SCHEMA_V8_PATH = PROJECT_ROOT / "sql" / "schema_v8.sql"
SCHEMA_V9_PATH = PROJECT_ROOT / "sql" / "schema_v9.sql"
SCHEMA_V10_PATH = PROJECT_ROOT / "sql" / "schema_v10.sql"
SCHEMA_V11_PATH = PROJECT_ROOT / "sql" / "schema_v11.sql"
SCHEMA_V14_PATH = PROJECT_ROOT / "sql" / "schema_v14.sql"
SCHEMA_V15_PATH = PROJECT_ROOT / "sql" / "schema_v15.sql"
SCHEMA_V16_PATH = PROJECT_ROOT / "sql" / "schema_v16.sql"
SCHEMA_V17_PATH = PROJECT_ROOT / "sql" / "schema_v17.sql"
SCHEMA_V18_PATH = PROJECT_ROOT / "sql" / "schema_v18.sql"
SCHEMA_V19_PATH = PROJECT_ROOT / "sql" / "schema_v19.sql"
SCHEMA_V20_PATH = PROJECT_ROOT / "sql" / "schema_v20.sql"
SCHEMA_V21_PATH = PROJECT_ROOT / "sql" / "schema_v21.sql"
SCHEMA_V22_PATH = PROJECT_ROOT / "sql" / "schema_v22.sql"


def _as_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class SqliteStorage:
    """Thread-local connections per instance; suitable for single-worker Phase 1."""

    def __init__(self, db_path: Path | None = None) -> None:
        settings = get_settings()
        self._db_path = db_path or settings.db_path
        self._connection: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        if self._current_schema_version(conn) < SCHEMA_VERSION:
            self._apply_schema(conn)
        if self._current_schema_version(conn) >= 5:
            self.seed_default_themes(conn)
        elif self._current_schema_version(conn) >= 4:
            self.seed_default_themes_legacy(conn)
        self._ensure_fts_index(conn)
        if self._current_schema_version(conn) >= 9:
            from on1y.user.accounts import bootstrap_default_user

            bootstrap_default_user(self)
        conn.commit()

    def _ensure_fts_index(self, conn: sqlite3.Connection) -> None:
        if self._current_schema_version(conn) < 6:
            return
        from on1y.search.fts import fts_index_count, rebuild_knowledge_fts

        if fts_index_count(conn) == 0:
            rebuild_knowledge_fts(conn)

    def _touch_search_index(self, conn: sqlite3.Connection, raw_id: int) -> None:
        if self._current_schema_version(conn) < 6:
            return
        from on1y.search.fts import index_raw_item

        index_raw_item(conn, raw_id)

    def _delete_search_index(self, conn: sqlite3.Connection, raw_id: int) -> None:
        if self._current_schema_version(conn) < 6:
            return
        from on1y.search.fts import delete_fts_row

        delete_fts_row(conn, raw_id)

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._connection = sqlite3.connect(
                    self._db_path,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    check_same_thread=False,
                    timeout=30.0,
                )
            except sqlite3.OperationalError as exc:
                raise sqlite3.OperationalError(
                    f"cannot open database at {self._db_path}: {exc}"
                ) from exc
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            try:
                self._connection.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError as exc:
                raise sqlite3.OperationalError(
                    f"cannot enable WAL for {self._db_path} (check folder write permission): {exc}"
                ) from exc
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _current_schema_version(self, conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            return int(row["v"]) if row and row["v"] is not None else 0
        except sqlite3.OperationalError:
            return 0

    def _apply_schema(self, conn: sqlite3.Connection) -> None:
        current = self._current_schema_version(conn)
        if current < 1:
            if not SCHEMA_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_PATH}")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (1,),
            )
            logger.info("Applied schema version 1 to %s", self._db_path)
            current = 1
        if current < 2:
            if not SCHEMA_V2_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V2_PATH}")
            conn.executescript(SCHEMA_V2_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (2,),
            )
            logger.info("Applied schema version 2 to %s", self._db_path)
            current = 2
        if current < 3:
            if not SCHEMA_V3_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V3_PATH}")
            conn.executescript(SCHEMA_V3_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (3,),
            )
            logger.info("Applied schema version 3 to %s", self._db_path)
            current = 3
        if current < 4:
            if not SCHEMA_V4_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V4_PATH}")
            conn.executescript(SCHEMA_V4_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (4,),
            )
            logger.info("Applied schema version 4 to %s", self._db_path)
            current = 4
        if current < 5:
            if not SCHEMA_V5_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V5_PATH}")
            conn.executescript(SCHEMA_V5_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (5,),
            )
            logger.info("Applied schema version 5 to %s", self._db_path)
            self.seed_default_themes(conn)
            current = 5
        if current < 6:
            if not SCHEMA_V6_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V6_PATH}")
            conn.executescript(SCHEMA_V6_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (6,),
            )
            logger.info("Applied schema version 6 to %s", self._db_path)
            current = 6
        if current < 7:
            if not SCHEMA_V7_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V7_PATH}")
            conn.executescript(SCHEMA_V7_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (7,),
            )
            logger.info("Applied schema version 7 to %s", self._db_path)
            current = 7
        if current < 8:
            if not SCHEMA_V8_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V8_PATH}")
            conn.executescript(SCHEMA_V8_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (8,),
            )
            logger.info("Applied schema version 8 to %s", self._db_path)
            current = 8
        if current < 9:
            self._apply_schema_v9(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (9,),
            )
            logger.info("Applied schema version 9 to %s", self._db_path)
            current = 9
        if current < 10:
            if not SCHEMA_V10_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V10_PATH}")
            conn.executescript(SCHEMA_V10_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (10,),
            )
            logger.info("Applied schema version 10 to %s", self._db_path)
            current = 10
        if current < 11:
            self._apply_schema_v11(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (11,),
            )
            logger.info("Applied schema version 11 to %s", self._db_path)
            current = 11
        if current < 12:
            self._apply_schema_v12(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (12,),
            )
            logger.info("Applied schema version 12 to %s", self._db_path)
            current = 12
        if current < 13:
            if not self._raw_items_has_per_user_url_unique(conn):
                self._apply_schema_v11(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (13,),
            )
            logger.info("Applied schema version 13 to %s", self._db_path)
            current = 13
        if current < 14:
            if not SCHEMA_V14_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V14_PATH}")
            conn.executescript(SCHEMA_V14_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (14,),
            )
            logger.info("Applied schema version 14 to %s", self._db_path)
            current = 14
        if current < 15:
            if not SCHEMA_V15_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V15_PATH}")
            conn.executescript(SCHEMA_V15_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (15,),
            )
            logger.info("Applied schema version 15 to %s", self._db_path)
            current = 15
        if current < 16:
            if not SCHEMA_V16_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V16_PATH}")
            conn.executescript(SCHEMA_V16_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (16,),
            )
            logger.info("Applied schema version 16 to %s", self._db_path)
            current = 16
        if current < 17:
            if not SCHEMA_V17_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V17_PATH}")
            conn.executescript(SCHEMA_V17_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (17,),
            )
            logger.info("Applied schema version 17 to %s", self._db_path)
            current = 17
        if current < 18:
            if not SCHEMA_V18_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V18_PATH}")
            conn.executescript(SCHEMA_V18_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (18,),
            )
            logger.info("Applied schema version 18 to %s", self._db_path)
            current = 18
        if current < 19:
            if not SCHEMA_V19_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V19_PATH}")
            conn.executescript(SCHEMA_V19_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (19,),
            )
            logger.info("Applied schema version 19 to %s", self._db_path)
            current = 19
        if current < 20:
            if not SCHEMA_V20_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V20_PATH}")
            conn.executescript(SCHEMA_V20_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (20,),
            )
            logger.info("Applied schema version 20 to %s", self._db_path)
            current = 20
        if current < 21:
            if not SCHEMA_V21_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V21_PATH}")
            conn.executescript(SCHEMA_V21_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (21,),
            )
            logger.info("Applied schema version 21 to %s", self._db_path)

            current = 21
        if current < 22:
            if not SCHEMA_V22_PATH.is_file():
                raise StorageError(f"Schema file not found: {SCHEMA_V22_PATH}")
            conn.executescript(SCHEMA_V22_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (22,),
            )
            logger.info("Applied schema version 22 to %s", self._db_path)

    def _table_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def _column_exists(self, conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(r[1]) == column for r in rows)

    def _apply_schema_v9(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "users"):
            conn.executescript(
                """
                CREATE TABLE users (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    email           TEXT UNIQUE COLLATE NOCASE,
                    password_hash   TEXT NOT NULL,
                    display_name    TEXT NOT NULL DEFAULT '',
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE user_profiles (
                    user_id         INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    profile_json    TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE user_subscription_settings (
                    user_id         INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    settings_json   TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
        if not self._column_exists(conn, "raw_items", "user_id"):
            conn.execute("ALTER TABLE raw_items ADD COLUMN user_id INTEGER REFERENCES users(id)")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_raw_items_user_id ON raw_items (user_id)
            """
        )

    def _raw_items_has_per_user_url_unique(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='raw_items'"
        ).fetchone()
        if not row or not row[0]:
            return False
        return bool(re.search(r"UNIQUE\s*\(\s*user_id\s*,\s*url\s*\)", str(row[0]), re.I))

    def _apply_schema_v11(self, conn: sqlite3.Connection) -> None:
        """Rebuild raw_items: UNIQUE(user_id, url) instead of global UNIQUE(url)."""
        if self._raw_items_has_per_user_url_unique(conn):
            return

        has_creator = self._column_exists(conn, "raw_items", "creator_id")
        creator_def = (
            ",\n                    creator_id INTEGER REFERENCES creators(id)"
            if has_creator
            else ""
        )
        creator_cols = ", creator_id" if has_creator else ""
        creator_select = ", creator_id" if has_creator else ""
        creator_index = (
            "\n                CREATE INDEX IF NOT EXISTS idx_raw_items_creator_id"
            "\n                    ON raw_items (creator_id);"
            if has_creator
            else ""
        )

        conn.execute("UPDATE raw_items SET user_id = COALESCE(user_id, 1) WHERE user_id IS NULL")
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.executescript(
                f"""
                CREATE TABLE raw_items_v11 (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    url             TEXT NOT NULL,
                    platform        TEXT NOT NULL,
                    source          TEXT NOT NULL,
                    raw_title       TEXT,
                    body_text       TEXT,
                    content_type    TEXT NOT NULL CHECK (content_type IN ('video', 'article', 'unknown')),
                    extract_status  TEXT NOT NULL CHECK (extract_status IN ('ok', 'partial', 'failed')),
                    extract_error   TEXT,
                    word_count      INTEGER,
                    source_meta     TEXT,
                    ingested_at     TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    theme_id        INTEGER REFERENCES themes(id) ON DELETE SET NULL,
                    theme_source    TEXT NOT NULL DEFAULT 'llm',
                    deleted_at      TEXT,
                    user_id         INTEGER NOT NULL DEFAULT 1 REFERENCES users(id){creator_def},
                    UNIQUE (user_id, url)
                );

                INSERT INTO raw_items_v11 (
                    id, url, platform, source, raw_title, body_text,
                    content_type, extract_status, extract_error, word_count, source_meta,
                    ingested_at, updated_at, theme_id, theme_source, deleted_at, user_id{creator_cols}
                )
                SELECT
                    id, url, platform, source, raw_title, body_text,
                    content_type, extract_status, extract_error, word_count, source_meta,
                    ingested_at, updated_at, theme_id, theme_source, deleted_at,
                    COALESCE(user_id, 1){creator_select}
                FROM raw_items;

                DROP TABLE raw_items;
                ALTER TABLE raw_items_v11 RENAME TO raw_items;

                CREATE INDEX IF NOT EXISTS idx_raw_items_platform_ingested
                    ON raw_items (platform, ingested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_raw_items_source ON raw_items (source);
                CREATE INDEX IF NOT EXISTS idx_raw_items_theme ON raw_items (theme_id);
                CREATE INDEX IF NOT EXISTS idx_raw_items_deleted_at ON raw_items (deleted_at);
                CREATE INDEX IF NOT EXISTS idx_raw_items_user_id ON raw_items (user_id);{creator_index}
                """
            )
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

    def _per_user_url_unique(self, conn: sqlite3.Connection) -> bool:
        return self._raw_items_has_per_user_url_unique(conn)

    def _pending_urls_per_user(self, conn: sqlite3.Connection) -> bool:
        return self._current_schema_version(conn) >= 12

    def _pending_user_id(self, conn: sqlite3.Connection) -> int:
        if not self._pending_urls_per_user(conn):
            return 1
        from on1y.auth.context import get_effective_user_id

        return get_effective_user_id()

    def _pending_user_clause(
        self, conn: sqlite3.Connection, *, table_alias: str = ""
    ) -> tuple[str, list[Any]]:
        if not self._pending_urls_per_user(conn):
            return "", []
        prefix = f"{table_alias}." if table_alias else ""
        return f"{prefix}user_id = ?", [self._pending_user_id(conn)]

    def _apply_schema_v12(self, conn: sqlite3.Connection) -> None:
        """Rebuild pending_urls: UNIQUE(user_id, url, source) for per-user ingest queues."""
        if self._column_exists(conn, "pending_urls", "user_id"):
            return

        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.executescript(
                """
                CREATE TABLE pending_urls_v12 (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    url         TEXT NOT NULL,
                    source      TEXT NOT NULL CHECK (source IN (
                        'rss', 'bilibili_feed', 'youtube_feed', 'manual', 'chrome', 'api'
                    )),
                    source_meta TEXT,
                    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending', 'processing', 'done', 'failed'
                    )),
                    attempts    INTEGER NOT NULL DEFAULT 0,
                    error       TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
                    user_id     INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
                    UNIQUE (user_id, url, source)
                );

                INSERT INTO pending_urls_v12 (
                    id, url, source, source_meta, status, attempts, error,
                    created_at, updated_at, user_id
                )
                SELECT
                    id, url, source, source_meta, status, attempts, error,
                    created_at, updated_at, 1
                FROM pending_urls;

                DROP TABLE pending_urls;
                ALTER TABLE pending_urls_v12 RENAME TO pending_urls;

                CREATE INDEX IF NOT EXISTS idx_pending_urls_status_created
                    ON pending_urls (status, created_at);
                CREATE INDEX IF NOT EXISTS idx_pending_urls_user_status_created
                    ON pending_urls (user_id, status, created_at);
                """
            )
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

    def _user_scope_parts(self, conn: sqlite3.Connection) -> tuple[str, list[Any]]:
        if self._current_schema_version(conn) < 9:
            return "", []
        from on1y.auth.context import get_current_user_id, get_effective_user_id

        uid = get_current_user_id()
        if uid is None:
            uid = get_effective_user_id()
        return "r.user_id = ?", [uid]

    def _write_user_id(self, conn: sqlite3.Connection) -> int | None:
        if self._current_schema_version(conn) < 9:
            return None
        from on1y.auth.context import get_effective_user_id

        return get_effective_user_id()

    def _hotlist_query_parts(
        self,
        conn: sqlite3.Connection,
        *,
        collection: str | None,
        hotlist_date: str | None,
        hotlist_source: str | None = None,
    ) -> tuple[str, str, list[Any]]:
        """Extra JOIN fragment, WHERE suffix, and params for hot-list by day."""
        if (collection or "feed").strip().lower() != "hotlist":
            return ("", "", [])
        day = (hotlist_date or "").strip() or date.today().isoformat()
        source = (hotlist_source or "").strip()
        if self._current_schema_version(conn) >= 8:
            join_sql = " INNER JOIN hotlist_snapshots hs ON hs.raw_id = r.id "
            where_suffix = " AND hs.snapshot_date = ? "
            params: list[Any] = [day]
            if source:
                where_suffix += " AND hs.hotlist_source = ? "
                params.append(source)
            return (join_sql, where_suffix, params)
        params = [day]
        where_suffix = " AND json_extract(r.source_meta, '$.snapshot_date') = ? "
        if source:
            where_suffix += " AND json_extract(r.source_meta, '$.hotlist_source') = ? "
            params.append(source)
        return ("", where_suffix, params)

    def list_hotlist_dates(
        self,
        *,
        hotlist_source: str = "zhihu",
        limit: int = 120,
    ) -> list[str]:
        conn = self._connect()
        if self._current_schema_version(conn) >= 8:
            rows = conn.execute(
                """
                SELECT DISTINCT snapshot_date AS d
                FROM hotlist_snapshots
                WHERE hotlist_source = ?
                ORDER BY snapshot_date DESC
                LIMIT ?
                """,
                (hotlist_source, limit),
            ).fetchall()
            return [str(r["d"]) for r in rows if r["d"]]

        rows = conn.execute(
            """
            SELECT DISTINCT json_extract(r.source_meta, '$.snapshot_date') AS d
            FROM raw_items r
            WHERE COALESCE(json_extract(r.source_meta, '$.hotlist_source'), '') = ?
              AND r.deleted_at IS NULL
              AND d IS NOT NULL AND TRIM(d) != ''
            ORDER BY d DESC
            LIMIT ?
            """,
            (hotlist_source, limit),
        ).fetchall()
        return [str(r["d"]) for r in rows if r["d"]]

    def upsert_hotlist_snapshot(
        self,
        *,
        hotlist_source: str,
        snapshot_date: str,
        question_id: str,
        raw_id: int,
        heat_text: str | None = None,
        title: str = "",
        excerpt: str = "",
        sort_order: int = 0,
    ) -> None:
        conn = self._connect()
        if self._current_schema_version(conn) < 8:
            return
        conn.execute(
            """
            INSERT INTO hotlist_snapshots (
                hotlist_source, snapshot_date, question_id, raw_id,
                heat_text, title, excerpt, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hotlist_source, snapshot_date, question_id) DO UPDATE SET
                raw_id = excluded.raw_id,
                heat_text = excluded.heat_text,
                title = excluded.title,
                excerpt = excluded.excerpt,
                sort_order = excluded.sort_order
            """,
            (
                hotlist_source,
                snapshot_date,
                question_id,
                raw_id,
                heat_text,
                title,
                excerpt,
                sort_order,
            ),
        )
        conn.commit()

    @staticmethod
    def _collection_clause(collection: str | None) -> str:
        from on1y.hotlist.sql import is_feed_row_sql, is_hotlist_row_sql

        key = (collection or "feed").strip().lower()
        if key == "trash":
            return "r.deleted_at IS NOT NULL"
        if key == "hotlist":
            return f"r.deleted_at IS NULL AND {is_hotlist_row_sql('r')}"
        if key == "favorites":
            return (
                "r.deleted_at IS NULL AND "
                "COALESCE(CAST(json_extract(r.source_meta, '$.starred') AS INTEGER), 0) = 1"
            )
        if key == "unread":
            return f"r.deleted_at IS NULL AND {is_feed_row_sql('r')} AND {unread_sql('r')}"
        if key == "notes":
            from on1y.knowledge.notes import notes_collection_clause

            return notes_collection_clause("r")
        if key == "chats":
            from on1y.knowledge.chats import chats_collection_clause

            return chats_collection_clause("r")
        if key == "continue":
            return (
                f"r.deleted_at IS NULL AND {is_feed_row_sql('r')} AND "
                "TRIM(COALESCE(json_extract(r.source_meta, '$.last_opened_at'), '')) != ''"
            )
        return f"r.deleted_at IS NULL AND {is_feed_row_sql('r')}"

    def seed_default_themes_legacy(self, conn: sqlite3.Connection | None = None) -> None:
        """Seed for schema v4 without description columns."""
        db = conn or self._connect()
        for theme in DEFAULT_THEMES:
            db.execute(
                """
                INSERT INTO themes (slug, name_zh, name_en, sort_order)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    name_zh = excluded.name_zh,
                    name_en = excluded.name_en,
                    sort_order = excluded.sort_order
                """,
                (theme.slug, theme.name_zh, theme.name_en, theme.sort_order),
            )

    def seed_default_themes(self, conn: sqlite3.Connection | None = None) -> None:
        db = conn or self._connect()
        for theme in DEFAULT_THEMES:
            db.execute(
                """
                INSERT INTO themes (
                    slug, name_zh, name_en, sort_order,
                    description_zh, description_en, is_builtin
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    name_zh = excluded.name_zh,
                    name_en = excluded.name_en,
                    sort_order = excluded.sort_order,
                    description_zh = excluded.description_zh,
                    description_en = excluded.description_en,
                    is_builtin = excluded.is_builtin
                """,
                (
                    theme.slug,
                    theme.name_zh,
                    theme.name_en,
                    theme.sort_order,
                    theme.description_zh,
                    theme.description_en,
                    1 if theme.is_builtin else 0,
                ),
            )
        from on1y.taxonomy.constants import THEME_GUIDANCE_PATCHES

        for slug, patch in THEME_GUIDANCE_PATCHES.items():
            row = db.execute(
                "SELECT id, description_zh FROM themes WHERE slug = ? AND archived_at IS NULL",
                (slug,),
            ).fetchone()
            if row is None:
                continue
            if str(row["description_zh"] or "").strip():
                continue
            desc_zh = str(patch.get("description_zh") or "").strip()
            desc_en = str(patch.get("description_en") or "").strip()
            if not desc_zh:
                continue
            db.execute(
                """
                UPDATE themes SET description_zh = ?, description_en = ? WHERE id = ?
                """,
                (desc_zh, desc_en, int(row["id"])),
            )

    def enqueue(self, item: QueueEnqueue) -> int:
        url = str(item.url)
        with self.transaction() as conn:
            user_id = self._pending_user_id(conn)
            if self._pending_urls_per_user(conn):
                conn.execute(
                    """
                    INSERT INTO pending_urls (url, source, source_meta, status, user_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, url, source) DO UPDATE SET
                        updated_at = datetime('now'),
                        source_meta = excluded.source_meta
                    WHERE pending_urls.status IN ('failed', 'pending')
                    """,
                    (
                        url,
                        item.source.value,
                        dumps_meta(item.source_meta),
                        PendingStatus.PENDING.value,
                        user_id,
                    ),
                )
                row = conn.execute(
                    "SELECT id FROM pending_urls WHERE url = ? AND source = ? AND user_id = ?",
                    (url, item.source.value, user_id),
                ).fetchone()
            else:
                conn.execute(
                    """
                    INSERT INTO pending_urls (url, source, source_meta, status)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(url, source) DO UPDATE SET
                        updated_at = datetime('now'),
                        source_meta = excluded.source_meta
                    WHERE pending_urls.status IN ('failed', 'pending')
                    """,
                    (
                        url,
                        item.source.value,
                        dumps_meta(item.source_meta),
                        PendingStatus.PENDING.value,
                    ),
                )
                row = conn.execute(
                    "SELECT id FROM pending_urls WHERE url = ? AND source = ?",
                    (url, item.source.value),
                ).fetchone()
            if row is None:
                raise StorageError(f"Failed to enqueue URL: {url}")
            return int(row["id"])

    def claim_next_pending(self) -> PendingUrl | None:
        with self.transaction() as conn:
            user_clause, user_params = self._pending_user_clause(conn)
            where_user = f"AND {user_clause}" if user_clause else ""
            row = conn.execute(
                f"""
                SELECT id FROM pending_urls
                WHERE status = 'pending' {where_user}
                ORDER BY created_at ASC
                LIMIT 1
                """,
                user_params,
            ).fetchone()
            if row is None:
                return None
            pending_id = int(row["id"])
            updated = conn.execute(
                """
                UPDATE pending_urls
                SET status = 'processing',
                    attempts = attempts + 1,
                    updated_at = datetime('now')
                WHERE id = ? AND status = 'pending'
                """,
                (pending_id,),
            )
            if updated.rowcount == 0:
                return None
            return self._row_to_pending(
                conn.execute("SELECT * FROM pending_urls WHERE id = ?", (pending_id,)).fetchone()
            )

    def claim_next_pending_for_platform(self, platform: str) -> PendingUrl | None:
        from on1y.utils.platform import pending_url_platform_clause

        clause, params = pending_url_platform_clause(platform)
        with self.transaction() as conn:
            user_clause, user_params = self._pending_user_clause(conn)
            user_sql = f"AND {user_clause}" if user_clause else ""
            row = conn.execute(
                f"""
                SELECT id FROM pending_urls
                WHERE status = 'pending' AND {clause} {user_sql}
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (*params, *user_params),
            ).fetchone()
            if row is None:
                return None
            pending_id = int(row["id"])
            updated = conn.execute(
                """
                UPDATE pending_urls
                SET status = 'processing',
                    attempts = attempts + 1,
                    updated_at = datetime('now')
                WHERE id = ? AND status = 'pending'
                """,
                (pending_id,),
            )
            if updated.rowcount == 0:
                return None
            return self._row_to_pending(
                conn.execute("SELECT * FROM pending_urls WHERE id = ?", (pending_id,)).fetchone()
            )

    def count_pending_for_platform(self, platform: str, *, status: str = "pending") -> int:
        from on1y.utils.platform import pending_url_platform_clause

        clause, params = pending_url_platform_clause(platform)
        conn = self._connect()
        user_clause, user_params = self._pending_user_clause(conn)
        user_sql = f"AND {user_clause}" if user_clause else ""
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM pending_urls WHERE status = ? AND {clause} {user_sql}",
            (status, *params, *user_params),
        ).fetchone()
        return int(row["n"]) if row else 0

    def reclaim_stale_processing_jobs(self, *, older_than_minutes: int = 45) -> dict[str, int]:
        """Move stuck processing rows back to pending (killed worker / crashed pipeline)."""
        minutes = max(5, int(older_than_minutes))
        out = {"pending_urls": 0, "pending_subtitles": 0}
        with self.transaction() as conn:
            user_clause, user_params = self._pending_user_clause(conn)
            user_sql = f"AND {user_clause}" if user_clause else ""
            cur = conn.execute(
                f"""
                UPDATE pending_urls
                SET status = 'pending', updated_at = datetime('now')
                WHERE status = 'processing'
                  AND updated_at < datetime('now', ?)
                  {user_sql}
                """,
                (f"-{minutes} minutes", *user_params),
            )
            out["pending_urls"] = int(cur.rowcount or 0)
            cur2 = conn.execute(
                """
                UPDATE pending_subtitles
                SET status = 'pending', updated_at = datetime('now')
                WHERE status = 'processing'
                  AND updated_at < datetime('now', ?)
                """,
                (f"-{minutes} minutes",),
            )
            out["pending_subtitles"] = int(cur2.rowcount or 0)
        return out

    def mark_pending_done(self, pending_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE pending_urls
                SET status = 'done', error = NULL, updated_at = datetime('now')
                WHERE id = ?
                """,
                (pending_id,),
            )

    def mark_pending_failed(self, pending_id: int, error: str, *, retry: bool) -> None:
        status = PendingStatus.PENDING.value if retry else PendingStatus.FAILED.value
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE pending_urls
                SET status = ?, error = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (status, error[:2000], pending_id),
            )

    def upsert_raw_item(self, item: RawItemCreate) -> RawItem:
        from on1y.utils.author_meta import merge_author_meta

        existing = self.get_raw_by_url(item.url)
        source_meta = dict(item.source_meta or {})
        if existing and existing.source_meta:
            source_meta = merge_author_meta(existing.source_meta, source_meta)
        item = item.model_copy(update={"source_meta": source_meta})

        word_count = len(item.body_text.split()) if item.body_text else 0
        with self.transaction() as conn:
            user_id = self._write_user_id(conn)
            per_user_url = self._per_user_url_unique(conn)
            if user_id is not None:
                conflict = "(user_id, url)" if per_user_url else "(url)"
                conn.execute(
                    f"""
                    INSERT INTO raw_items (
                        url, platform, source, raw_title, body_text,
                        content_type, extract_status, extract_error,
                        word_count, source_meta, user_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT {conflict} DO UPDATE SET
                        platform = excluded.platform,
                        source = excluded.source,
                        raw_title = excluded.raw_title,
                        body_text = excluded.body_text,
                        content_type = excluded.content_type,
                        extract_status = excluded.extract_status,
                        extract_error = excluded.extract_error,
                        word_count = excluded.word_count,
                        source_meta = excluded.source_meta,
                        updated_at = datetime('now')
                    """,
                    (
                        item.url,
                        item.platform,
                        item.source.value,
                        item.raw_title,
                        item.body_text,
                        item.content_type.value,
                        item.extract_status.value,
                        item.extract_error,
                        word_count,
                        dumps_meta(item.source_meta),
                        user_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO raw_items (
                        url, platform, source, raw_title, body_text,
                        content_type, extract_status, extract_error,
                        word_count, source_meta
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        platform = excluded.platform,
                        source = excluded.source,
                        raw_title = excluded.raw_title,
                        body_text = excluded.body_text,
                        content_type = excluded.content_type,
                        extract_status = excluded.extract_status,
                        extract_error = excluded.extract_error,
                        word_count = excluded.word_count,
                        source_meta = excluded.source_meta,
                        updated_at = datetime('now')
                    """,
                    (
                        item.url,
                        item.platform,
                        item.source.value,
                        item.raw_title,
                        item.body_text,
                        item.content_type.value,
                        item.extract_status.value,
                        item.extract_error,
                        word_count,
                        dumps_meta(item.source_meta),
                    ),
                )
            if user_id is not None:
                row = conn.execute(
                    "SELECT * FROM raw_items WHERE url = ? AND user_id = ?",
                    (item.url, user_id),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM raw_items WHERE url = ?", (item.url,)).fetchone()
            if row is None:
                raise StorageError(f"Failed to upsert raw item: {item.url}")
            raw = self._row_to_raw(row)
            self._touch_search_index(conn, raw.id)
            return raw

    def get_raw_by_url(self, url: str) -> RawItem | None:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        if user_clause:
            row = conn.execute(
                f"SELECT * FROM raw_items r WHERE r.url = ? AND {user_clause}",
                (url, *user_params),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM raw_items WHERE url = ?", (url,)).fetchone()
        return self._row_to_raw(row) if row else None

    def get_raw_by_id(self, raw_id: int) -> RawItem | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM raw_items WHERE id = ?", (raw_id,)).fetchone()
        return self._row_to_raw(row) if row else None

    def get_raw_by_id_for_user(self, raw_id: int) -> RawItem | None:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        if user_clause:
            row = conn.execute(
                f"SELECT * FROM raw_items r WHERE r.id = ? AND {user_clause}",
                (raw_id, *user_params),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM raw_items WHERE id = ?", (raw_id,)).fetchone()
        return self._row_to_raw(row) if row else None

    def update_raw_url(self, raw_id: int, new_url: str) -> RawItem:
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE raw_items
                SET url = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_url, raw_id),
            )
            row = conn.execute("SELECT * FROM raw_items WHERE id = ?", (raw_id,)).fetchone()
        if row is None:
            raise StorageError(f"raw item not found: {raw_id}")
        return self._row_to_raw(row)

    def get_hotlist_raw_id(
        self,
        *,
        hotlist_source: str,
        question_id: str,
    ) -> int | None:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT raw_id FROM hotlist_snapshots
            WHERE hotlist_source = ? AND question_id = ?
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (hotlist_source, question_id),
        ).fetchone()
        return int(row["raw_id"]) if row else None

    def merge_source_meta(self, raw_id: int, patch: dict[str, Any]) -> None:
        raw = self.get_raw_by_id(raw_id)
        if raw is None:
            raise StorageError(f"raw item not found: {raw_id}")
        meta = dict(raw.source_meta or {})
        allow_empty = {"user_note_html", "annotated_body_html"}
        bool_keys = {"starred", "distill_pending"}
        for key, value in patch.items():
            if key == "importance":
                from on1y.knowledge.importance import normalize_importance

                stars = normalize_importance(value)
                if stars is None:
                    meta.pop("importance", None)
                else:
                    meta["importance"] = stars
                continue
            if key in bool_keys:
                meta[key] = bool(value)
                continue
            if key in allow_empty:
                meta[key] = "" if value is None else str(value)
                continue
            if value is not None and str(value).strip():
                meta[key] = value
        with self.transaction() as conn:
            conn.execute(
                "UPDATE raw_items SET source_meta = ?, updated_at = datetime('now') WHERE id = ?",
                (dumps_meta(meta), raw_id),
            )
            if "user_note_html" in patch:
                self._touch_search_index(conn, raw_id)

    def set_item_read_state(self, raw_id: int, *, read: bool) -> dict[str, Any]:
        raw = self.get_raw_by_id(raw_id)
        if raw is None:
            raise StorageError(f"raw item not found: {raw_id}")
        meta = dict(raw.source_meta or {})
        if read:
            meta["read_at"] = utc_now_iso()
        else:
            meta.pop("read_at", None)
        with self.transaction() as conn:
            conn.execute(
                "UPDATE raw_items SET source_meta = ?, updated_at = datetime('now') WHERE id = ?",
                (dumps_meta(meta), raw_id),
            )
        return {
            "raw_id": raw_id,
            "read_at": read_at_from_meta(meta),
            "is_read": read,
        }

    def touch_item_reading(self, raw_id: int) -> dict[str, Any]:
        """Mark read and update last_opened_at (link click or reader expand)."""
        raw = self.get_raw_by_id(raw_id)
        if raw is None:
            raise StorageError(f"raw item not found: {raw_id}")
        meta = dict(raw.source_meta or {})
        now = utc_now_iso()
        meta["last_opened_at"] = now
        meta["read_at"] = read_at_from_meta(meta) or now
        with self.transaction() as conn:
            conn.execute(
                "UPDATE raw_items SET source_meta = ?, updated_at = datetime('now') WHERE id = ?",
                (dumps_meta(meta), raw_id),
            )
        return {
            "raw_id": raw_id,
            "read_at": meta["read_at"],
            "last_opened_at": now,
            "is_read": True,
        }

    def list_pending_urls(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PendingUrl]:
        conn = self._connect()
        user_clause, user_params = self._pending_user_clause(conn)
        query = "SELECT * FROM pending_urls WHERE 1=1"
        params: list[Any] = list(user_params)
        if user_clause:
            query += f" AND {user_clause}"
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [self._row_to_pending(r) for r in rows]

    def count_pending_by_status(self) -> dict[str, int]:
        conn = self._connect()
        user_clause, user_params = self._pending_user_clause(conn)
        where_user = f"WHERE {user_clause}" if user_clause else ""
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS c FROM pending_urls {where_user} GROUP BY status",
            user_params,
        ).fetchall()
        counts = {str(r["status"]): int(r["c"]) for r in rows}
        for key in ("pending", "processing", "done", "failed"):
            counts.setdefault(key, 0)
        return counts

    def count_raw_items(self) -> int:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        if user_clause:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM raw_items r WHERE {user_clause}",
                user_params,
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM raw_items").fetchone()
        return int(row["c"]) if row else 0

    def count_distilled_items(self) -> int:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        try:
            if user_clause:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM distilled_items d
                    JOIN raw_items r ON r.id = d.raw_id
                    WHERE {user_clause}
                    """,
                    user_params,
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM distilled_items").fetchone()
            return int(row["c"]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def url_in_rss_queue(self, url: str) -> bool:
        from on1y.models.enums import SourceType

        conn = self._connect()
        user_clause, user_params = self._pending_user_clause(conn)
        user_sql = f"AND {user_clause}" if user_clause else ""
        row = conn.execute(
            f"""
            SELECT 1 FROM pending_urls
            WHERE url = ? AND source = ? AND status IN ('done', 'pending', 'processing')
            {user_sql}
            LIMIT 1
            """,
            (url, SourceType.RSS.value, *user_params),
        ).fetchone()
        return row is not None

    def list_raw_items(
        self,
        *,
        platform: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RawItem]:
        conn = self._connect()
        query = "SELECT * FROM raw_items WHERE 1=1"
        params: list[Any] = []
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY ingested_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [self._row_to_raw(r) for r in rows]

    def get_rss_feed_state(self, feed_url: str) -> tuple[str | None, str | None]:
        conn = self._connect()
        row = conn.execute(
            "SELECT last_entry_id, last_published FROM rss_feed_state WHERE feed_url = ?",
            (feed_url,),
        ).fetchone()
        if not row:
            return None, None
        return row["last_entry_id"], row["last_published"]

    def set_rss_feed_state(
        self,
        feed_url: str,
        *,
        last_entry_id: str | None,
        last_published: str | None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO rss_feed_state (feed_url, last_entry_id, last_published)
                VALUES (?, ?, ?)
                ON CONFLICT(feed_url) DO UPDATE SET
                    last_entry_id = excluded.last_entry_id,
                    last_published = excluded.last_published,
                    updated_at = datetime('now')
                """,
                (feed_url, last_entry_id, last_published),
            )

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def _row_to_pending(self, row: sqlite3.Row) -> PendingUrl:
        return PendingUrl(
            id=int(row["id"]),
            url=row["url"],
            source=SourceType(row["source"]),
            source_meta=loads_meta(row["source_meta"]),
            status=PendingStatus(row["status"]),
            attempts=int(row["attempts"]),
            error=row["error"],
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
        )

    def _row_to_raw(self, row: sqlite3.Row) -> RawItem:
        from on1y.models.enums import ContentType, ExtractStatus

        return RawItem(
            id=int(row["id"]),
            url=row["url"],
            platform=row["platform"],
            source=SourceType(row["source"]),
            raw_title=row["raw_title"],
            body_text=row["body_text"],
            content_type=ContentType(row["content_type"]),
            extract_status=ExtractStatus(row["extract_status"]),
            extract_error=row["extract_error"],
            word_count=row["word_count"],
            source_meta=loads_meta(row["source_meta"]),
            ingested_at=self._parse_dt(row["ingested_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
        )

    def list_raw_ids_without_distill(
        self, *, limit: int = 20, platform: str | None = None
    ) -> list[int]:
        conn = self._connect()
        platform_clause = ""
        params: list[object] = []
        if platform:
            platform_clause = "AND r.platform = ?"
            params.append(platform)
        rows = conn.execute(
            f"""
            SELECT r.id FROM raw_items r
            LEFT JOIN distilled_items d ON d.raw_id = r.id
            WHERE d.id IS NULL
              AND r.extract_status IN ('ok', 'partial')
              AND r.body_text IS NOT NULL
              AND length(trim(r.body_text)) > 50
              {platform_clause}
              AND (
                r.platform NOT IN ('youtube', 'bilibili')
                OR json_extract(r.source_meta, '$.subtitle_status') = 'ready'
              )
            ORDER BY r.ingested_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def _distill_eligibility_sql(
        self, conn: sqlite3.Connection, *, platform: str | None = None
    ) -> tuple[str, list[object]]:
        platform_clause = ""
        params: list[object] = []
        user_clause, user_params = self._user_scope_parts(conn)
        user_sql = f"AND {user_clause}" if user_clause else ""
        params.extend(user_params)
        if platform:
            platform_clause = "AND r.platform = ?"
            params.append(platform)
        where = f"""
            r.extract_status IN ('ok', 'partial')
              AND r.body_text IS NOT NULL
              AND length(trim(r.body_text)) > 50
              {user_sql}
              {platform_clause}
              AND (
                r.platform NOT IN ('youtube', 'bilibili')
                OR json_extract(r.source_meta, '$.subtitle_status') = 'ready'
              )
        """
        return where, params

    def list_raw_ids_eligible_for_distill(
        self, *, limit: int = 20, platform: str | None = None
    ) -> list[int]:
        conn = self._connect()
        where, params = self._distill_eligibility_sql(conn, platform=platform)
        rows = conn.execute(
            f"""
            SELECT r.id FROM raw_items r
            WHERE {where}
            ORDER BY r.ingested_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def list_raw_ids_needing_distill(
        self,
        *,
        prompt_version: str,
        limit: int = 20,
        platform: str | None = None,
    ) -> list[int]:
        """Undistilled first, then stale prompt_version; skip current version."""
        conn = self._connect()
        where, params = self._distill_eligibility_sql(conn, platform=platform)
        rows = conn.execute(
            f"""
            SELECT r.id FROM raw_items r
            LEFT JOIN distilled_items d ON d.raw_id = r.id
            WHERE {where}
              AND (
                d.id IS NULL
                OR d.prompt_version IS NULL
                OR d.prompt_version != ?
              )
            ORDER BY (d.id IS NULL) DESC, r.ingested_at DESC
            LIMIT ?
            """,
            (*params, prompt_version, limit),
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def count_raw_ids_needing_distill(
        self, *, prompt_version: str, platform: str | None = None
    ) -> int:
        conn = self._connect()
        where, params = self._distill_eligibility_sql(conn, platform=platform)
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM raw_items r
            LEFT JOIN distilled_items d ON d.raw_id = r.id
            WHERE {where}
              AND (
                d.id IS NULL
                OR d.prompt_version IS NULL
                OR d.prompt_version != ?
              )
            """,
            (*params, prompt_version),
        ).fetchone()
        return int(row["n"]) if row else 0

    def enqueue_subtitle_job(self, raw_id: int, url: str) -> int:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO pending_subtitles (raw_id, url, status)
                VALUES (?, ?, ?)
                ON CONFLICT(raw_id) DO UPDATE SET
                    url = excluded.url,
                    status = 'pending',
                    error = NULL,
                    attempts = 0,
                    updated_at = datetime('now')
                """,
                (raw_id, url, PendingStatus.PENDING.value),
            )
            row = conn.execute(
                "SELECT id FROM pending_subtitles WHERE raw_id = ?",
                (raw_id,),
            ).fetchone()
            if row is None:
                raise StorageError(f"Failed to enqueue subtitle job for raw_id={raw_id}")
            return int(row["id"])

    def claim_next_pending_subtitle(self, platform: str | None = None) -> PendingSubtitle | None:
        with self.transaction() as conn:
            if platform:
                row = conn.execute(
                    """
                    SELECT ps.id FROM pending_subtitles ps
                    JOIN raw_items r ON r.id = ps.raw_id
                    WHERE ps.status = 'pending' AND r.platform = ?
                    ORDER BY ps.created_at ASC
                    LIMIT 1
                    """,
                    (platform,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id FROM pending_subtitles
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT 1
                    """
                ).fetchone()
            if row is None:
                return None
            job_id = int(row["id"])
            updated = conn.execute(
                """
                UPDATE pending_subtitles
                SET status = 'processing',
                    attempts = attempts + 1,
                    updated_at = datetime('now')
                WHERE id = ? AND status = 'pending'
                """,
                (job_id,),
            )
            if updated.rowcount == 0:
                return None
            full = conn.execute(
                "SELECT * FROM pending_subtitles WHERE id = ?",
                (job_id,),
            ).fetchone()
            return self._row_to_pending_subtitle(full)

    def mark_subtitle_done(self, job_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE pending_subtitles
                SET status = 'done', error = NULL, updated_at = datetime('now')
                WHERE id = ?
                """,
                (job_id,),
            )

    def mark_subtitle_failed(self, job_id: int, error: str, *, retry: bool) -> None:
        status = PendingStatus.PENDING.value if retry else PendingStatus.FAILED.value
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE pending_subtitles
                SET status = ?, error = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (status, error[:2000], job_id),
            )

    def count_subtitles_by_status(self) -> dict[str, int]:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        if user_clause:
            rows = conn.execute(
                f"""
                SELECT ps.status, COUNT(*) AS c
                FROM pending_subtitles ps
                JOIN raw_items r ON r.id = ps.raw_id
                WHERE {user_clause}
                GROUP BY ps.status
                """,
                user_params,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM pending_subtitles GROUP BY status"
            ).fetchall()
        counts = {str(r["status"]): int(r["c"]) for r in rows}
        for key in ("pending", "processing", "done", "failed"):
            counts.setdefault(key, 0)
        return counts

    def count_pending_subtitles_for_platform(self, platform: str) -> int:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM pending_subtitles ps
            JOIN raw_items r ON r.id = ps.raw_id
            WHERE ps.status = 'pending' AND r.platform = ?
            """,
            (platform,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_video_raw_needing_subtitles(
        self, platform: str | None = None
    ) -> list[tuple[int, str]]:
        """
        Video rows without subtitle_status=ready and no active subtitle job.

        Platforms: YouTube and Bilibili (optionally filter to one).
        """
        conn = self._connect()
        platform_clause = ""
        params: tuple[object, ...] = ()
        if platform:
            platform_clause = "AND r.platform = ?"
            params = (platform,)
        rows = conn.execute(
            f"""
            SELECT r.id, r.url FROM raw_items r
            WHERE r.platform IN ('youtube', 'bilibili')
              {platform_clause}
              AND COALESCE(json_extract(r.source_meta, '$.subtitle_status'), '') != 'ready'
              AND NOT EXISTS (
                SELECT 1 FROM pending_subtitles ps
                WHERE ps.raw_id = r.id
                  AND ps.status IN ('pending', 'processing')
              )
            ORDER BY r.id ASC
            """,
            params,
        ).fetchall()
        return [(int(r["id"]), str(r["url"])) for r in rows]

    def list_youtube_raw_needing_subtitles(self) -> list[tuple[int, str]]:
        """Backward-compatible alias."""
        return self.list_video_raw_needing_subtitles()

    def update_raw_item_content(
        self,
        raw_id: int,
        *,
        body_text: str | None,
        raw_title: str | None,
        extract_status: ExtractStatus,
        extract_error: str | None,
        source_meta: dict[str, Any],
    ) -> None:
        word_count = len(body_text.split()) if body_text else 0
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE raw_items SET
                    body_text = ?,
                    raw_title = ?,
                    extract_status = ?,
                    extract_error = ?,
                    word_count = ?,
                    source_meta = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    body_text,
                    raw_title,
                    extract_status.value,
                    extract_error,
                    word_count,
                    dumps_meta(source_meta),
                    raw_id,
                ),
            )
            self._touch_search_index(conn, raw_id)

    def _row_to_pending_subtitle(self, row: sqlite3.Row | None) -> PendingSubtitle | None:
        if row is None:
            return None
        return PendingSubtitle(
            id=int(row["id"]),
            raw_id=int(row["raw_id"]),
            url=str(row["url"]),
            status=PendingStatus(row["status"]),
            attempts=int(row["attempts"]),
            error=row["error"],
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
        )

    def list_raw_urls(self, *, limit: int = 200) -> list[str]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT url FROM raw_items ORDER BY ingested_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [str(r["url"]) for r in rows]

    def get_distilled_by_raw_id(self, raw_id: int) -> Any:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM distilled_items WHERE raw_id = ?",
            (raw_id,),
        ).fetchone()
        return self._row_to_distilled(row) if row else None

    def upsert_distilled(
        self,
        *,
        raw_id: int,
        summary: str | None,
        key_points: list[str],
        topics: list[str],
        model: str | None,
        prompt_version: str | None,
        status: str,
        error: str | None,
        reader_text: str | None = None,
    ) -> int:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO distilled_items (
                    raw_id, summary, key_points, topics,
                    distill_status, distill_error, model, prompt_version, reader_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_id) DO UPDATE SET
                    summary = excluded.summary,
                    key_points = excluded.key_points,
                    topics = excluded.topics,
                    distill_status = excluded.distill_status,
                    distill_error = excluded.distill_error,
                    model = excluded.model,
                    prompt_version = excluded.prompt_version,
                    reader_text = COALESCE(excluded.reader_text, distilled_items.reader_text),
                    distilled_at = datetime('now')
                """,
                (
                    raw_id,
                    summary,
                    dumps_json(key_points),
                    dumps_json(topics),
                    status,
                    error,
                    model,
                    prompt_version,
                    reader_text,
                ),
            )
            row = conn.execute(
                "SELECT id FROM distilled_items WHERE raw_id = ?",
                (raw_id,),
            ).fetchone()
            if row is None:
                raise StorageError(f"Failed to upsert distilled for raw_id={raw_id}")
            self._touch_search_index(conn, raw_id)
            return int(row["id"])

    def ensure_tag(self, name: str, *, parent_id: int | None = None) -> int:
        import re

        name = name.strip()
        slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", name.lower()).strip("-") or "tag"
        with self.transaction() as conn:
            row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
            if row is not None:
                if parent_id is not None:
                    conn.execute(
                        "UPDATE tags SET parent_id = COALESCE(parent_id, ?) WHERE id = ?",
                        (parent_id, int(row["id"])),
                    )
                return int(row["id"])
            row = conn.execute("SELECT id FROM tags WHERE slug = ?", (slug,)).fetchone()
            if row is not None:
                if parent_id is not None:
                    conn.execute(
                        "UPDATE tags SET parent_id = COALESCE(parent_id, ?) WHERE id = ?",
                        (parent_id, int(row["id"])),
                    )
                return int(row["id"])
            conn.execute(
                "INSERT INTO tags (name, slug, parent_id) VALUES (?, ?, ?)",
                (name, slug, parent_id),
            )
            row = conn.execute("SELECT id FROM tags WHERE slug = ?", (slug,)).fetchone()
            if row is None:
                raise StorageError(f"Failed to ensure tag: {name}")
            return int(row["id"])

    def clear_item_tags(self, raw_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM item_tags WHERE raw_id = ?", (raw_id,))

    def clear_item_tags_by_source(self, raw_id: int, source: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM item_tags WHERE raw_id = ? AND source = ?",
                (raw_id, source),
            )

    def link_item_tag(
        self,
        raw_id: int,
        tag_id: int,
        *,
        confidence: float | None,
        source: str = "llm",
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO item_tags (raw_id, tag_id, confidence, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(raw_id, tag_id) DO UPDATE SET
                    confidence = excluded.confidence
                """,
                (raw_id, tag_id, confidence, source),
            )

    def ensure_flat_tag(self, name: str) -> int:
        """Dynamic tag — flat mesh, no parent hierarchy."""
        return self.ensure_tag(name, parent_id=None)

    def clear_item_themes(self, raw_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM item_themes WHERE raw_id = ?", (raw_id,))

    def link_item_theme(
        self,
        raw_id: int,
        theme_id: int,
        *,
        confidence: float | None,
        source: str = "llm",
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO item_themes (raw_id, theme_id, confidence, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(raw_id, theme_id) DO UPDATE SET
                    confidence = excluded.confidence,
                    source = excluded.source
                """,
                (raw_id, theme_id, confidence, source),
            )

    def get_theme_id_by_slug(self, slug: str) -> int | None:
        row = (
            self._connect()
            .execute(
                "SELECT id FROM themes WHERE slug = ? AND archived_at IS NULL",
                (slug.strip().lower(),),
            )
            .fetchone()
        )
        return int(row["id"]) if row else None

    def get_theme_by_id(self, theme_id: int) -> dict[str, Any] | None:
        row = (
            self._connect()
            .execute(
                "SELECT * FROM themes WHERE id = ?",
                (theme_id,),
            )
            .fetchone()
        )
        return dict(row) if row else None

    def list_active_themes(self) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT id, slug, name_zh, name_en, description_zh, description_en,
                   sort_order, is_builtin
            FROM themes
            WHERE archived_at IS NULL
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def list_themes_with_counts(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        from on1y.hotlist.constants import HOTLIST_THEME_SLUG
        from on1y.hotlist.sql import is_feed_row_sql

        conn = self._connect()
        archived_clause = "" if include_archived else "AND t.archived_at IS NULL"
        feed_only = f"AND r.deleted_at IS NULL AND {is_feed_row_sql('r')}"
        user_clause, user_params = self._user_scope_parts(conn)
        user_join = f" AND {user_clause}" if user_clause else ""
        rows = conn.execute(
            f"""
            SELECT
                t.id,
                t.slug,
                t.name_zh,
                t.name_en,
                t.description_zh,
                t.description_en,
                t.sort_order,
                t.is_builtin,
                t.archived_at,
                COUNT(DISTINCT r.id) AS item_count
            FROM themes t
            LEFT JOIN raw_items r ON r.theme_id = t.id {feed_only}{user_join}
            WHERE 1=1 {archived_clause} AND t.slug != ?
            GROUP BY t.id, t.slug, t.name_zh, t.name_en, t.description_zh,
                     t.description_en, t.sort_order, t.is_builtin, t.archived_at
            ORDER BY t.sort_order ASC, t.id ASC
            """,
            (*user_params, HOTLIST_THEME_SLUG),
        ).fetchall()
        return [dict(r) for r in rows]

    def create_theme(
        self,
        *,
        slug: str,
        name_zh: str,
        name_en: str,
        description_zh: str = "",
        description_en: str = "",
        sort_order: int | None = None,
        is_builtin: bool = False,
    ) -> dict[str, Any]:
        normalized_slug = slug.strip().lower() if slug.strip() else slugify_theme_name(name_zh)
        if not normalized_slug:
            raise StorageError("theme slug required")
        conn = self._connect()
        if sort_order is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 10 AS n FROM themes"
            ).fetchone()
            sort_order = int(row["n"]) if row else 10
        with self.transaction() as tx:
            tx.execute(
                """
                INSERT INTO themes (
                    slug, name_zh, name_en, sort_order,
                    description_zh, description_en, is_builtin
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_slug,
                    name_zh.strip(),
                    name_en.strip() or name_zh.strip(),
                    sort_order,
                    description_zh.strip(),
                    description_en.strip(),
                    1 if is_builtin else 0,
                ),
            )
        created = self.get_theme_id_by_slug(normalized_slug)
        if created is None:
            row = conn.execute("SELECT * FROM themes WHERE slug = ?", (normalized_slug,)).fetchone()
            return dict(row) if row else {}
        return self.get_theme_by_id(created) or {}

    def update_theme(
        self,
        theme_id: int,
        *,
        name_zh: str | None = None,
        name_en: str | None = None,
        description_zh: str | None = None,
        description_en: str | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any] | None:
        fields: list[str] = []
        params: list[Any] = []
        if name_zh is not None:
            fields.append("name_zh = ?")
            params.append(name_zh.strip())
        if name_en is not None:
            fields.append("name_en = ?")
            params.append(name_en.strip())
        if description_zh is not None:
            fields.append("description_zh = ?")
            params.append(description_zh.strip())
        if description_en is not None:
            fields.append("description_en = ?")
            params.append(description_en.strip())
        if sort_order is not None:
            fields.append("sort_order = ?")
            params.append(sort_order)
        if not fields:
            return self.get_theme_by_id(theme_id)
        fields.append("updated_at = datetime('now')")
        params.append(theme_id)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE themes SET {', '.join(fields)} WHERE id = ?",
                params,
            )
        return self.get_theme_by_id(theme_id)

    def set_theme_discovery_json(self, theme_id: int, discovery: dict[str, Any]) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE themes SET discovery_json = ?, updated_at = datetime('now') WHERE id = ?",
                (dumps_json(discovery), theme_id),
            )

    def get_theme_discovery_json(self, theme_id: int) -> dict[str, Any]:
        if not self._column_exists(self._connect(), "themes", "discovery_json"):
            return {}
        row = (
            self._connect()
            .execute(
                "SELECT discovery_json FROM themes WHERE id = ?",
                (theme_id,),
            )
            .fetchone()
        )
        if row is None:
            return {}
        return loads_meta(row["discovery_json"])

    def archive_theme(self, theme_id: int, *, reassign_to_other: bool = True) -> int:
        """Archive a theme; optionally move its items to「其他」. Returns items remapped."""
        theme = self.get_theme_by_id(theme_id)
        if theme is None:
            raise StorageError(f"theme not found: {theme_id}")
        if theme.get("archived_at"):
            raise StorageError(f"theme already archived: {theme_id}")
        if int(theme.get("is_builtin") or 0):
            raise StorageError("cannot archive built-in theme")
        other_id = self.get_theme_id_by_slug(OTHER_THEME_SLUG) if reassign_to_other else None
        raw_ids = self.list_raw_ids_by_theme(theme_id)
        remapped = 0
        with self.transaction() as conn:
            if reassign_to_other and other_id is not None and raw_ids:
                cur = conn.execute(
                    "UPDATE raw_items SET theme_id = ?, theme_source = 'remap' WHERE theme_id = ?",
                    (other_id, theme_id),
                )
                remapped = int(cur.rowcount or 0)
                conn.execute("DELETE FROM item_themes WHERE theme_id = ?", (theme_id,))
                for raw_id in raw_ids:
                    conn.execute(
                        """
                        INSERT INTO item_themes (raw_id, theme_id, confidence, source)
                        VALUES (?, ?, 1.0, 'remap')
                        ON CONFLICT(raw_id, theme_id) DO UPDATE SET
                            source = excluded.source,
                            confidence = excluded.confidence
                        """,
                        (raw_id, other_id),
                    )
                    self._touch_search_index(conn, raw_id)
            else:
                conn.execute("DELETE FROM item_themes WHERE theme_id = ?", (theme_id,))
            conn.execute(
                "UPDATE themes SET archived_at = datetime('now') WHERE id = ?",
                (theme_id,),
            )
        return remapped

    def detach_hotlist_item(self, raw_id: int) -> None:
        """Keep hot-list rows out of theme taxonomy."""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE raw_items SET theme_id = NULL, theme_source = '' WHERE id = ?",
                (raw_id,),
            )
            conn.execute("DELETE FROM item_themes WHERE raw_id = ?", (raw_id,))

    def reorder_themes(self, theme_ids: list[int]) -> None:
        """Persist sidebar order; ``theme_ids`` must list every active sidebar theme once."""
        active_rows = self.list_themes_with_counts()
        active_ids = sorted(int(r["id"]) for r in active_rows)
        ids = [int(i) for i in theme_ids]
        if sorted(ids) != active_ids:
            raise StorageError("theme_ids must include every active theme exactly once")
        with self.transaction() as conn:
            for index, theme_id in enumerate(ids):
                conn.execute(
                    "UPDATE themes SET sort_order = ?, updated_at = datetime('now') WHERE id = ?",
                    ((index + 1) * 10, theme_id),
                )

    def list_raw_ids_by_theme(
        self,
        theme_id: int,
        *,
        exclude_theme_sources: tuple[str, ...] | None = None,
        feed_only: bool = False,
        exclude_deleted: bool = False,
    ) -> list[int]:
        from on1y.hotlist.sql import is_feed_row_sql

        sql = "SELECT id FROM raw_items WHERE theme_id = ?"
        params: list[Any] = [theme_id]
        if exclude_deleted:
            sql += " AND deleted_at IS NULL"
        if feed_only:
            sql += f" AND {is_feed_row_sql('raw_items')}"
        if exclude_theme_sources:
            placeholders = ", ".join("?" * len(exclude_theme_sources))
            sql += f" AND theme_source NOT IN ({placeholders})"
            params.extend(exclude_theme_sources)
        sql += " ORDER BY id ASC"
        rows = self._connect().execute(sql, params).fetchall()
        return [int(r["id"]) for r in rows]

    def get_raw_theme_source(self, raw_id: int) -> str | None:
        row = (
            self._connect()
            .execute(
                "SELECT theme_source FROM raw_items WHERE id = ?",
                (raw_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return str(row["theme_source"]) if row["theme_source"] else None

    def set_item_theme(self, raw_id: int, theme_id: int, *, source: str = "llm") -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE raw_items SET theme_id = ?, theme_source = ? WHERE id = ?",
                (theme_id, source, raw_id),
            )
            conn.execute("DELETE FROM item_themes WHERE raw_id = ?", (raw_id,))
            conn.execute(
                """
                INSERT INTO item_themes (raw_id, theme_id, confidence, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(raw_id, theme_id) DO UPDATE SET source = excluded.source
                """,
                (raw_id, theme_id, 1.0, source),
            )

    def set_item_theme_by_slug(self, raw_id: int, slug: str, *, source: str = "llm") -> None:
        theme_id = self.get_theme_id_by_slug(slug.strip().lower())
        if theme_id is None:
            theme_id = self.get_theme_id_by_slug(OTHER_THEME_SLUG)
        if theme_id is None:
            return
        self.set_item_theme(raw_id, theme_id, source=source)

    def get_item_tag_names(self, raw_id: int) -> list[str]:
        rows = (
            self._connect()
            .execute(
                """
            SELECT t.name FROM item_tags it
            JOIN tags t ON t.id = it.tag_id
            WHERE it.raw_id = ?
            ORDER BY t.name ASC
            """,
                (raw_id,),
            )
            .fetchall()
        )
        return [str(r["name"]) for r in rows]

    def merge_extracted_tags(self, raw_id: int, tag_names: list[str]) -> None:
        self.clear_item_tags_by_source(raw_id, "extract")
        seen: set[str] = set()
        for name in tag_names:
            label = name.strip()
            if not label or label in seen:
                continue
            seen.add(label)
            tag_id = self.ensure_flat_tag(label)
            self.link_item_tag(raw_id, tag_id, confidence=1.0, source="extract")

    def merge_llm_tags(self, raw_id: int, tag_names: list[str]) -> None:
        conn = self._connect()
        row = conn.execute(
            "SELECT json_extract(source_meta, '$.author') AS author FROM raw_items WHERE id = ?",
            (raw_id,),
        ).fetchone()
        author_key = str(row["author"] or "").strip().casefold() if row else ""
        self.clear_item_tags_by_source(raw_id, "llm")
        seen: set[str] = set()
        for name in tag_names:
            label = name.strip()
            if not label or label in seen:
                continue
            if author_key and label.casefold() == author_key:
                continue
            seen.add(label)
            tag_id = self.ensure_flat_tag(label)
            self.link_item_tag(raw_id, tag_id, confidence=1.0, source="llm")

    def merge_user_tags(self, raw_id: int, tag_names: list[str]) -> None:
        seen = set(self.get_item_tag_names(raw_id))
        for name in tag_names:
            label = name.strip()
            if not label or label in seen:
                continue
            seen.add(label)
            tag_id = self.ensure_flat_tag(label)
            self.link_item_tag(raw_id, tag_id, confidence=1.0, source="user")

    def set_item_classification(
        self,
        raw_id: int,
        *,
        theme_slug: str | None = None,
        theme_slugs: list[str] | None = None,
        tag_names: list[str] | None = None,
        tags: list[str] | None = None,
        source: str = "manual",
    ) -> None:
        slug = theme_slug
        if not slug and theme_slugs:
            slug = theme_slugs[0] if theme_slugs else None
        if slug:
            self.set_item_theme_by_slug(raw_id, slug, source=source)
        names = tag_names if tag_names is not None else (tags or [])
        if source == "manual":
            self.clear_item_tags(raw_id)
            seen: set[str] = set()
            for name in names:
                label = name.strip()
                if not label or label in seen:
                    continue
                seen.add(label)
                tag_id = self.ensure_flat_tag(label)
                self.link_item_tag(raw_id, tag_id, confidence=1.0, source="user")
        else:
            self.merge_llm_tags(raw_id, names)
        conn = self._connect()
        self._touch_search_index(conn, raw_id)
        conn.commit()

    def record_theme_operation(
        self,
        *,
        op_type: str,
        source_theme_id: int | None,
        target_theme_ids: list[int],
        total_items: int,
        processed_items: int,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO theme_operations (
                    op_type, source_theme_id, target_theme_ids, metadata_json,
                    status, total_items, processed_items, completed_at
                ) VALUES (?, ?, ?, ?, 'done', ?, ?, datetime('now'))
                """,
                (
                    op_type,
                    source_theme_id,
                    dumps_json(target_theme_ids),
                    dumps_json(metadata or {}),
                    total_items,
                    processed_items,
                ),
            )
            row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
            return int(row["id"]) if row else 0

    def get_latest_absorb_operation(self, theme_id: int) -> dict[str, Any] | None:
        if not self._table_exists(self._connect(), "theme_operations"):
            return None
        row = (
            self._connect()
            .execute(
                """
            SELECT id, op_type, source_theme_id, target_theme_ids, metadata_json,
                   status, total_items, processed_items, created_at, completed_at
            FROM theme_operations
            WHERE op_type = 'absorb' AND source_theme_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
                (theme_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        data = dict(row)
        data["metadata"] = loads_meta(data.get("metadata_json"))
        return data

    def get_reader_content(self, raw_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT r.id, r.url, r.raw_title, r.body_text, r.platform, r.source_meta,
                   d.summary, d.reader_text
            FROM raw_items r
            LEFT JOIN distilled_items d ON d.raw_id = r.id
            WHERE r.id = ?
            """,
            (raw_id,),
        ).fetchone()
        if row is None:
            return None
        from on1y.utils.transcript_meta import classify_transcript, pick_single_transcript

        meta = loads_meta(row["source_meta"])
        author_info = author_fields_from_meta(meta)
        body_text = row["body_text"]
        reader_text = row["reader_text"]
        prefer = get_settings().content_locale
        if str(row["platform"]) == "economist":
            from on1y.hotlist.economist_urls import strip_legacy_economist_body

            base = (reader_text or body_text or "").strip()
            display_body = strip_legacy_economist_body(base)
        else:
            display_body = pick_single_transcript(body_text or "", prefer_lang=prefer)
        translated_body_text = str(meta.get("translated_body_text") or "").strip() or None
        transcript_kind = classify_transcript(display_body, prefer_lang=prefer)
        item_url = str(row["url"])
        if str(row["platform"]) == "economist":
            from on1y.hotlist.economist_urls import resolve_economist_epub_url

            item_url = resolve_economist_epub_url(item_url, meta)
        elif str(row["platform"]) == "obsidian":
            source_url = str(meta.get("obsidian_source_url") or "").strip()
            if source_url:
                item_url = source_url
        return {
            "raw_id": int(row["id"]),
            "url": item_url,
            "title": row["raw_title"],
            "platform": str(row["platform"]),
            "published_at": published_at_iso(meta),
            "duration_sec": _source_meta_int(meta, "duration_sec", "duration"),
            "like_count": _source_meta_int(meta, "like_count", "likes", "voteup_count"),
            "comment_count": _source_meta_int(meta, "comment_count", "comments", "reply_count"),
            "body_text": display_body,
            "raw_body_text": body_text,
            "summary": row["summary"],
            "reader_text": row["reader_text"],
            "user_note_html": str(meta.get("user_note_html") or ""),
            "annotated_body_html": str(meta.get("annotated_body_html") or ""),
            "clip_source": str(meta.get("clip_source") or "").strip() or None,
            "clip_title": str(meta.get("clip_title") or "").strip() or None,
            "clip_count": _as_int_or_none(meta.get("clip_count")),
            "extract_strategy": str(meta.get("extract_strategy") or "").strip() or None,
            "jina_markdown": str(meta.get("jina_markdown") or ""),
            "jina_markdown_length": _as_int_or_none(meta.get("jina_markdown_length")),
            "obsidian_uri": str(meta.get("obsidian_uri") or "").strip() or None,
            "obsidian_source_url": str(meta.get("obsidian_source_url") or "").strip() or None,
            "obsidian_path": str(meta.get("obsidian_path") or "").strip() or None,
            "obsidian_writeback_status": str(meta.get("obsidian_writeback_status") or "").strip()
            or None,
            "transcript_kind": transcript_kind,
            "translated_body_text": translated_body_text,
            "can_translate": transcript_kind == "en" and not translated_body_text,
            "is_conversation": bool(meta.get("conversation")),
            "telegram_messages": meta.get("telegram_messages")
            if isinstance(meta.get("telegram_messages"), list)
            else None,
            **author_info,
        }

    def _purge_raw_item_row(self, conn: sqlite3.Connection, raw_id: int) -> None:
        self._delete_search_index(conn, raw_id)
        conn.execute("DELETE FROM item_tags WHERE raw_id = ?", (raw_id,))
        conn.execute("DELETE FROM item_themes WHERE raw_id = ?", (raw_id,))
        conn.execute("DELETE FROM distilled_items WHERE raw_id = ?", (raw_id,))
        conn.execute(
            "DELETE FROM item_relations WHERE from_raw_id = ? OR to_raw_id = ?",
            (raw_id, raw_id),
        )
        conn.execute("DELETE FROM raw_items WHERE id = ?", (raw_id,))

    def _soft_delete_raw_row(self, conn: sqlite3.Connection, raw_id: int) -> bool:
        row = conn.execute(
            "SELECT id, deleted_at FROM raw_items WHERE id = ?",
            (raw_id,),
        ).fetchone()
        if row is None:
            return False
        if row["deleted_at"]:
            return True
        deleted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE raw_items SET deleted_at = ? WHERE id = ?",
            (deleted_at, raw_id),
        )
        self._delete_search_index(conn, raw_id)
        return True

    def delete_raw_item(self, raw_id: int) -> None:
        """Soft-delete, or permanently purge if already in trash."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id, deleted_at FROM raw_items WHERE id = ?",
                (raw_id,),
            ).fetchone()
            if row is None:
                raise StorageError(f"raw item not found: {raw_id}")
            if row["deleted_at"]:
                self._purge_raw_item_row(conn, raw_id)
            elif not self._soft_delete_raw_row(conn, raw_id):
                raise StorageError(f"raw item not found: {raw_id}")

    def delete_raw_items(self, raw_ids: list[int]) -> dict[str, int]:
        """Soft-delete multiple items. Returns deleted / not_found counts."""
        unique: list[int] = []
        seen: set[int] = set()
        for value in raw_ids:
            rid = int(value)
            if rid not in seen:
                seen.add(rid)
                unique.append(rid)
        deleted = 0
        not_found = 0
        with self.transaction() as conn:
            for raw_id in unique:
                row = conn.execute(
                    "SELECT id, deleted_at FROM raw_items WHERE id = ?",
                    (raw_id,),
                ).fetchone()
                if row is None:
                    not_found += 1
                    continue
                if row["deleted_at"]:
                    self._purge_raw_item_row(conn, raw_id)
                elif self._soft_delete_raw_row(conn, raw_id):
                    pass
                else:
                    not_found += 1
                    continue
                deleted += 1
        return {"deleted": deleted, "not_found": not_found}

    def restore_raw_item(self, raw_id: int) -> bool:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM raw_items WHERE id = ? AND deleted_at IS NOT NULL",
                (raw_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                "UPDATE raw_items SET deleted_at = NULL WHERE id = ?",
                (raw_id,),
            )
            if self._current_schema_version(conn) >= 6:
                from on1y.search.fts import index_raw_item

                index_raw_item(conn, raw_id)
            return True

    def restore_raw_items(self, raw_ids: list[int]) -> dict[str, int]:
        restored = 0
        not_found = 0
        with self.transaction() as conn:
            for raw_id in raw_ids:
                row = conn.execute(
                    "SELECT id FROM raw_items WHERE id = ? AND deleted_at IS NOT NULL",
                    (int(raw_id),),
                ).fetchone()
                if row is None:
                    not_found += 1
                    continue
                conn.execute(
                    "UPDATE raw_items SET deleted_at = NULL WHERE id = ?",
                    (int(raw_id),),
                )
                if self._current_schema_version(conn) >= 6:
                    from on1y.search.fts import index_raw_item

                    index_raw_item(conn, int(raw_id))
                restored += 1
        return {"restored": restored, "not_found": not_found}

    def purge_raw_item(self, raw_id: int) -> bool:
        """Permanently remove a trashed item."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM raw_items WHERE id = ? AND deleted_at IS NOT NULL",
                (raw_id,),
            ).fetchone()
            if row is None:
                return False
            self._purge_raw_item_row(conn, raw_id)
            return True

    def count_collection_items(
        self,
        collection: str,
        *,
        hotlist_date: str | None = None,
        hotlist_source: str | None = None,
    ) -> int:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        user_filter = f" AND {user_clause}" if user_clause else ""
        coll = collection.strip().lower()
        if coll == "hotlist":
            join_sql, day_where, day_params = self._hotlist_query_parts(
                conn,
                collection="hotlist",
                hotlist_date=hotlist_date,
                hotlist_source=hotlist_source,
            )
            clause = self._collection_clause(collection)
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM raw_items r {join_sql} WHERE {clause}{day_where}{user_filter}",
                (*day_params, *user_params),
            ).fetchone()
            return int(row["n"]) if row else 0
        clause = self._collection_clause(collection)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM raw_items r WHERE {clause}{user_filter}",
            user_params,
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_telegram_chats(self) -> list[dict[str, Any]]:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        user_filter = f" AND {user_clause}" if user_clause else ""
        rows = conn.execute(
            f"""
            SELECT
                json_extract(r.source_meta, '$.telegram_chat_id') AS chat_id,
                json_extract(r.source_meta, '$.telegram_chat') AS chat_name,
                json_extract(r.source_meta, '$.telegram_chat_type') AS chat_type,
                COUNT(*) AS session_count,
                MAX(CAST(json_extract(r.source_meta, '$.telegram_end_ts') AS REAL)) AS last_ts
            FROM raw_items r
            WHERE r.deleted_at IS NULL
              AND LOWER(r.platform) = 'telegram'
              {user_filter}
            GROUP BY chat_id, chat_name, chat_type
            ORDER BY last_ts DESC
            """,
            user_params,
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "chat_id": str(row["chat_id"] or ""),
                    "chat_name": str(row["chat_name"] or ""),
                    "chat_type": str(row["chat_type"] or ""),
                    "session_count": int(row["session_count"] or 0),
                    "last_ts": float(row["last_ts"] or 0),
                }
            )
        return out

    def list_dynamic_tags_with_counts(self, *, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._connect()
        user_clause, user_params = self._user_scope_parts(conn)
        user_join = f" AND {user_clause}" if user_clause else ""
        rows = conn.execute(
            f"""
            SELECT
                t.id,
                t.name,
                t.slug,
                COUNT(DISTINCT it.raw_id) AS item_count
            FROM tags t
            INNER JOIN item_tags it ON it.tag_id = t.id
            INNER JOIN raw_items r ON r.id = it.raw_id{user_join}
            GROUP BY t.id, t.name, t.slug
            ORDER BY item_count DESC, t.name ASC
            LIMIT ?
            """,
            (*user_params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_relations_from(self, raw_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM item_relations WHERE from_raw_id = ? AND source = 'llm'",
                (raw_id,),
            )

    def add_relation(
        self,
        *,
        from_raw_id: int,
        to_raw_id: int,
        relation_type: str,
        note: str | None,
        confidence: float | None,
        source: str = "llm",
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO item_relations (
                    from_raw_id, to_raw_id, relation_type, note, confidence, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(from_raw_id, to_raw_id, relation_type) DO UPDATE SET
                    note = excluded.note,
                    confidence = excluded.confidence
                """,
                (from_raw_id, to_raw_id, relation_type, note, confidence, source),
            )

    def list_item_relations(self, raw_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        uid = self._write_user_id(conn)
        scoped = " AND fr.user_id = ? AND tr.user_id = ?" if uid is not None else ""
        rows = conn.execute(
            f"""
            SELECT
                ir.id,
                ir.from_raw_id,
                ir.to_raw_id,
                ir.relation_type,
                ir.confidence,
                ir.note,
                ir.source,
                ir.created_at,
                fr.raw_title AS from_title,
                fr.url AS from_url,
                fr.platform AS from_platform,
                tr.raw_title AS to_title,
                tr.url AS to_url,
                tr.platform AS to_platform
            FROM item_relations ir
            JOIN raw_items fr ON fr.id = ir.from_raw_id
            JOIN raw_items tr ON tr.id = ir.to_raw_id
            WHERE (ir.from_raw_id = ? OR ir.to_raw_id = ?)
              AND fr.deleted_at IS NULL
              AND tr.deleted_at IS NULL
              {scoped}
            ORDER BY ir.created_at DESC, ir.id DESC
            """,
            (raw_id, raw_id, uid, uid) if uid is not None else (raw_id, raw_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_relation(self, relation_id: int, *, raw_id: int | None = None) -> bool:
        with self.transaction() as conn:
            uid = self._write_user_id(conn)
            params: list[Any] = [relation_id]
            raw_guard = ""
            if raw_id is not None:
                raw_guard = " AND (ir.from_raw_id = ? OR ir.to_raw_id = ?)"
                params.extend([raw_id, raw_id])
            user_guard = ""
            if uid is not None:
                user_guard = (
                    " AND EXISTS (SELECT 1 FROM raw_items r WHERE r.id = ir.from_raw_id "
                    "AND r.user_id = ?)"
                )
                params.append(uid)
            row = conn.execute(
                f"""
                SELECT ir.id
                FROM item_relations ir
                WHERE ir.id = ?{raw_guard}{user_guard}
                """,
                params,
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM item_relations WHERE id = ?", (relation_id,))
            return True

    def upsert_obsidian_registry(
        self,
        *,
        raw_id: int,
        vault_path: str,
        rel_path: str,
        content_hash: str,
        mtime: float | None,
    ) -> int:
        with self.transaction() as conn:
            user_id = self._write_user_id(conn) or 1
            conn.execute(
                """
                INSERT INTO obsidian_note_registry (
                    user_id, vault_path, rel_path, content_hash, raw_id, mtime
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, vault_path, rel_path) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    raw_id = excluded.raw_id,
                    mtime = excluded.mtime,
                    updated_at = datetime('now')
                """,
                (user_id, vault_path, rel_path, content_hash, raw_id, mtime),
            )
            row = conn.execute(
                """
                SELECT id FROM obsidian_note_registry
                WHERE user_id = ? AND vault_path = ? AND rel_path = ?
                """,
                (user_id, vault_path, rel_path),
            ).fetchone()
            if row is None:
                raise StorageError("failed to upsert obsidian registry")
            return int(row["id"])

    def get_obsidian_registry_by_raw_id(self, raw_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        uid = self._write_user_id(conn)
        user_guard = " AND rr.user_id = ?" if uid is not None else ""
        params: list[Any] = [raw_id]
        if uid is not None:
            params.append(uid)
        row = conn.execute(
            f"""
            SELECT rr.*
            FROM obsidian_note_registry rr
            WHERE rr.raw_id = ?{user_guard}
            ORDER BY rr.updated_at DESC, rr.id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        return dict(row) if row else None

    def enqueue_obsidian_writeback(
        self,
        *,
        target_rel_path: str,
        content_md: str,
        block_anchor: str | None = None,
        link_raw_id: int | None = None,
    ) -> dict[str, Any]:
        with self.transaction() as conn:
            user_id = self._write_user_id(conn) or 1
            row = None
            if link_raw_id is not None:
                row = conn.execute(
                    """
                    SELECT id FROM obsidian_writeback_queue
                    WHERE user_id = ? AND target_rel_path = ? AND link_raw_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (user_id, target_rel_path, link_raw_id),
                ).fetchone()
            if row is not None:
                queue_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE obsidian_writeback_queue
                    SET block_anchor = ?,
                        content_md = ?,
                        status = 'pending',
                        last_error = NULL,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (block_anchor, content_md, queue_id),
                )
                row = conn.execute(
                    "SELECT * FROM obsidian_writeback_queue WHERE id = ?",
                    (queue_id,),
                ).fetchone()
            else:
                cur = conn.execute(
                    """
                    INSERT INTO obsidian_writeback_queue (
                        user_id, target_rel_path, block_anchor, content_md, link_raw_id, status
                    ) VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (user_id, target_rel_path, block_anchor, content_md, link_raw_id),
                )
                row = conn.execute(
                    "SELECT * FROM obsidian_writeback_queue WHERE id = ?",
                    (int(cur.lastrowid),),
                ).fetchone()
            if row is None:
                raise StorageError("failed to enqueue obsidian writeback")
            return dict(row)

    def list_obsidian_writeback_queue(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        uid = self._write_user_id(conn)
        where = ["1=1"]
        params: list[Any] = []
        if status:
            where.append("q.status = ?")
            params.append(status.strip().lower())
        if uid is not None:
            where.append("q.user_id = ?")
            params.append(uid)
        rows = conn.execute(
            f"""
            SELECT q.*
            FROM obsidian_writeback_queue q
            WHERE {" AND ".join(where)}
            ORDER BY q.created_at DESC, q.id DESC
            LIMIT ?
            """,
            (*params, max(1, int(limit))),
        ).fetchall()
        return [dict(r) for r in rows]

    def claim_pending_obsidian_writeback(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.transaction() as conn:
            uid = self._write_user_id(conn)
            where = ["q.status = 'pending'"]
            params: list[Any] = []
            if uid is not None:
                where.append("q.user_id = ?")
                params.append(uid)
            rows = conn.execute(
                f"""
                SELECT q.*
                FROM obsidian_writeback_queue q
                WHERE {" AND ".join(where)}
                ORDER BY q.created_at ASC, q.id ASC
                LIMIT ?
                """,
                (*params, max(1, int(limit))),
            ).fetchall()
            ids = [int(r["id"]) for r in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"""
                    UPDATE obsidian_writeback_queue
                    SET status = 'processing', last_error = NULL
                    WHERE id IN ({placeholders})
                    """,
                    ids,
                )
                rows = conn.execute(
                    f"""
                    SELECT * FROM obsidian_writeback_queue
                    WHERE id IN ({placeholders})
                    ORDER BY created_at ASC, id ASC
                    """,
                    ids,
                ).fetchall()
            return [dict(r) for r in rows]

    def mark_obsidian_writeback_status(
        self,
        queue_id: int,
        *,
        status: str,
        last_error: str | None = None,
        applied_at: str | None = None,
    ) -> None:
        normalized = (status or "").strip().lower()
        if normalized not in {"pending", "processing", "applied", "failed", "skipped"}:
            normalized = "failed"
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE obsidian_writeback_queue
                SET status = ?,
                    last_error = ?,
                    applied_at = COALESCE(?, applied_at),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (normalized, (last_error or "").strip() or None, applied_at, queue_id),
            )

    def list_distilled_summary(
        self,
        *,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT d.id, d.raw_id, d.summary, d.distill_status, d.distilled_at,
                   r.url, r.raw_title, r.platform
            FROM distilled_items d
            JOIN raw_items r ON r.id = d.raw_id
            ORDER BY d.distilled_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_tags_with_counts(self) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT
                t.id,
                t.name,
                t.slug,
                t.parent_id,
                COUNT(DISTINCT it.raw_id) AS item_count
            FROM tags t
            LEFT JOIN item_tags it ON it.tag_id = t.id
            GROUP BY t.id, t.name, t.slug, t.parent_id
            ORDER BY t.name ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def search_knowledge_items(
        self,
        *,
        query: str,
        limit: int = 40,
        offset: int = 0,
        platform: str | None = None,
        source: str | None = None,
        tag_ids: list[int] | None = None,
        theme_id: int | None = None,
        creator_key: str | None = None,
        collection: str | None = None,
        hotlist_date: str | None = None,
        hotlist_source: str | None = None,
        feed_date: str | None = None,
        unread_only: bool = False,
        min_importance: int | None = None,
    ) -> dict[str, Any]:
        """BM25-ranked full-text search with snippets."""
        from on1y.search.fts import search_knowledge_fts

        conn = self._connect()
        if self._current_schema_version(conn) < 6:
            items = self.list_knowledge_items(
                limit=limit,
                offset=offset,
                platform=platform,
                source=source,
                query=query,
                tag_ids=tag_ids,
                theme_id=theme_id,
                creator_key=creator_key,
                collection=collection,
                hotlist_date=hotlist_date,
                hotlist_source=hotlist_source,
                feed_date=feed_date,
                unread_only=unread_only,
                min_importance=min_importance,
            )
            return {"items": items, "total": len(items), "engine": "like"}

        coll_key = (collection or "feed").strip().lower()
        collection_sql = self._collection_clause_for_conn(conn, collection)
        if unread_only and coll_key == "feed":
            collection_sql = f"({collection_sql}) AND {unread_sql('r')}"
        if min_importance is not None and coll_key == "feed":
            from on1y.knowledge.importance import importance_min_sql

            collection_sql = (
                f"({collection_sql}) AND {importance_min_sql('r', minimum=min_importance)}"
            )
        user_clause, user_params = self._user_scope_parts(conn)
        if user_clause:
            collection_sql = f"({collection_sql}) AND {user_clause}"
        collection_params: list[Any] = list(user_params) if user_params else []
        if min_importance is not None and coll_key == "feed":
            collection_params.append(int(min_importance))
        hits, total = search_knowledge_fts(
            conn,
            user_query=query,
            limit=limit,
            offset=offset,
            platform=platform,
            source=source,
            theme_id=None if coll_key == "hotlist" else theme_id,
            tag_ids=tag_ids,
            collection_sql=collection_sql,
            collection_params=collection_params or None,
        )
        if not hits:
            return {"items": [], "total": 0, "engine": "fts5"}

        raw_ids = [int(h["raw_id"]) for h in hits]
        if creator_key and creator_key.strip() and coll_key != "hotlist":
            from on1y.knowledge.creators import creator_filter_sql

            clause, creator_params = creator_filter_sql(creator_key.strip())
            id_ph = ",".join("?" for _ in raw_ids)
            allowed = {
                int(r["id"])
                for r in conn.execute(
                    f"SELECT r.id FROM raw_items r WHERE r.id IN ({id_ph}) AND {clause}",
                    (*raw_ids, *creator_params),
                ).fetchall()
            }
            raw_ids = [rid for rid in raw_ids if rid in allowed]
            hits = [h for h in hits if int(h["raw_id"]) in allowed]
            total = len(raw_ids)
        if feed_date and feed_date.strip() and coll_key == "feed":
            from on1y.knowledge.feed_dates import feed_date_where_clause

            clause, date_params = feed_date_where_clause(feed_date.strip())
            id_ph = ",".join("?" for _ in raw_ids)
            allowed = {
                int(r["id"])
                for r in conn.execute(
                    f"SELECT r.id FROM raw_items r WHERE r.id IN ({id_ph}) AND {clause}",
                    (*raw_ids, *date_params),
                ).fetchall()
            }
            raw_ids = [rid for rid in raw_ids if rid in allowed]
            hits = [h for h in hits if int(h["raw_id"]) in allowed]
            total = len(raw_ids)
        if unread_only and coll_key == "feed" and raw_ids:
            clause = unread_sql("r")
            id_ph = ",".join("?" for _ in raw_ids)
            allowed = {
                int(r["id"])
                for r in conn.execute(
                    f"SELECT r.id FROM raw_items r WHERE r.id IN ({id_ph}) AND {clause}",
                    raw_ids,
                ).fetchall()
            }
            raw_ids = [rid for rid in raw_ids if rid in allowed]
            hits = [h for h in hits if int(h["raw_id"]) in allowed]
            total = len(raw_ids)
        if min_importance is not None and coll_key == "feed" and raw_ids:
            from on1y.knowledge.importance import importance_min_sql

            clause = importance_min_sql("r", minimum=min_importance)
            id_ph = ",".join("?" for _ in raw_ids)
            allowed = {
                int(r["id"])
                for r in conn.execute(
                    f"SELECT r.id FROM raw_items r WHERE r.id IN ({id_ph}) AND {clause}",
                    (*raw_ids, int(min_importance)),
                ).fetchall()
            }
            raw_ids = [rid for rid in raw_ids if rid in allowed]
            hits = [h for h in hits if int(h["raw_id"]) in allowed]
            total = len(raw_ids)
        if not raw_ids:
            return {"items": [], "total": 0, "engine": "fts5"}

        placeholders = ",".join("?" for _ in raw_ids)
        user_clause, user_params = self._user_scope_parts(conn)
        user_filter = f" AND {user_clause}" if user_clause else ""
        rows = conn.execute(
            f"""
            SELECT
                r.id AS raw_id,
                r.url,
                r.raw_title,
                r.platform,
                r.source,
                r.content_type,
                r.ingested_at,
                r.source_meta,
                r.theme_id,
                d.summary,
                d.topics,
                d.prompt_version,
                d.distill_status
            FROM raw_items r
            LEFT JOIN distilled_items d ON d.raw_id = r.id
            WHERE r.id IN ({placeholders}){user_filter}
            """,
            (*raw_ids, *user_params),
        ).fetchall()
        row_by_id = {int(r["raw_id"]): r for r in rows}
        ordered_rows = [row_by_id[rid] for rid in raw_ids if rid in row_by_id]
        if coll_key == "hotlist" and hotlist_date:
            _join_sql, _day_where, day_params = self._hotlist_query_parts(
                conn,
                collection="hotlist",
                hotlist_date=hotlist_date,
                hotlist_source=hotlist_source,
            )
            if day_params:
                source_clause = ""
                params = list(day_params)
                if hotlist_source and hotlist_source.strip():
                    source_clause = " AND hotlist_source = ? "
                    params.append(hotlist_source.strip())
                allowed = {
                    int(r["raw_id"])
                    for r in conn.execute(
                        f"""
                        SELECT raw_id FROM hotlist_snapshots
                        WHERE snapshot_date = ?{source_clause}
                        """,
                        params,
                    ).fetchall()
                }
                ordered_rows = [
                    row_by_id[rid] for rid in raw_ids if rid in allowed and rid in row_by_id
                ]
                total = len(ordered_rows)
        items = self._assemble_knowledge_items(ordered_rows)
        hit_map = {int(h["raw_id"]): h for h in hits}
        for item in items:
            hit = hit_map.get(int(item["raw_id"]))
            if not hit:
                continue
            item["search_rank"] = hit.get("search_rank")
            item["search_snippet"] = hit.get("search_snippet")
            item["search_title_html"] = hit.get("search_title_html")
            item["search_summary_html"] = hit.get("search_summary_html")
        return {"items": items, "total": total, "engine": "fts5"}

    def list_subscribed_creators(self, *, enrich_avatars: bool = False) -> list[dict[str, Any]]:
        """Creators from subscription feeds + Bilibili follows in the library."""
        from on1y.knowledge.creators import (
            bilibili_following_groups,
            discover_twitter_author_groups,
            discover_zhihu_person_groups,
            finalize_creator_sidebar_rows,
            normalize_twitter_author_url,
            normalize_zhihu_author_url,
            subscription_feed_groups,
            zhihu_author_url,
        )
        from on1y.utils.author_meta import pick_better_avatar, resolve_author_avatar
        from on1y.utils.bilibili_author import enrich_bilibili_author_meta
        from on1y.utils.youtube_author import enrich_youtube_author_meta

        conn = self._connect()
        groups = subscription_feed_groups()
        bili_follow_groups = bilibili_following_groups()
        for key, meta in bili_follow_groups.items():
            if key in groups:
                row = groups[key]
                for label in meta.get("feed_labels") or []:
                    if label not in (row.get("feed_labels") or []):
                        row.setdefault("feed_labels", []).append(label)
                if not str(row.get("name_hint") or "").strip():
                    row["name_hint"] = meta.get("name_hint")
                row["subscribed"] = True
            else:
                groups[key] = meta
        user_clause, user_params = self._user_scope_parts(conn)
        user_filter = f" AND {user_clause}" if user_clause else ""
        trash_filter = self._collection_clause_for_conn(conn, "feed")
        scope_where = f"({trash_filter}){user_filter}"

        feed_count_rows = conn.execute(
            f"""
            SELECT
                json_extract(r.source_meta, '$.feed_label') AS feed_label,
                COUNT(*) AS item_count,
                MAX(r.ingested_at) AS latest_at
            FROM raw_items r
            WHERE {scope_where}
              AND COALESCE(json_extract(r.source_meta, '$.feed_label'), '') != ''
            GROUP BY feed_label
            """,
            user_params,
        ).fetchall()
        feed_counts: dict[str, int] = {}
        feed_latest_at: dict[str, str] = {}
        for row in feed_count_rows:
            label = str(row["feed_label"] or "").strip()
            if not label:
                continue
            feed_counts[label] = int(row["item_count"])
            feed_latest_at[label] = str(row["latest_at"] or "")

        feed_latest_meta: dict[str, dict[str, Any]] = {}
        if feed_counts:
            latest_rows = conn.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        json_extract(r.source_meta, '$.feed_label') AS feed_label,
                        r.source_meta,
                        ROW_NUMBER() OVER (
                            PARTITION BY json_extract(r.source_meta, '$.feed_label')
                            ORDER BY r.ingested_at DESC
                        ) AS rn
                    FROM raw_items r
                    WHERE {scope_where}
                      AND COALESCE(json_extract(r.source_meta, '$.feed_label'), '') != ''
                )
                SELECT feed_label, source_meta FROM ranked WHERE rn = 1
                """,
                user_params,
            ).fetchall()
            for row in latest_rows:
                label = str(row["feed_label"] or "").strip()
                if label:
                    feed_latest_meta[label] = loads_meta(row["source_meta"])

        bili_rows = conn.execute(
            f"""
            SELECT
                json_extract(r.source_meta, '$.author_url') AS author_url,
                json_extract(r.source_meta, '$.author') AS author,
                json_extract(r.source_meta, '$.author_avatar') AS author_avatar,
                COUNT(*) AS item_count
            FROM raw_items r
            WHERE r.platform = 'bilibili'
              AND ({trash_filter})
              AND COALESCE(json_extract(r.source_meta, '$.author_url'), '') != ''
              {user_filter}
            GROUP BY author_url, author, author_avatar
            ORDER BY item_count DESC
            """,
            user_params,
        ).fetchall()
        bili_by_url: dict[str, dict[str, Any]] = {}
        for row in bili_rows:
            author_url = str(row["author_url"] or "").strip()
            if not author_url:
                continue
            count = int(row["item_count"])
            prev = bili_by_url.get(author_url)
            if prev:
                prev["count"] += count
                if not prev.get("author") and row["author"]:
                    prev["author"] = str(row["author"]).strip()
                prev["avatar"] = pick_better_avatar(
                    prev.get("avatar"), str(row["author_avatar"] or "")
                )
            else:
                bili_by_url[author_url] = {
                    "count": count,
                    "author": str(row["author"] or "").strip(),
                    "avatar": str(row["author_avatar"] or "").strip(),
                }
            key = f"bili:{author_url}"
            if key not in groups:
                groups[key] = {
                    "key": key,
                    "platform": "bilibili",
                    "feed_labels": [],
                    "name_hint": bili_by_url[author_url]["author"] or author_url,
                }

        zhihu_rows = conn.execute(
            f"""
            SELECT
                json_extract(r.source_meta, '$.author_url') AS author_url,
                json_extract(r.source_meta, '$.author') AS author,
                json_extract(r.source_meta, '$.author_avatar') AS author_avatar,
                COUNT(*) AS item_count
            FROM raw_items r
            WHERE r.platform = 'zhihu'
              AND ({trash_filter})
              AND COALESCE(json_extract(r.source_meta, '$.author_url'), '') != ''
              {user_filter}
            GROUP BY author_url, author, author_avatar
            """,
            user_params,
        ).fetchall()
        zhihu_by_url: dict[str, dict[str, Any]] = {}
        for row in zhihu_rows:
            author_url = normalize_zhihu_author_url(str(row["author_url"] or ""))
            if not author_url:
                continue
            prev = zhihu_by_url.get(author_url)
            count = int(row["item_count"])
            if prev:
                prev["count"] += count
                if not prev.get("author") and row["author"]:
                    prev["author"] = str(row["author"]).strip()
                prev["avatar"] = pick_better_avatar(
                    prev.get("avatar"), str(row["author_avatar"] or "")
                )
            else:
                zhihu_by_url[author_url] = {
                    "count": count,
                    "author": str(row["author"] or "").strip(),
                    "avatar": str(row["author_avatar"] or "").strip(),
                }

        zhihu_latest_meta: dict[str, dict[str, Any]] = {}
        if zhihu_by_url:
            latest_zhihu = conn.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        json_extract(r.source_meta, '$.author_url') AS author_url,
                        r.source_meta,
                        ROW_NUMBER() OVER (
                            PARTITION BY json_extract(r.source_meta, '$.author_url')
                            ORDER BY r.ingested_at DESC
                        ) AS rn
                    FROM raw_items r
                    WHERE r.platform = 'zhihu'
                      AND {scope_where}
                      AND COALESCE(json_extract(r.source_meta, '$.author_url'), '') != ''
                )
                SELECT author_url, source_meta FROM ranked WHERE rn = 1
                """,
                user_params,
            ).fetchall()
            for row in latest_zhihu:
                author_url = normalize_zhihu_author_url(str(row["author_url"] or ""))
                if author_url:
                    zhihu_latest_meta[author_url] = loads_meta(row["source_meta"])

        scoped_rows = conn.execute(
            f"""
            SELECT DISTINCT json_extract(r.source_meta, '$.author_url') AS author_url
            FROM raw_items r
            WHERE r.platform = 'zhihu'
              AND {scope_where}
              AND COALESCE(json_extract(r.source_meta, '$.author_url'), '') != ''
              AND (
                json_extract(r.source_meta, '$.feed_label') LIKE 'zhihu-collection-%'
                OR json_extract(r.source_meta, '$.feed_label') LIKE 'zhihu-activities-%'
                OR json_extract(r.source_meta, '$.feed_label') LIKE 'zhihu-answers-%'
              )
            """,
            user_params,
        ).fetchall()
        scoped_zhihu_urls = {
            normalize_zhihu_author_url(str(row["author_url"] or ""))
            for row in scoped_rows
            if normalize_zhihu_author_url(str(row["author_url"] or ""))
        }

        for key, meta in discover_zhihu_person_groups(zhihu_by_url).items():
            if key in groups:
                continue
            people_url = normalize_zhihu_author_url(str(meta.get("people_url") or ""))
            if people_url not in scoped_zhihu_urls:
                continue
            groups[key] = meta

        twitter_rows = conn.execute(
            f"""
            SELECT
                json_extract(r.source_meta, '$.author_url') AS author_url,
                json_extract(r.source_meta, '$.author') AS author,
                json_extract(r.source_meta, '$.author_avatar') AS author_avatar,
                COUNT(*) AS item_count
            FROM raw_items r
            WHERE r.platform = 'twitter'
              AND r.deleted_at IS NULL
              AND COALESCE(json_extract(r.source_meta, '$.author_url'), '') != ''
              {user_filter}
            GROUP BY author_url, author, author_avatar
            ORDER BY item_count DESC
            """,
            user_params,
        ).fetchall()
        twitter_by_url: dict[str, dict[str, Any]] = {}
        for row in twitter_rows:
            author_url = normalize_twitter_author_url(str(row["author_url"] or ""))
            if not author_url:
                continue
            count = int(row["item_count"])
            prev = twitter_by_url.get(author_url)
            if prev:
                prev["count"] += count
                if not prev.get("author") and row["author"]:
                    prev["author"] = str(row["author"]).strip()
                prev["avatar"] = pick_better_avatar(
                    prev.get("avatar"), str(row["author_avatar"] or "")
                )
            else:
                twitter_by_url[author_url] = {
                    "count": count,
                    "author": str(row["author"] or "").strip(),
                    "avatar": str(row["author_avatar"] or "").strip(),
                }
            key = f"twitter:{author_url}"
            if key not in groups:
                groups[key] = {
                    "key": key,
                    "platform": "twitter",
                    "feed_labels": [],
                    "name_hint": twitter_by_url[author_url]["author"] or author_url,
                    "author_url": author_url,
                }

        twitter_latest_meta: dict[str, dict[str, Any]] = {}
        if twitter_by_url:
            latest_twitter = conn.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        json_extract(r.source_meta, '$.author_url') AS author_url,
                        r.source_meta,
                        ROW_NUMBER() OVER (
                            PARTITION BY json_extract(r.source_meta, '$.author_url')
                            ORDER BY r.ingested_at DESC
                        ) AS rn
                    FROM raw_items r
                    WHERE r.platform = 'twitter'
                      AND {scope_where}
                      AND COALESCE(json_extract(r.source_meta, '$.author_url'), '') != ''
                )
                SELECT author_url, source_meta FROM ranked WHERE rn = 1
                """,
                user_params,
            ).fetchall()
            for row in latest_twitter:
                author_url = normalize_twitter_author_url(str(row["author_url"] or ""))
                if author_url:
                    twitter_latest_meta[author_url] = loads_meta(row["source_meta"])

        for key, meta in discover_twitter_author_groups(twitter_by_url).items():
            if key not in groups:
                groups[key] = meta

        creators: list[dict[str, Any]] = []
        for key, meta in groups.items():
            if key.startswith("zhihu-collection:"):
                continue
            name = str(meta.get("name_hint") or "").strip()
            avatar = ""
            author_url = ""
            if key.startswith("bili:"):
                url = key[5:]
                bili = bili_by_url.get(url)
                item_count = int(bili["count"]) if bili else 0
                if bili:
                    name = bili["author"] or name or url
                bili_meta = {
                    "author_url": url,
                    "author": name or url,
                    "author_avatar": bili.get("avatar") if bili else None,
                    "up_mid": str(meta.get("up_mid") or "").strip() or None,
                }
                if enrich_avatars:
                    bili_meta = enrich_bilibili_author_meta(bili_meta)
                avatar = resolve_author_avatar(bili_meta)
                author_url = url
            elif key.startswith("zhihu-person:"):
                people_url = normalize_zhihu_author_url(
                    str(meta.get("people_url") or zhihu_author_url(key.split(":", 1)[1]))
                )
                zh = zhihu_by_url.get(people_url, {})
                item_count = int(zh.get("count", 0))
                latest_meta = zhihu_latest_meta.get(people_url) or {}
                name = str(zh.get("author") or latest_meta.get("author") or name).strip() or name
                avatar = resolve_author_avatar(latest_meta or {"author_avatar": zh.get("avatar")})
                author_url = people_url
            elif key.startswith("twitter:"):
                url = key[8:]
                tw = twitter_by_url.get(url, {})
                item_count = int(tw.get("count", 0))
                latest_meta = twitter_latest_meta.get(url) or {}
                name = str(tw.get("author") or latest_meta.get("author") or name).strip() or name
                avatar = resolve_author_avatar(latest_meta or {"author_avatar": tw.get("avatar")})
                author_url = url
            else:
                labels = meta.get("feed_labels") or []
                item_count = sum(feed_counts.get(label, 0) for label in labels)
                best_label = ""
                best_at = ""
                avatar = ""
                channel_id = ""
                if labels:
                    label_ph = ",".join("?" for _ in labels)
                    avatar_rows = conn.execute(
                        f"""
                        SELECT
                            json_extract(r.source_meta, '$.author_avatar') AS avatar,
                            json_extract(r.source_meta, '$.channel_id') AS channel_id
                        FROM raw_items r
                        WHERE {scope_where}
                          AND json_extract(r.source_meta, '$.feed_label') IN ({label_ph})
                        """,
                        (*user_params, *labels),
                    ).fetchall()
                    for row in avatar_rows:
                        avatar = pick_better_avatar(avatar, str(row["avatar"] or ""))
                        cid = str(row["channel_id"] or "").strip()
                        if cid:
                            channel_id = channel_id or cid
                for label in labels:
                    at = feed_latest_at.get(label, "")
                    if at >= best_at:
                        best_at = at
                        best_label = label
                if best_label:
                    latest_meta = feed_latest_meta.get(best_label) or {}
                    name = str(latest_meta.get("author") or name).strip() or name
                    avatar = pick_better_avatar(avatar, resolve_author_avatar(latest_meta))
                    channel_id = channel_id or str(latest_meta.get("channel_id") or "").strip()
                    author_url = str(latest_meta.get("author_url") or "").strip()
                platform_name = str(meta.get("platform") or "").strip().lower()
                if platform_name == "youtube":
                    yt_meta = {
                        "author_avatar": avatar,
                        "channel_id": channel_id,
                        "author_url": author_url,
                        "author": name,
                    }
                    if enrich_avatars:
                        yt_meta = enrich_youtube_author_meta(yt_meta)
                    avatar = resolve_author_avatar(yt_meta)
            creators.append(
                {
                    "key": key,
                    "name": name or key,
                    "platform": meta.get("platform") or "generic",
                    "author_url": author_url or None,
                    "author_avatar": avatar or None,
                    "item_count": item_count,
                    "feed_labels": meta.get("feed_labels") or [],
                }
            )
        return finalize_creator_sidebar_rows(creators)

    def _collection_clause_for_conn(self, conn: sqlite3.Connection, collection: str | None) -> str:
        key = (collection or "feed").strip().lower()
        if self._current_schema_version(conn) >= 8 and key == "hotlist":
            # Membership comes from hotlist_snapshots join; avoid tagging feed rows via meta.
            return "r.deleted_at IS NULL"
        if self._current_schema_version(conn) < 7:
            if key == "trash":
                return "0"
            if key == "favorites":
                return "COALESCE(CAST(json_extract(r.source_meta, '$.starred') AS INTEGER), 0) = 1"
            return "1"
        return self._collection_clause(collection)

    def _knowledge_items_filters(
        self,
        conn: sqlite3.Connection,
        *,
        platform: str | None = None,
        source: str | None = None,
        query: str | None = None,
        tag_ids: list[int] | None = None,
        theme_id: int | None = None,
        creator_key: str | None = None,
        collection: str | None = None,
        hotlist_date: str | None = None,
        hotlist_source: str | None = None,
        feed_date: str | None = None,
        unread_only: bool = False,
        min_importance: int | None = None,
    ) -> tuple[str, str, list[Any], bool]:
        """Return (WHERE sql, JOIN sql, params, needs_distilled_join for COUNT)."""
        where_parts: list[str] = [self._collection_clause_for_conn(conn, collection)]
        user_clause, user_params = self._user_scope_parts(conn)
        if user_clause:
            where_parts.append(user_clause)
        join_sql, day_where, day_params = self._hotlist_query_parts(
            conn,
            collection=collection,
            hotlist_date=hotlist_date,
            hotlist_source=hotlist_source,
        )
        params: list[Any] = list(user_params) + list(day_params)
        if day_where.strip():
            where_parts.append(day_where.strip().removeprefix("AND").strip())
        needs_join = False
        if platform:
            from on1y.utils.platform import knowledge_platform_filter_sql

            clause, platform_params = knowledge_platform_filter_sql(platform)
            if clause:
                where_parts.append(clause)
                params.extend(platform_params)
        if source:
            where_parts.append("r.source = ?")
            params.append(source)
        if query and query.strip() and self._current_schema_version(conn) < 6:
            needs_join = True
            where_parts.append(
                "("
                "COALESCE(r.raw_title, '') LIKE ? "
                "OR COALESCE(d.summary, '') LIKE ? "
                "OR COALESCE(r.body_text, '') LIKE ?"
                ")"
            )
            like = f"%{query.strip()}%"
            params.extend([like, like, like])
        coll_key = (collection or "feed").strip().lower()
        if feed_date and feed_date.strip() and coll_key == "feed":
            from on1y.knowledge.feed_dates import feed_date_where_clause

            day_clause, day_params = feed_date_where_clause(feed_date.strip())
            where_parts.append(day_clause)
            params.extend(day_params)
        if unread_only and coll_key == "feed":
            where_parts.append(unread_sql("r"))
        if min_importance is not None and coll_key == "feed":
            from on1y.knowledge.importance import importance_min_sql

            where_parts.append(importance_min_sql("r", minimum=min_importance))
            params.append(int(min_importance))
        if theme_id is not None and coll_key != "hotlist":
            where_parts.append("r.theme_id = ?")
            params.append(theme_id)
        if creator_key and creator_key.strip() and coll_key != "hotlist":
            from on1y.knowledge.creators import creator_filter_sql

            clause, creator_params = creator_filter_sql(creator_key.strip())
            where_parts.append(clause)
            params.extend(creator_params)
        if tag_ids:
            placeholders = ",".join("?" for _ in tag_ids)
            where_parts.append(
                "EXISTS ("
                "SELECT 1 FROM item_tags itf "
                f"WHERE itf.raw_id = r.id AND itf.tag_id IN ({placeholders})"
                ")"
            )
            params.extend(tag_ids)
        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        return where_sql, join_sql, params, needs_join

    def count_knowledge_items(
        self,
        *,
        platform: str | None = None,
        source: str | None = None,
        query: str | None = None,
        tag_ids: list[int] | None = None,
        theme_id: int | None = None,
        creator_key: str | None = None,
        collection: str | None = None,
        hotlist_date: str | None = None,
        hotlist_source: str | None = None,
        feed_date: str | None = None,
        unread_only: bool = False,
        min_importance: int | None = None,
    ) -> int:
        conn = self._connect()
        where_sql, join_sql, params, needs_join = self._knowledge_items_filters(
            conn,
            platform=platform,
            source=source,
            query=query,
            tag_ids=tag_ids,
            theme_id=theme_id,
            creator_key=creator_key,
            collection=collection,
            hotlist_date=hotlist_date,
            hotlist_source=hotlist_source,
            feed_date=feed_date,
            unread_only=unread_only,
            min_importance=min_importance,
        )
        if needs_join:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM raw_items r
                {join_sql}
                LEFT JOIN distilled_items d ON d.raw_id = r.id
                {where_sql}
                """,
                params,
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM raw_items r {join_sql} {where_sql}",
                params,
            ).fetchone()
        return int(row["n"]) if row else 0

    def list_knowledge_items(
        self,
        *,
        limit: int = 30,
        offset: int = 0,
        platform: str | None = None,
        source: str | None = None,
        query: str | None = None,
        tag_ids: list[int] | None = None,
        theme_id: int | None = None,
        creator_key: str | None = None,
        collection: str | None = None,
        hotlist_date: str | None = None,
        hotlist_source: str | None = None,
        feed_date: str | None = None,
        unread_only: bool = False,
        min_importance: int | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        if query and query.strip() and self._current_schema_version(conn) >= 6:
            result = self.search_knowledge_items(
                query=query,
                limit=limit,
                offset=offset,
                platform=platform,
                source=source,
                tag_ids=tag_ids,
                theme_id=theme_id,
                creator_key=creator_key,
                collection=collection,
                hotlist_date=hotlist_date,
                hotlist_source=hotlist_source,
                feed_date=feed_date,
                unread_only=unread_only,
                min_importance=min_importance,
            )
            return result["items"]

        where_sql, join_sql, params, _needs_join = self._knowledge_items_filters(
            conn,
            platform=platform,
            source=source,
            query=query,
            tag_ids=tag_ids,
            theme_id=theme_id,
            creator_key=creator_key,
            collection=collection,
            hotlist_date=hotlist_date,
            hotlist_source=hotlist_source,
            feed_date=feed_date,
            unread_only=unread_only,
            min_importance=min_importance,
        )
        coll = (collection or "feed").strip().lower()
        if coll == "trash":
            order_sql = "r.deleted_at DESC"
        elif coll == "hotlist" and self._current_schema_version(conn) >= 8 and join_sql:
            order_sql = "hs.sort_order ASC, hs.id ASC"
        elif coll == "hotlist":
            order_sql = "r.ingested_at DESC"
        elif coll == "continue":
            order_sql = "json_extract(r.source_meta, '$.last_opened_at') DESC"
        elif coll == "unread":
            order_sql = "r.ingested_at DESC"
        elif coll == "notes":
            order_sql = "r.updated_at DESC"
        elif coll == "chats":
            order_sql = "CAST(json_extract(r.source_meta, '$.telegram_end_ts') AS REAL) DESC, r.ingested_at DESC"
        else:
            order_sql = "COALESCE(d.distilled_at, r.ingested_at) DESC"
        snapshot_select = (
            ", hs.snapshot_date AS hotlist_snapshot_date, hs.heat_text AS hotlist_heat_text"
            if coll == "hotlist" and join_sql
            else ""
        )
        rows = conn.execute(
            f"""
            SELECT
                r.id AS raw_id,
                r.url,
                r.raw_title,
                r.platform,
                r.source,
                r.content_type,
                r.ingested_at,
                r.deleted_at,
                r.source_meta,
                r.theme_id,
                d.summary,
                d.topics,
                d.prompt_version,
                d.distill_status
                {snapshot_select}
            FROM raw_items r
            {join_sql}
            LEFT JOIN distilled_items d ON d.raw_id = r.id
            {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        items = self._assemble_knowledge_items(rows)
        if coll == "hotlist":
            for item, row in zip(items, rows, strict=False):
                snap = (
                    row["hotlist_snapshot_date"] if "hotlist_snapshot_date" in row.keys() else None
                )
                if snap:
                    item["snapshot_date"] = str(snap)
                heat = row["hotlist_heat_text"] if "hotlist_heat_text" in row.keys() else None
                if heat:
                    item["heat_text"] = str(heat).strip() or item.get("heat_text")
        if (collection or "feed").strip().lower() == "trash":
            for item in items:
                item["deleted"] = True
        return items

    def _assemble_knowledge_items(self, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        conn = self._connect()
        item_ids = [int(r["raw_id"]) for r in rows]
        if not item_ids:
            return []
        placeholders = ",".join("?" for _ in item_ids)
        tag_rows = conn.execute(
            f"""
            SELECT it.raw_id, t.id, t.name, t.slug
            FROM item_tags it
            JOIN tags t ON t.id = it.tag_id
            WHERE it.raw_id IN ({placeholders})
            ORDER BY t.name ASC
            """,
            item_ids,
        ).fetchall()
        theme_ids = {int(r["theme_id"]) for r in rows if r["theme_id"] is not None}
        theme_map: dict[int, dict[str, Any]] = {}
        if theme_ids:
            th_placeholders = ",".join("?" for _ in theme_ids)
            theme_rows = conn.execute(
                f"""
                SELECT id, slug, name_zh, name_en
                FROM themes
                WHERE id IN ({th_placeholders})
                """,
                list(theme_ids),
            ).fetchall()
            for row in theme_rows:
                theme_map[int(row["id"])] = {
                    "id": int(row["id"]),
                    "slug": str(row["slug"]),
                    "name_zh": str(row["name_zh"]),
                    "name_en": str(row["name_en"]),
                }
        tags_by_raw: dict[int, list[dict[str, Any]]] = {raw_id: [] for raw_id in item_ids}
        for row in tag_rows:
            raw_id = int(row["raw_id"])
            tags_by_raw.setdefault(raw_id, []).append(
                {
                    "id": int(row["id"]),
                    "name": str(row["name"]),
                    "slug": str(row["slug"]),
                }
            )
        items: list[dict[str, Any]] = []
        for row in rows:
            raw_id = int(row["raw_id"])
            meta = loads_meta(row["source_meta"])
            author_info = author_fields_from_meta(meta)
            starred = bool(meta.get("starred"))
            read_at = read_at_from_meta(meta)
            has_note = has_user_note(meta)
            importance = importance_from_meta(meta)
            topics = loads_json_list(row["topics"])
            tid = row["theme_id"]
            theme_obj = theme_map.get(int(tid)) if tid is not None else None
            themes_list = [theme_obj] if theme_obj else []
            item_url = str(row["url"])
            if str(row["platform"]) == "economist":
                from on1y.hotlist.economist_urls import resolve_economist_epub_url

                item_url = resolve_economist_epub_url(item_url, meta)
            elif str(row["platform"]) == "obsidian":
                source_url = str(meta.get("obsidian_source_url") or "").strip()
                if source_url:
                    item_url = source_url
            items.append(
                {
                    "raw_id": raw_id,
                    "url": item_url,
                    "title": row["raw_title"],
                    "platform": str(row["platform"]),
                    "source": str(row["source"]),
                    "content_type": str(row["content_type"])
                    if "content_type" in row.keys() and row["content_type"]
                    else "unknown",
                    "ingested_at": row["ingested_at"],
                    "published_at": published_at_iso(meta),
                    "duration_sec": _source_meta_int(meta, "duration_sec", "duration"),
                    "like_count": _source_meta_int(meta, "like_count", "likes", "voteup_count"),
                    "comment_count": _source_meta_int(
                        meta, "comment_count", "comments", "reply_count"
                    ),
                    "feed_label": str(meta.get("feed_label") or "").strip() or None,
                    "hot_rank": meta.get("hot_rank"),
                    "heat_text": str(meta.get("heat_text") or "").strip() or None,
                    "snapshot_date": str(meta.get("snapshot_date") or "").strip() or None,
                    "summary": row["summary"] or meta.get("entry_excerpt"),
                    "topics": topics if isinstance(topics, list) else [],
                    "prompt_version": row["prompt_version"],
                    "distill_status": row["distill_status"],
                    **author_info,
                    "theme_id": int(tid) if tid is not None else None,
                    "theme": theme_obj,
                    "tags": tags_by_raw.get(raw_id, []),
                    "themes": themes_list,
                    "starred": starred,
                    "read_at": read_at,
                    "is_read": read_at is not None,
                    "has_note": has_note,
                    "importance": importance,
                    "clip_source": str(meta.get("clip_source") or "").strip() or None,
                    "clip_count": _as_int_or_none(meta.get("clip_count")),
                    "extract_strategy": str(meta.get("extract_strategy") or "").strip() or None,
                    "obsidian_uri": str(meta.get("obsidian_uri") or "").strip() or None,
                    "obsidian_source_url": str(meta.get("obsidian_source_url") or "").strip()
                    or None,
                    "obsidian_path": str(meta.get("obsidian_path") or "").strip() or None,
                    "obsidian_writeback_status": str(
                        meta.get("obsidian_writeback_status") or ""
                    ).strip()
                    or None,
                    "deleted_at": row["deleted_at"] if "deleted_at" in row.keys() else None,
                }
            )
        return items

    def get_distilled_detail(self, raw_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        drow = conn.execute(
            "SELECT * FROM distilled_items WHERE raw_id = ?",
            (raw_id,),
        ).fetchone()
        if not drow:
            return None
        raw = conn.execute("SELECT * FROM raw_items WHERE id = ?", (raw_id,)).fetchone()
        tags = conn.execute(
            """
            SELECT t.id, t.name, t.slug, it.confidence
            FROM item_tags it
            JOIN tags t ON t.id = it.tag_id
            WHERE it.raw_id = ?
            ORDER BY t.name ASC
            """,
            (raw_id,),
        ).fetchall()
        themes = conn.execute(
            """
            SELECT th.id, th.slug, th.name_zh, th.name_en, ith.confidence
            FROM item_themes ith
            JOIN themes th ON th.id = ith.theme_id
            WHERE ith.raw_id = ?
            ORDER BY th.sort_order ASC
            """,
            (raw_id,),
        ).fetchall()
        rels = conn.execute(
            """
            SELECT ir.*, r.url AS to_url, r.raw_title AS to_title
            FROM item_relations ir
            JOIN raw_items r ON r.id = ir.to_raw_id
            WHERE ir.from_raw_id = ?
            """,
            (raw_id,),
        ).fetchall()
        distilled = self._row_to_distilled(drow)
        return {
            "distilled": distilled.model_dump(),
            "raw": dict(raw) if raw else None,
            "tags": [dict(t) for t in tags],
            "themes": [dict(t) for t in themes],
            "relations": [dict(r) for r in rels],
        }

    def _row_to_distilled(self, row: sqlite3.Row) -> DistilledItem:
        kp = loads_json_list(row["key_points"])
        tp = loads_json_list(row["topics"])
        return DistilledItem(
            id=int(row["id"]),
            raw_id=int(row["raw_id"]),
            summary=row["summary"],
            key_points=kp if isinstance(kp, list) else [],
            topics=tp if isinstance(tp, list) else [],
            distill_status=row["distill_status"],
            distill_error=row["distill_error"],
            model=row["model"],
            prompt_version=row["prompt_version"],
            distilled_at=self._parse_dt(row["distilled_at"]),
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def get_storage() -> SqliteStorage:
    storage = SqliteStorage()
    storage.initialize()
    return storage
