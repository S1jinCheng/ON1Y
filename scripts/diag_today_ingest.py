"""Diagnose today view vs published dates and sync_since settings."""

from __future__ import annotations

from datetime import datetime

from on1y.adapters.sqlite_storage import get_storage
from on1y.stats.timezone_util import stats_timezone
from on1y.subscriptions.settings import load_subscription_settings, sync_since_date
from on1y.utils.json_util import loads_meta
from on1y.utils.published_at import published_at_iso


def main() -> None:
    cfg = load_subscription_settings()
    print("subscription_settings:", cfg)
    for p in ("bilibili", "youtube", "zhihu"):
        print(f"  {p} sync_since:", sync_since_date(p))

    tz = stats_timezone()
    today = datetime.now(tz).date()
    print("local today:", today.isoformat())

    storage = get_storage()
    storage.initialize()
    conn = storage._connect()

    rows = conn.execute(
        """
        SELECT r.id, r.platform, r.ingested_at, r.raw_title, r.source_meta
        FROM raw_items r
        WHERE r.deleted_at IS NULL
        ORDER BY r.ingested_at DESC LIMIT 30
        """
    ).fetchall()
    print("\nlatest 30 ingested:")
    old_pub_count = 0
    for r in rows:
        meta = loads_meta(r["source_meta"])
        pub = published_at_iso(meta)
        pub_day = pub[:10] if pub else "?"
        ing = str(r["ingested_at"] or "")[:10]
        title = (r["raw_title"] or "")[:50]
        if pub_day != "?" and pub_day < "2026-05-01":
            old_pub_count += 1
            flag = " OLD_PUB"
        else:
            flag = ""
        print(f"  {ing} | pub {pub_day} | {r['platform']}{flag} | {title}")

    # ingested today in Shanghai
    start = today.isoformat()
    end = (today.toordinal() + 1)  # wrong - use timedelta
    from datetime import timedelta

    tomorrow = (today + timedelta(days=1)).isoformat()
    today_rows = conn.execute(
        """
        SELECT COUNT(*) AS n FROM raw_items r
        WHERE r.deleted_at IS NULL
          AND DATE(r.ingested_at) >= DATE(?)
          AND DATE(r.ingested_at) < DATE(?)
        """,
        (start, tomorrow),
    ).fetchone()
    print(f"\ningested on {today} (DATE filter):", int(today_rows["n"]))

    mismatch = conn.execute(
        """
        SELECT COUNT(*) AS n FROM raw_items r
        WHERE r.deleted_at IS NULL
          AND DATE(r.ingested_at) >= DATE(?)
          AND DATE(r.ingested_at) < DATE(?)
          AND r.source_meta IS NOT NULL
        """,
        (start, tomorrow),
    ).fetchone()
    print("of those rows, checking published in python...")
    storage.close()


if __name__ == "__main__":
    main()
