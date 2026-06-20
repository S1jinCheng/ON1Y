-- Schema v18: bookshelf shadow rows stay out of theme feed

UPDATE raw_items
SET theme_id = NULL, theme_source = ''
WHERE platform = 'book'
   OR COALESCE(json_extract(source_meta, '$.book_shelf'), '') IN ('1', 'true', 'True');
