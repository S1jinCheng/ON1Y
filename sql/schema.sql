-- On1y Phase 1 schema (version 1)
-- Applied idempotently by on1y.adapters.sqlite_storage

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pending_urls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    source      TEXT NOT NULL CHECK (source IN (
        'rss', 'bilibili_feed', 'youtube_feed', 'manual', 'chrome', 'api'
    )),
    source_meta TEXT,  -- JSON object
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'processing', 'done', 'failed'
    )),
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (url, source)
);

CREATE INDEX IF NOT EXISTS idx_pending_urls_status_created
    ON pending_urls (status, created_at);

CREATE TABLE IF NOT EXISTS raw_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,
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
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_raw_items_platform_ingested
    ON raw_items (platform, ingested_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_items_source
    ON raw_items (source);

-- RSS feed cursor: last seen entry id / published time per feed URL
CREATE TABLE IF NOT EXISTS rss_feed_state (
    feed_url        TEXT PRIMARY KEY,
    last_entry_id   TEXT,
    last_published  TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
