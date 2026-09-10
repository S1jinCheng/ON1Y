ALTER TABLE paper_items ADD COLUMN ai_summary_json TEXT;
ALTER TABLE paper_items ADD COLUMN ai_summary_status TEXT NOT NULL DEFAULT 'idle';
ALTER TABLE paper_items ADD COLUMN ai_summary_error TEXT;
ALTER TABLE paper_items ADD COLUMN ai_summary_model TEXT;
ALTER TABLE paper_items ADD COLUMN ai_summary_updated_at TEXT;
ALTER TABLE paper_items ADD COLUMN figures_json TEXT NOT NULL DEFAULT '[]';
