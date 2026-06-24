-- Schema v19: Obsidian registry, writeback queue, and relation type extension.

CREATE TABLE IF NOT EXISTS obsidian_note_registry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vault_path    TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    raw_id        INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    mtime         REAL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, vault_path, rel_path)
);

CREATE INDEX IF NOT EXISTS idx_obsidian_registry_raw_id
    ON obsidian_note_registry (raw_id);

CREATE TABLE IF NOT EXISTS obsidian_writeback_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_rel_path TEXT NOT NULL,
    block_anchor    TEXT,
    content_md      TEXT NOT NULL,
    link_raw_id     INTEGER REFERENCES raw_items(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'applied', 'failed', 'skipped')),
    last_error      TEXT,
    applied_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_obsidian_writeback_user_status
    ON obsidian_writeback_queue (user_id, status, created_at);

DROP INDEX IF EXISTS idx_item_relations_from;
DROP INDEX IF EXISTS idx_item_relations_to;
ALTER TABLE item_relations RENAME TO item_relations_old;

CREATE TABLE item_relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_raw_id     INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    to_raw_id       INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL CHECK (relation_type IN (
        'same_topic', 'references', 'subset_of', 'series', 'contradicts', 'related', 'obsidian_link'
    )),
    confidence      REAL,
    note            TEXT,
    source          TEXT NOT NULL DEFAULT 'llm',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (from_raw_id, to_raw_id, relation_type)
);

INSERT OR IGNORE INTO item_relations (
    id, from_raw_id, to_raw_id, relation_type, confidence, note, source, created_at
)
SELECT
    id, from_raw_id, to_raw_id, relation_type, confidence, note, source, created_at
FROM item_relations_old;

DROP TABLE item_relations_old;

CREATE INDEX IF NOT EXISTS idx_item_relations_from ON item_relations (from_raw_id);
CREATE INDEX IF NOT EXISTS idx_item_relations_to ON item_relations (to_raw_id);
