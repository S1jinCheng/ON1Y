-- Schema v24: Zotero collection memberships and hierarchy paths for Paper

ALTER TABLE paper_items ADD COLUMN zotero_collections_json TEXT NOT NULL DEFAULT '[]';
