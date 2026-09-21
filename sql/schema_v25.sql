-- Schema v25: local-folder classification and stable Literature Vault identity.
-- Folder membership is intentionally independent from Zotero collections.

ALTER TABLE paper_items ADD COLUMN folders_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE paper_items ADD COLUMN literature_paper_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_items_user_literature
    ON paper_items (user_id, literature_paper_id)
    WHERE literature_paper_id IS NOT NULL;
