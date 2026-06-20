-- Schema v16: link shelf items to knowledge archive for tags + recommendations

ALTER TABLE book_shelf_items ADD COLUMN raw_id INTEGER REFERENCES raw_items(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_book_shelf_raw ON book_shelf_items (raw_id);
