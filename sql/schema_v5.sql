-- Schema v5: exclusive theme on raw_items, user-managed themes, reader text

ALTER TABLE themes ADD COLUMN description_zh TEXT NOT NULL DEFAULT '';
ALTER TABLE themes ADD COLUMN description_en TEXT NOT NULL DEFAULT '';
ALTER TABLE themes ADD COLUMN is_builtin INTEGER NOT NULL DEFAULT 0;
ALTER TABLE themes ADD COLUMN archived_at TEXT;
ALTER TABLE themes ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));

ALTER TABLE raw_items ADD COLUMN theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL;
ALTER TABLE raw_items ADD COLUMN theme_source TEXT NOT NULL DEFAULT 'llm';

ALTER TABLE distilled_items ADD COLUMN reader_text TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_items_theme ON raw_items (theme_id);

-- One theme per item: migrate from item_themes (lowest sort_order wins)
UPDATE raw_items
SET theme_id = (
    SELECT ith.theme_id
    FROM item_themes ith
    JOIN themes th ON th.id = ith.theme_id
    WHERE ith.raw_id = raw_items.id
    ORDER BY th.sort_order ASC, ith.theme_id ASC
    LIMIT 1
)
WHERE theme_id IS NULL
  AND EXISTS (SELECT 1 FROM item_themes ith2 WHERE ith2.raw_id = raw_items.id);

CREATE TABLE IF NOT EXISTS theme_operations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    op_type         TEXT NOT NULL CHECK (op_type IN ('split', 'merge', 'archive')),
    source_theme_id INTEGER REFERENCES themes(id) ON DELETE SET NULL,
    target_theme_ids TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'done',
    total_items     INTEGER NOT NULL DEFAULT 0,
    processed_items INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);
