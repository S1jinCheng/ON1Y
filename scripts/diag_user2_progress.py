"""Quick cold-start progress snapshot for a user."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from on1y.config import get_settings

uid = int(sys.argv[1]) if len(sys.argv) > 1 else 2
db = get_settings().db_path
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

print(f"DB: {db}  user_id={uid}\n")

print("=== raw_items ===")
print(conn.execute("SELECT COUNT(*) FROM raw_items WHERE user_id=?", (uid,)).fetchone()[0])
for row in conn.execute(
    "SELECT extract_status, COUNT(*) c FROM raw_items WHERE user_id=? GROUP BY extract_status",
    (uid,),
):
    print(f"  extract {row['extract_status']}: {row['c']}")

print("\n=== pending_urls ===")
for row in conn.execute(
    "SELECT status, COUNT(*) c FROM pending_urls WHERE user_id=? GROUP BY status",
    (uid,),
):
    print(f"  {row['status']}: {row['c']}")

print("\n=== subtitle_status (source_meta) ===")
for row in conn.execute(
    """
    SELECT COALESCE(json_extract(source_meta, '$.subtitle_status'), '(null)') AS st, COUNT(*) c
    FROM raw_items WHERE user_id=? AND content_type='video'
    GROUP BY st
    """,
    (uid,),
):
    print(f"  {row['st']}: {row['c']}")

print("\n=== pending_subtitles ===")
try:
    for row in conn.execute(
        """
        SELECT ps.status, COUNT(*) c FROM pending_subtitles ps
        JOIN raw_items r ON r.id = ps.raw_id WHERE r.user_id=?
        GROUP BY ps.status
        """,
        (uid,),
    ):
        print(f"  {row['status']}: {row['c']}")
except sqlite3.OperationalError as e:
    print(f"  (skip: {e})")

print("\n=== distill ===")
for row in conn.execute(
    """
    SELECT COALESCE(d.distill_status, '(none)') AS st, COUNT(*) c
    FROM raw_items r
    LEFT JOIN distilled_items d ON d.raw_id = r.id
    WHERE r.user_id=?
    GROUP BY st
    """,
    (uid,),
):
    print(f"  {row['st']}: {row['c']}")

errs = conn.execute(
    """
    SELECT substr(d.distill_error, 1, 120) AS err, COUNT(*) c
    FROM raw_items r
    JOIN distilled_items d ON d.raw_id = r.id
    WHERE r.user_id=? AND d.distill_status='failed'
    GROUP BY err ORDER BY c DESC LIMIT 5
    """,
    (uid,),
).fetchall()
if errs:
    print("  distill errors:")
    for row in errs:
        print(f"    [{row['c']}] {row['err']}")

eligible = conn.execute(
    """
    SELECT COUNT(*) FROM raw_items r
    LEFT JOIN distilled_items d ON d.raw_id = r.id
    WHERE r.user_id=? AND r.deleted_at IS NULL
      AND (d.id IS NULL OR d.distill_status='failed')
      AND r.extract_status IN ('ok', 'partial')
      AND (
        length(COALESCE(r.body_text, '')) > 50
        OR json_extract(r.source_meta, '$.subtitle_status') = 'ready'
      )
    """,
    (uid,),
).fetchone()[0]
print(f"\n  eligible for distill (approx): {eligible}")

timing = Path(get_settings().data_dir) / "users" / str(uid) / "sync_timing.jsonl"
if timing.is_file():
    lines = timing.read_text(encoding="utf-8").strip().splitlines()
    print(f"\n=== sync_timing ({len(lines)} records) ===")
    if lines:
        rec = json.loads(lines[-1])
        print(f"  last total_ms: {rec.get('total_duration_ms')}")
        print(f"  phases_ms: {json.dumps(rec.get('phases_ms', {}), ensure_ascii=False)[:600]}")
        pipe = rec.get("pipeline") or {}
        print(f"  pipeline rounds: {pipe.get('rounds')}")
else:
    print(f"\n(no {timing})")

profile = Path(get_settings().data_dir) / "users" / str(uid) / "profile.json"
if profile.is_file():
    prof = json.loads(profile.read_text(encoding="utf-8"))
    cs = prof.get("cold_start") or prof.get("sections", {}).get("cold_start")
    if cs:
        print(f"\n=== profile cold_start ===\n  {json.dumps(cs, ensure_ascii=False)[:500]}")

conn.close()
