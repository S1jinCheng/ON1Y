"""Profile creator sidebar / filter API latency."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "on1y.db"


def timed(label: str, fn):
    t0 = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - t0) * 1000
    print(f"{label:40s} {ms:8.1f} ms")
    return result


def profile_storage():
    from on1y.adapters.sqlite_storage import SqliteStorage

    storage = SqliteStorage(DB)
    try:
        creators = timed("list_subscribed_creators", storage.list_subscribed_creators)
        print(f"  creators: {len(creators)}")
        if creators:
            key = creators[0]["key"]
            timed(
                "list_knowledge_items (creator)",
                lambda: storage.list_knowledge_items(
                    limit=40, offset=0, creator_key=key, collection="feed"
                ),
            )
            timed(
                "count_knowledge_items (creator)",
                lambda: storage.count_knowledge_items(
                    creator_key=key, collection="feed"
                ),
            )
        timed("list_knowledge_items (all)", lambda: storage.list_knowledge_items(limit=40))
        timed("list_tags_with_counts", storage.list_tags_with_counts)
    finally:
        storage.close()


def profile_http(base: str = "http://127.0.0.1:8765", token: str | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def get(path: str) -> dict:
        req = urllib.request.Request(f"{base}{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())

    timed("GET /api/knowledge/creators", lambda: get("/api/knowledge/creators"))
    creators = get("/api/knowledge/creators").get("creators", [])
    if creators:
        key = urllib.parse.quote(creators[0]["key"])
        timed(
            f"GET items creator_key=...",
            lambda: get(f"/api/knowledge/items?creator_key={key}&limit=40"),
        )
    timed("GET /api/knowledge/taxonomy", lambda: get("/api/knowledge/taxonomy"))
    timed("GET /api/knowledge/items", lambda: get("/api/knowledge/items?limit=40"))


if __name__ == "__main__":
    print("=== SQLite direct ===")
    profile_storage()
    print("\n=== HTTP (needs auth token in ON1Y_TOKEN env) ===")
    import os

    token = os.environ.get("ON1Y_TOKEN")
    if token:
        profile_http(token=token)
    else:
        print("skip HTTP (set ON1Y_TOKEN)")
