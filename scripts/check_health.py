"""Quick health: DB queue + tips for logs (API needs browser auth)."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone

DB = r"D:\On1y\data\on1y.db"
API = "http://127.0.0.1:8765"


def main() -> None:
    print("=== DB ===")
    conn = sqlite3.connect(DB)
    pending = conn.execute(
        "SELECT COUNT(*) FROM pending_urls WHERE status = 'pending'"
    ).fetchone()[0]
    failed = conn.execute(
        "SELECT COUNT(*) FROM pending_urls WHERE status = 'failed'"
    ).fetchone()[0]
    raw = conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
    distilled = conn.execute("SELECT COUNT(*) FROM distilled_items").fetchone()[0]
    need_distill = conn.execute(
        """
        SELECT COUNT(*) FROM raw_items r
        LEFT JOIN distilled_items d ON d.raw_id = r.id
        WHERE d.id IS NULL
        """
    ).fetchone()[0]
    print(f"pending_urls: {pending}  failed: {failed}")
    print(f"raw_items: {raw}  distilled: {distilled}  without_distill: {need_distill}")

    last_raw = conn.execute(
        "SELECT MAX(ingested_at) FROM raw_items"
    ).fetchone()[0]
    last_pending = conn.execute(
        "SELECT MAX(updated_at) FROM pending_urls"
    ).fetchone()[0]
    print(f"last ingested_at: {last_raw}")
    print(f"last pending update: {last_pending}")

    recent_pending = conn.execute(
        """
        SELECT id, substr(url,1,72), status, attempts, updated_at
        FROM pending_urls ORDER BY id DESC LIMIT 3
        """
    ).fetchall()
    print("recent queue:", recent_pending)

    recent_raw = conn.execute(
        """
        SELECT id, platform, substr(url,1,50), extract_status, ingested_at
        FROM raw_items ORDER BY id DESC LIMIT 3
        """
    ).fetchall()
    print("recent raw:", recent_raw)
    conn.close()

    timing_path = r"D:\On1y\data\sync_timing_history.jsonl"
    try:
        with open(timing_path, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        if lines:
            print("\n=== last cold-start timing ===")
            print(lines[-1][:2000])
    except FileNotFoundError:
        print("\n(no sync_timing_history.jsonl yet)")

    print("\n=== API cold-start/status (needs login token) ===")
    try:
        with urllib.request.urlopen(f"{API}/api/cold-start/status", timeout=5) as resp:
            print(json.dumps(json.loads(resp.read().decode()), indent=2, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:200]
        print(f"HTTP {exc.code}: {body}")
        if exc.code == 401:
            print("→ Open DevTools in the app: Network → cold-start/status (while logged in)")
    except Exception as exc:
        print(f"API error: {exc}")

    print("\n=== Logs ===")
    print("On1y logs go to the 'On1y Backend' PowerShell window (on1y serve), not a file.")
    print("Taskbar → look for minimized PowerShell titled 'On1y Backend'.")
    print("More verbose: set ON1Y_LOG_LEVEL=DEBUG in .env and restart serve.")


if __name__ == "__main__":
    main()
