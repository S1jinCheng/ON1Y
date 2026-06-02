-- Schema v8: per-day hot-list snapshots (browse history by date)

CREATE TABLE IF NOT EXISTS hotlist_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotlist_source TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    question_id TEXT NOT NULL,
    raw_id INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    heat_text TEXT,
    title TEXT,
    excerpt TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (hotlist_source, snapshot_date, question_id)
);

CREATE INDEX IF NOT EXISTS idx_hotlist_snapshots_date
    ON hotlist_snapshots (hotlist_source, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_hotlist_snapshots_raw
    ON hotlist_snapshots (raw_id);

INSERT OR IGNORE INTO hotlist_snapshots (
    hotlist_source,
    snapshot_date,
    question_id,
    raw_id,
    heat_text,
    title,
    excerpt,
    sort_order
)
SELECT
    COALESCE(json_extract(r.source_meta, '$.hotlist_source'), 'zhihu'),
    COALESCE(
        NULLIF(TRIM(json_extract(r.source_meta, '$.snapshot_date')), ''),
        date(r.ingested_at)
    ),
    COALESCE(
        NULLIF(TRIM(json_extract(r.source_meta, '$.question_id')), ''),
        CAST(r.id AS TEXT)
    ),
    r.id,
    NULLIF(TRIM(json_extract(r.source_meta, '$.heat_text')), ''),
    r.raw_title,
    NULLIF(TRIM(json_extract(r.source_meta, '$.entry_excerpt')), ''),
    CAST(COALESCE(json_extract(r.source_meta, '$.hot_rank'), '9999') AS INTEGER)
FROM raw_items r
WHERE COALESCE(json_extract(r.source_meta, '$.hotlist_source'), '') != '';
