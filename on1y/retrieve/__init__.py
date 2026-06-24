"""Unified retrieval foundation for future RAG pipelines."""

from __future__ import annotations

from typing import Any

from on1y.recommend.similar import find_related_items


def retrieve(
    storage: Any,
    *,
    query: str | None = None,
    from_raw_id: int | None = None,
    mode: str = "keyword",
    limit: int = 20,
    offset: int = 0,
    theme_id: int | None = None,
    tag_ids: list[int] | None = None,
    collection: str = "feed",
    platform: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    mode_key = (mode or "keyword").strip().lower()
    if mode_key in {"similar", "hybrid"} and from_raw_id is not None:
        items = find_related_items(storage, from_raw_id=from_raw_id, limit=limit, scope="library")
        hits = []
        for rank, item in enumerate(items):
            score = float(item.get("search_rank") or 0.0)
            hits.append(
                {
                    "raw_id": int(item["raw_id"]),
                    "score": score,
                    "score_parts": {
                        "rank_order": max(0.0, float(limit - rank)),
                        "fts": score,
                    },
                    "item": item,
                }
            )
        return {"mode": mode_key, "engine": "related+fts", "total": len(hits), "hits": hits}

    q = (query or "").strip()
    if not q:
        rows = storage.list_knowledge_items(
            limit=limit,
            offset=offset,
            platform=platform,
            source=source,
            theme_id=theme_id,
            tag_ids=tag_ids,
            collection=collection,
        )
        hits = [
            {
                "raw_id": int(row["raw_id"]),
                "score": float(limit - idx),
                "score_parts": {"recency": float(limit - idx)},
                "item": row,
            }
            for idx, row in enumerate(rows)
        ]
        return {"mode": "list", "engine": "list", "total": len(hits), "hits": hits}

    result = storage.search_knowledge_items(
        query=q,
        limit=limit,
        offset=offset,
        platform=platform,
        source=source,
        theme_id=theme_id,
        tag_ids=tag_ids,
        collection=collection,
    )
    hits = []
    for row in result["items"]:
        rank = row.get("search_rank")
        fts_score = 0.0
        if isinstance(rank, (int, float)):
            fts_score = 1.0 / (1.0 + abs(float(rank)))
        hits.append(
            {
                "raw_id": int(row["raw_id"]),
                "score": fts_score,
                "score_parts": {"fts": fts_score},
                "item": row,
            }
        )
    return {
        "mode": "keyword" if mode_key not in {"hybrid", "semantic"} else mode_key,
        "engine": result.get("engine", "fts5"),
        "total": int(result.get("total") or len(hits)),
        "hits": hits,
    }


def pack_context(
    storage: Any,
    raw_ids: list[int],
    *,
    max_chars_per_doc: int = 4000,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for raw_id in raw_ids:
        raw = storage.get_raw_by_id_for_user(int(raw_id))
        if raw is None:
            continue
        reader = storage.get_reader_content(int(raw_id)) or {}
        body = str(reader.get("body_text") or "")
        if len(body) > max_chars_per_doc:
            body = body[:max_chars_per_doc]
        contexts.append(
            {
                "raw_id": int(raw_id),
                "title": raw.raw_title,
                "url": raw.url,
                "platform": raw.platform.value if hasattr(raw.platform, "value") else str(raw.platform),
                "summary": str(reader.get("summary") or "").strip(),
                "body_text": body,
                "tags": list(storage.get_item_tag_names(int(raw_id))),
            }
        )
    return contexts
