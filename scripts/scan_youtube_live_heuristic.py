from __future__ import annotations

import re

from on1y.adapters.sqlite_storage import get_storage
from on1y.utils.json_util import loads_meta

_LIVE_URL = re.compile(r"youtube\.com/live/", re.I)
_LIVE_TITLE = re.compile(
    r"(?:\bLIVE\b|直播|正在直播|live\s*stream|stream\s*live|【直播|直播回放|\[直播)",
    re.I,
)


def main() -> None:
    storage = get_storage()
    rows = storage._connect().execute(
        """
        SELECT id, url, raw_title, source_meta
        FROM raw_items
        WHERE platform = 'youtube' AND deleted_at IS NULL
        ORDER BY id ASC
        """
    ).fetchall()
    hits: list[tuple[int, list[str], str]] = []
    for row in rows:
        url = str(row["url"] or "")
        title = str(row["raw_title"] or "")
        meta = loads_meta(row["source_meta"])
        reasons: list[str] = []
        if _LIVE_URL.search(url):
            reasons.append("url")
        if _LIVE_TITLE.search(title):
            reasons.append("title")
        if str(meta.get("live_status") or "") in {"is_live", "is_upcoming", "was_live", "post_live"}:
            reasons.append("meta_live_status")
        if meta.get("is_live") or meta.get("was_live"):
            reasons.append("meta_live_flag")
        if reasons:
            hits.append((int(row["id"]), reasons, title[:70]))
    print("total", len(rows))
    print("heuristic_hits", len(hits))
    for item in hits:
        print(item)
    storage.close()


if __name__ == "__main__":
    main()
