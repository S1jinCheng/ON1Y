"""User feedback on related-item pairs."""

from __future__ import annotations

import sqlite3


def record_less_relevant(conn: sqlite3.Connection, *, from_raw_id: int, to_raw_id: int) -> None:
    if from_raw_id == to_raw_id:
        return
    conn.execute(
        """
        INSERT INTO recommendation_feedback (from_raw_id, to_raw_id, action)
        VALUES (?, ?, 'less_relevant')
        ON CONFLICT(from_raw_id, to_raw_id) DO NOTHING
        """,
        (from_raw_id, to_raw_id),
    )
