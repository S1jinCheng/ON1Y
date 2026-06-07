"""Live sync job + queue diagnostics."""

from __future__ import annotations

import sqlite3
import sys

from on1y.config import get_settings
from on1y.distill.batch_job import distill_batch_status
from on1y.distill.prompts import PROMPT_VERSION
from on1y.sync.full_sync import full_sync_status


def main() -> None:
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    db = get_settings().db_path

    print("=== full_sync_status (in-memory) ===")
    st = full_sync_status()
    for key in (
        "running",
        "active",
        "distill_running",
        "current_phase",
        "user_id",
        "error",
        "started_at",
        "finished_at",
    ):
        print(f"  {key}: {st.get(key)}")
    bg = st.get("background_distill") or {}
    print(
        "  background_distill:",
        {k: bg.get(k) for k in ("running", "distilled", "remaining", "failed", "error")},
    )
    counters = (st.get("progress") or {}).get("counters")
    print(f"  progress.counters: {counters}")

    print("\n=== distill_batch_job ===")
    print(distill_batch_status())

    conn = sqlite3.connect(db)
    print(f"\n=== user_id={uid} queues ===")
    print("pending_urls:", conn.execute(
        "SELECT status, COUNT(*) FROM pending_urls WHERE user_id=? GROUP BY status",
        (uid,),
    ).fetchall())
    print("raw_items:", conn.execute(
        "SELECT COUNT(*) FROM raw_items WHERE user_id=?", (uid,)
    ).fetchone()[0])
    print("distill ok:", conn.execute(
        """
        SELECT COUNT(*) FROM raw_items r
        JOIN distilled_items d ON d.raw_id=r.id
        WHERE r.user_id=? AND d.distill_status='ok'
        """,
        (uid,),
    ).fetchone()[0])
    print("no distill row:", conn.execute(
        """
        SELECT COUNT(*) FROM raw_items r
        LEFT JOIN distilled_items d ON d.raw_id=r.id
        WHERE r.user_id=? AND d.id IS NULL
        """,
        (uid,),
    ).fetchone()[0])
    print("pending_subtitles:", conn.execute(
        """
        SELECT ps.status, COUNT(*) FROM pending_subtitles ps
        JOIN raw_items r ON r.id=ps.raw_id WHERE r.user_id=?
        GROUP BY ps.status
        """,
        (uid,),
    ).fetchall())
    failed = conn.execute(
        "SELECT url, substr(error,1,150) FROM pending_urls WHERE user_id=? AND status='failed'",
        (uid,),
    ).fetchall()
    if failed:
        print("failed pending:", failed)

    from on1y.adapters.sqlite_storage import SqliteStorage
    from on1y.auth.context import user_context

    with user_context(uid):
        storage = SqliteStorage(db)
        storage.initialize()
        needing = storage.count_raw_ids_needing_distill(
            prompt_version=PROMPT_VERSION, platform=None
        )
        print(f"needing_distill (storage): {needing}")
        sample = storage.list_raw_ids_needing_distill(
            prompt_version=PROMPT_VERSION, limit=5, platform=None
        )
        print("sample raw_ids:", sample)
        for raw_id in sample[:3]:
            raw = storage.get_raw_by_id(raw_id)
            if not raw:
                continue
            meta = raw.source_meta or {}
            print(
                f"  id={raw_id} platform={raw.platform} "
                f"body_len={len((raw.body_text or '').strip())} "
                f"subtitle={meta.get('subtitle_status')} "
                f"title={(raw.raw_title or '')[:40]}"
            )
        storage.close()
    conn.close()


if __name__ == "__main__":
    main()
