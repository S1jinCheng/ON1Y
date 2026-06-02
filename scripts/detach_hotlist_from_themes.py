#!/usr/bin/env python3
"""One-off: move existing hot-list rows out of theme taxonomy."""

from __future__ import annotations

from on1y.adapters.sqlite_storage import get_storage
from on1y.hotlist.sql import is_hotlist_row_sql


def main() -> int:
    storage = get_storage()
    conn = storage._connect()
    rows = conn.execute(
        f"""
        SELECT id FROM raw_items r
        WHERE {is_hotlist_row_sql("r")}
          AND (r.theme_id IS NOT NULL OR EXISTS (
            SELECT 1 FROM item_themes it WHERE it.raw_id = r.id
          ))
        """
    ).fetchall()
    n = 0
    for row in rows:
        storage.detach_hotlist_item(int(row["id"]))
        n += 1
    storage.close()
    print(f"Detached {n} hot-list item(s) from themes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
