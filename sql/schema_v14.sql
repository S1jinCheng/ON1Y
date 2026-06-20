-- Schema v14: book shelf (per-user, separate from favorites)

CREATE TABLE IF NOT EXISTS book_shelf_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    author          TEXT,
    status          TEXT NOT NULL DEFAULT 'want' CHECK (status IN ('want', 'reading', 'read')),
    links_json      TEXT NOT NULL DEFAULT '[]',
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_book_shelf_user ON book_shelf_items (user_id);
CREATE INDEX IF NOT EXISTS idx_book_shelf_user_status ON book_shelf_items (user_id, status);
