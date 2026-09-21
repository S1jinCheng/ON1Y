-- Schema v26: allow a paper to leave the daily reading queue without being read.
-- SQLite cannot widen a CHECK constraint in place, so rebuild the table while
-- preserving every column introduced through schema v25.

BEGIN IMMEDIATE;

CREATE TABLE paper_items_v26 (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    raw_id                     INTEGER REFERENCES raw_items(id) ON DELETE SET NULL,
    title                      TEXT NOT NULL,
    authors_json               TEXT NOT NULL DEFAULT '[]',
    abstract                   TEXT,
    status                     TEXT NOT NULL DEFAULT 'to_read'
                               CHECK (status IN ('to_read', 'reading', 'read', 'dismissed')),
    year                       INTEGER,
    venue                      TEXT,
    doi                        TEXT,
    url                        TEXT,
    pdf_path                   TEXT,
    zotero_key                 TEXT,
    zotero_library_id          TEXT,
    zotero_version             INTEGER,
    citation_count             INTEGER,
    user_note_html             TEXT,
    importance                 INTEGER,
    theme_slug                 TEXT,
    tags_json                  TEXT NOT NULL DEFAULT '[]',
    created_at                 TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                 TEXT NOT NULL DEFAULT (datetime('now')),
    zotero_attachment_key      TEXT,
    zotero_library_type        TEXT,
    ai_summary_json            TEXT,
    ai_summary_status          TEXT NOT NULL DEFAULT 'idle',
    ai_summary_error           TEXT,
    ai_summary_model           TEXT,
    ai_summary_updated_at      TEXT,
    figures_json               TEXT NOT NULL DEFAULT '[]',
    zotero_collections_json    TEXT NOT NULL DEFAULT '[]',
    folders_json               TEXT NOT NULL DEFAULT '[]',
    literature_paper_id        TEXT
);

INSERT INTO paper_items_v26 (
    id, user_id, raw_id, title, authors_json, abstract, status, year, venue,
    doi, url, pdf_path, zotero_key, zotero_library_id, zotero_version,
    citation_count, user_note_html, importance, theme_slug, tags_json,
    created_at, updated_at, zotero_attachment_key, zotero_library_type,
    ai_summary_json, ai_summary_status, ai_summary_error, ai_summary_model,
    ai_summary_updated_at, figures_json, zotero_collections_json, folders_json,
    literature_paper_id
)
SELECT
    id, user_id, raw_id, title, authors_json, abstract, status, year, venue,
    doi, url, pdf_path, zotero_key, zotero_library_id, zotero_version,
    citation_count, user_note_html, importance, theme_slug, tags_json,
    created_at, updated_at, zotero_attachment_key, zotero_library_type,
    ai_summary_json, ai_summary_status, ai_summary_error, ai_summary_model,
    ai_summary_updated_at, figures_json, zotero_collections_json, folders_json,
    literature_paper_id
FROM paper_items;

DROP TABLE paper_items;
ALTER TABLE paper_items_v26 RENAME TO paper_items;

CREATE INDEX idx_paper_items_user ON paper_items (user_id);
CREATE INDEX idx_paper_items_user_status ON paper_items (user_id, status);
CREATE INDEX idx_paper_items_raw ON paper_items (raw_id);
CREATE UNIQUE INDEX idx_paper_items_user_zotero
    ON paper_items (user_id, zotero_library_id, zotero_key)
    WHERE zotero_key IS NOT NULL;
CREATE UNIQUE INDEX idx_paper_items_user_literature
    ON paper_items (user_id, literature_paper_id)
    WHERE literature_paper_id IS NOT NULL;

COMMIT;
