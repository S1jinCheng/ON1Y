"""Re-queue failed pending_urls after schema repair (user 2 by default)."""

from __future__ import annotations

import argparse
import sqlite3

from on1y.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=2)
    args = parser.parse_args()
    db = get_settings().db_path
    conn = sqlite3.connect(db)
    cur = conn.execute(
        """
        UPDATE pending_urls
        SET status = 'pending', error = NULL, attempts = 0, updated_at = datetime('now')
        WHERE user_id = ? AND status IN ('failed', 'processing')
        """,
        (args.user_id,),
    )
    conn.commit()
    print(f"Reset {cur.rowcount} pending_urls for user_id={args.user_id} in {db}")
    conn.close()


if __name__ == "__main__":
    main()
