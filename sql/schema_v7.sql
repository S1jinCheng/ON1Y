-- Schema v7: soft delete (recently deleted / restore)

ALTER TABLE raw_items ADD COLUMN deleted_at TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_items_deleted_at ON raw_items(deleted_at);
