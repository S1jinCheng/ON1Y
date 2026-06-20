"""Hybrid related-item ranking: shared tags, theme, FTS recall."""

from __future__ import annotations

import logging
from typing import Any

import sqlite3

from on1y.hotlist.sql import is_feed_row_sql
from on1y.search.fts import prepare_fts_query, search_knowledge_fts

logger = logging.getLogger(__name__)

_W_TAG = 3.0
_W_THEME = 2.0
_W_FTS = 4.0
_CANDIDATE_POOL = 80

_DISTILLED_OK = """
    d.distill_status = 'ok'
    AND trim(COALESCE(d.summary, '')) <> ''
"""


def _scope_clause(scope: str) -> str:
    if scope == "books":
        return "r.platform = 'book'"
    return is_feed_row_sql("r")


def _eligible_source_row(conn: sqlite3.Connection, raw_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT
            r.id,
            r.raw_title,
            r.theme_id,
            d.summary
        FROM raw_items r
        INNER JOIN distilled_items d ON d.raw_id = r.id
        WHERE r.id = ?
          AND (r.deleted_at IS NULL OR r.deleted_at = '')
          AND {_DISTILLED_OK}
        """,
        (raw_id,),
    ).fetchone()


def _build_fts_query(row: sqlite3.Row, tag_names: list[str]) -> str:
    parts: list[str] = []
    for name in tag_names[:6]:
        name = (name or "").strip()
        if name:
            parts.append(name)
    summary = str(row["summary"] or "").strip()
    if summary:
        parts.append(summary[:120])
    title = str(row["raw_title"] or "").strip()
    if title:
        parts.append(title[:80])
    return " ".join(parts)


def _tag_overlap_candidates(
    conn: sqlite3.Connection,
    *,
    from_raw_id: int,
    theme_id: int | None,
    scope: str,
    user_clause: str,
    user_params: list[Any],
) -> list[tuple[int, float]]:
    user_filter = f" AND {user_clause}" if user_clause else ""
    params: list[Any] = [
        theme_id,
        theme_id,
        from_raw_id,
        from_raw_id,
        from_raw_id,
        *user_params,
        _CANDIDATE_POOL,
    ]
    rows = conn.execute(
        f"""
        SELECT
            r.id AS raw_id,
            COUNT(DISTINCT it2.tag_id) AS shared_tags,
            CASE WHEN ? IS NOT NULL AND r.theme_id = ? THEN 1 ELSE 0 END AS same_theme
        FROM raw_items r
        INNER JOIN distilled_items d ON d.raw_id = r.id
        INNER JOIN item_tags it2 ON it2.raw_id = r.id
        WHERE r.id != ?
          AND (r.deleted_at IS NULL OR r.deleted_at = '')
          AND {_DISTILLED_OK}
          AND {_scope_clause(scope)}
          AND it2.tag_id IN (
              SELECT tag_id FROM item_tags WHERE raw_id = ?
          )
          AND NOT EXISTS (
              SELECT 1 FROM recommendation_feedback rf
              WHERE rf.from_raw_id = ? AND rf.to_raw_id = r.id
          )
          {user_filter}
        GROUP BY r.id
        ORDER BY shared_tags DESC, same_theme DESC, r.ingested_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    scores: list[tuple[int, float]] = []
    for row in rows:
        shared = int(row["shared_tags"] or 0)
        same_theme = int(row["same_theme"] or 0)
        score = shared * _W_TAG + same_theme * _W_THEME
        if score > 0:
            scores.append((int(row["raw_id"]), score))
    return scores


def _fts_candidates(
    conn: sqlite3.Connection,
    *,
    from_raw_id: int,
    fts_query: str,
    scope: str,
    user_clause: str,
    user_params: list[Any],
) -> list[tuple[int, float]]:
    if not fts_query.strip():
        return []
    collection_sql = f"(r.deleted_at IS NULL OR r.deleted_at = '') AND {_scope_clause(scope)}"
    if user_clause:
        collection_sql += f" AND {user_clause}"
    hits, _total = search_knowledge_fts(
        conn,
        user_query=fts_query,
        limit=_CANDIDATE_POOL,
        offset=0,
        collection_sql=collection_sql,
        collection_params=user_params if user_clause else None,
    )
    blocked = {
        int(r["to_raw_id"])
        for r in conn.execute(
            "SELECT to_raw_id FROM recommendation_feedback WHERE from_raw_id = ?",
            (from_raw_id,),
        ).fetchall()
    }
    out: list[tuple[int, float]] = []
    for hit in hits:
        rid = int(hit["raw_id"])
        if rid == from_raw_id or rid in blocked:
            continue
        row = conn.execute(
            f"""
            SELECT 1 FROM raw_items r
            INNER JOIN distilled_items d ON d.raw_id = r.id
            WHERE r.id = ? AND {_DISTILLED_OK}
            """,
            (rid,),
        ).fetchone()
        if not row:
            continue
        rank = float(hit.get("search_rank") or 0.0)
        fts_score = _W_FTS / (1.0 + abs(rank))
        out.append((rid, fts_score))
    return out


def find_related_items(
    storage: Any,
    *,
    from_raw_id: int,
    limit: int = 6,
    scope: str = "library",
) -> list[dict[str, Any]]:
    """Return related knowledge items for a distilled feed entry."""
    conn = storage._connect()
    source = _eligible_source_row(conn, from_raw_id)
    if source is None:
        return []

    user_clause, user_params = storage._user_scope_parts(conn)
    if user_clause:
        owned = conn.execute(
            f"SELECT 1 FROM raw_items r WHERE r.id = ? AND {user_clause}",
            (from_raw_id, *user_params),
        ).fetchone()
        if not owned:
            return []

    tag_rows = conn.execute(
        """
        SELECT t.name
        FROM item_tags it
        JOIN tags t ON t.id = it.tag_id
        WHERE it.raw_id = ?
        ORDER BY t.name ASC
        """,
        (from_raw_id,),
    ).fetchall()
    tag_names = [str(r["name"]) for r in tag_rows]
    theme_id = int(source["theme_id"]) if source["theme_id"] is not None else None

    score_map: dict[int, float] = {}

    for raw_id, score in _tag_overlap_candidates(
        conn,
        from_raw_id=from_raw_id,
        theme_id=theme_id,
        scope=scope,
        user_clause=user_clause,
        user_params=user_params,
    ):
        score_map[raw_id] = score_map.get(raw_id, 0.0) + score

    fts_q = _build_fts_query(source, tag_names)
    if prepare_fts_query(fts_q):
        for raw_id, score in _fts_candidates(
            conn,
            from_raw_id=from_raw_id,
            fts_query=fts_q,
            scope=scope,
            user_clause=user_clause,
            user_params=user_params,
        ):
            score_map[raw_id] = score_map.get(raw_id, 0.0) + score

    if not score_map and tag_names:
        theme_only = conn.execute(
            f"""
            SELECT r.id AS raw_id
            FROM raw_items r
            INNER JOIN distilled_items d ON d.raw_id = r.id
            WHERE r.id != ?
              AND (r.deleted_at IS NULL OR r.deleted_at = '')
              AND {_DISTILLED_OK}
              AND {_scope_clause(scope)}
              AND ? IS NOT NULL AND r.theme_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM recommendation_feedback rf
                  WHERE rf.from_raw_id = ? AND rf.to_raw_id = r.id
              )
              {f" AND {user_clause}" if user_clause else ""}
            ORDER BY r.ingested_at DESC
            LIMIT ?
            """,
            (
                from_raw_id,
                theme_id,
                theme_id,
                from_raw_id,
                *user_params,
                limit,
            ),
        ).fetchall()
        for row in theme_only:
            score_map[int(row["raw_id"])] = _W_THEME

    ranked = sorted(score_map.items(), key=lambda x: (-x[1], x[0]))[:limit]
    if not ranked:
        title_q = str(source["raw_title"] or "").strip()
        if title_q and prepare_fts_query(title_q):
            for raw_id, score in _fts_candidates(
                conn,
                from_raw_id=from_raw_id,
                fts_query=title_q[:80],
                scope=scope,
                user_clause=user_clause,
                user_params=user_params,
            ):
                score_map[raw_id] = score
        ranked = sorted(score_map.items(), key=lambda x: (-x[1], x[0]))[:limit]
    if not ranked:
        return []

    raw_ids = [rid for rid, _ in ranked]
    placeholders = ",".join("?" for _ in raw_ids)
    user_filter = f" AND {user_clause}" if user_clause else ""
    rows = conn.execute(
        f"""
        SELECT
            r.id AS raw_id,
            r.url,
            r.raw_title,
            r.platform,
            r.source,
            r.content_type,
            r.ingested_at,
            r.deleted_at,
            r.source_meta,
            r.theme_id,
            d.summary,
            d.topics,
            d.prompt_version,
            d.distill_status
        FROM raw_items r
        LEFT JOIN distilled_items d ON d.raw_id = r.id
        WHERE r.id IN ({placeholders}){user_filter}
        """,
        (*raw_ids, *user_params),
    ).fetchall()
    row_by_id = {int(r["raw_id"]): r for r in rows}
    ordered = [row_by_id[rid] for rid in raw_ids if rid in row_by_id]
    items = storage._assemble_knowledge_items(ordered)
    return items

