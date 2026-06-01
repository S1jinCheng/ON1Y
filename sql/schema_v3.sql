-- Schema v3: decoupled YouTube subtitle fetch queue

CREATE TABLE IF NOT EXISTS pending_subtitles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id      INTEGER NOT NULL UNIQUE,
    url         TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'processing', 'done', 'failed'
    )),
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (raw_id) REFERENCES raw_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pending_subtitles_status_created
    ON pending_subtitles (status, created_at);
