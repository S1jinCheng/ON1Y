-- Schema v21: per-user paper library linked to the shared knowledge archive

CREATE TABLE IF NOT EXISTS paper_items (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    raw_id             INTEGER REFERENCES raw_items(id) ON DELETE SET NULL,
    title              TEXT NOT NULL,
    authors_json       TEXT NOT NULL DEFAULT '[]',
    abstract           TEXT,
    status             TEXT NOT NULL DEFAULT 'to_read'
                       CHECK (status IN ('to_read', 'reading', 'read')),
    year               INTEGER,
    venue              TEXT,
    doi                TEXT,
    url                TEXT,
    pdf_path           TEXT,
    zotero_key         TEXT,
    zotero_library_id  TEXT,
    zotero_version     INTEGER,
    citation_count     INTEGER,
    user_note_html     TEXT,
    importance         INTEGER,
    theme_slug         TEXT,
    tags_json          TEXT NOT NULL DEFAULT '[]',
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_paper_items_user ON paper_items (user_id);
CREATE INDEX IF NOT EXISTS idx_paper_items_user_status ON paper_items (user_id, status);
CREATE INDEX IF NOT EXISTS idx_paper_items_raw ON paper_items (raw_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_items_user_zotero
    ON paper_items (user_id, zotero_library_id, zotero_key)
    WHERE zotero_key IS NOT NULL;

UPDATE raw_items
SET theme_id = NULL, theme_source = ''
WHERE platform = 'paper'
   OR COALESCE(json_extract(source_meta, '$.paper_library'), '') IN ('1', 'true', 'True');
