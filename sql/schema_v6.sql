-- Schema v6: FTS5 full-text search index (trigram — strong CJK substring recall)

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title,
    summary,
    body,
    tags,
    author,
    theme,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS knowledge_fts_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO knowledge_fts_meta (key, value) VALUES ('version', '1');
