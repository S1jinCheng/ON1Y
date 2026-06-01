-- On1y schema migration v2: LLM distillation, tags, relations

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    parent_id   INTEGER REFERENCES tags(id) ON DELETE SET NULL,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tags_parent ON tags (parent_id);

CREATE TABLE IF NOT EXISTS distilled_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id          INTEGER NOT NULL UNIQUE REFERENCES raw_items(id) ON DELETE CASCADE,
    summary         TEXT,
    key_points      TEXT,
    topics          TEXT,
    distill_status  TEXT NOT NULL DEFAULT 'ok' CHECK (distill_status IN ('ok', 'failed')),
    distill_error   TEXT,
    model           TEXT,
    prompt_version  TEXT,
    distilled_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_distilled_raw ON distilled_items (raw_id);

CREATE TABLE IF NOT EXISTS item_tags (
    raw_id      INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    confidence  REAL,
    source      TEXT NOT NULL DEFAULT 'llm',
    PRIMARY KEY (raw_id, tag_id)
);

CREATE TABLE IF NOT EXISTS item_relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_raw_id     INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    to_raw_id       INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL CHECK (relation_type IN (
        'same_topic', 'references', 'subset_of', 'series', 'contradicts', 'related'
    )),
    confidence      REAL,
    note            TEXT,
    source          TEXT NOT NULL DEFAULT 'llm',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (from_raw_id, to_raw_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_item_relations_from ON item_relations (from_raw_id);
CREATE INDEX IF NOT EXISTS idx_item_relations_to ON item_relations (to_raw_id);
