-- Schema v22: retain Zotero PDF attachment identity for reader deep links

ALTER TABLE paper_items ADD COLUMN zotero_attachment_key TEXT;
ALTER TABLE paper_items ADD COLUMN zotero_library_type TEXT;
