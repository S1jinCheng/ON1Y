# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "on1y.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

for label in ("yt-zhang-xiaojun-podcast", "yt-mediastorm"):
    rows = conn.execute(
        """
        SELECT platform,
               json_extract(source_meta, '$.author') AS author,
               json_extract(source_meta, '$.author_avatar') AS avatar,
               json_extract(source_meta, '$.channel_id') AS cid
        FROM raw_items
        WHERE deleted_at IS NULL
          AND json_extract(source_meta, '$.feed_label') = ?
        LIMIT 5
        """,
        (label,),
    ).fetchall()
    print(f"\n=== {label} ===")
    for r in rows:
        print(dict(r))

from on1y.adapters.sqlite_storage import SqliteStorage

s = SqliteStorage(DB)
for c in s.list_subscribed_creators():
    if "zhang-xiaojun" in str(c):
        print("\nSIDEBAR:", c)
s.close()
conn.close()
