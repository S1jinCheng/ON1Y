-- Schema v4: hard themes (一级) + flat dynamic tags (多维)

CREATE TABLE IF NOT EXISTS themes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,
    name_zh     TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS item_themes (
    raw_id      INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    theme_id    INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    source      TEXT NOT NULL DEFAULT 'llm',
    confidence  REAL,
    PRIMARY KEY (raw_id, theme_id)
);

CREATE INDEX IF NOT EXISTS idx_item_themes_theme ON item_themes (theme_id);
CREATE INDEX IF NOT EXISTS idx_item_themes_raw ON item_themes (raw_id);
