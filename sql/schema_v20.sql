-- Schema v20: theme discovery cache + absorb operation metadata

ALTER TABLE themes ADD COLUMN discovery_json TEXT;

ALTER TABLE theme_operations RENAME TO theme_operations_old;

CREATE TABLE theme_operations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    op_type         TEXT NOT NULL CHECK (op_type IN ('split', 'merge', 'archive', 'absorb')),
    source_theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    target_theme_ids TEXT NOT NULL DEFAULT '[]',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'done',
    total_items     INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

INSERT INTO theme_operations (
    id, op_type, source_theme_id, target_theme_ids, metadata_json,
    status, total_items, processed_items, created_at, completed_at
)
SELECT
    id, op_type, source_theme_id, target_theme_ids, '{}',
    status, total_items, processed_items, created_at, completed_at
FROM theme_operations_old;

DROP TABLE theme_operations_old;
