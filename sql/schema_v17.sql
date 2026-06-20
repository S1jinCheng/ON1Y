-- Schema v17: drop "want" shelf status (migrate to reading)

UPDATE book_shelf_items SET status = 'reading' WHERE status = 'want';
