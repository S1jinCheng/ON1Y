-- Schema v15: book shelf metadata, user notes, tags

ALTER TABLE book_shelf_items ADD COLUMN cover_url TEXT;
ALTER TABLE book_shelf_items ADD COLUMN translator TEXT;
ALTER TABLE book_shelf_items ADD COLUMN publisher TEXT;
ALTER TABLE book_shelf_items ADD COLUMN summary TEXT;
ALTER TABLE book_shelf_items ADD COLUMN user_note_html TEXT;
ALTER TABLE book_shelf_items ADD COLUMN importance INTEGER;
ALTER TABLE book_shelf_items ADD COLUMN theme_slug TEXT;
ALTER TABLE book_shelf_items ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE book_shelf_items ADD COLUMN cached_format TEXT;
