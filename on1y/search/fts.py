"""SQLite FTS5 (trigram) indexing and ranked search for knowledge items."""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

# bm25() column weights: title, summary, body, tags, author, theme
_BM25_WEIGHTS = (15.0, 8.0, 1.0, 5.0, 3.0, 2.0)
_BODY_INDEX_CHARS = 32_000
_FTS_SPECIAL_RE = re.compile(r'["\']')

_MARK_OPEN = "<mark>"
_MARK_CLOSE = "</mark>"


def prepare_fts_query(user_query: str) -> str:
    """Turn user input into a safe FTS5 MATCH string (trigram: quoted terms ANDed)."""
    terms = _query_terms(user_query)
    if not terms:
        return ""
    return " AND ".join(f'"{t.replace(chr(34), chr(34)*2)}"' for t in terms)


def _query_terms(user_query: str) -> list[str]:
    text = (user_query or "").strip()
    if not text:
        return []
    if len(text) >= 2 and text[0] == text[-1] == '"':
        inner = text[1:-1].strip()
        return [inner] if inner else []
    return [part.strip() for part in text.split() if part.strip()]


def _has_short_trigram_terms(user_query: str) -> bool:
    """Trigram tokenizer requires at least 3 characters per term."""
    return any(len(term) < 3 for term in _query_terms(user_query))


def _normalize_index_text(value: str | None, *, max_len: int) -> str:
    if not value:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) > max_len:
        return text[:max_len]
    return text


def _fetch_index_payload(conn: sqlite3.Connection, raw_id: int) -> dict[str, str] | None:
    row = conn.execute(
        """
        SELECT
            r.id,
            r.raw_title,
            r.body_text,
            r.extract_status,
            r.source_meta,
            d.summary,
            th.name_zh AS theme_zh,
            th.name_en AS theme_en
        FROM raw_items r
        LEFT JOIN distilled_items d ON d.raw_id = r.id
        LEFT JOIN themes th ON th.id = r.theme_id
        WHERE r.id = ?
        """,
        (raw_id,),
    ).fetchone()
    if row is None:
        return None
    if str(row["extract_status"]) not in ("ok", "partial"):
        return None

    from on1y.utils.author_meta import author_fields_from_meta
    from on1y.utils.json_util import loads_meta

    meta = loads_meta(row["source_meta"])
    author_info = author_fields_from_meta(meta)
    tag_rows = conn.execute(
        """
        SELECT t.name FROM item_tags it
        JOIN tags t ON t.id = it.tag_id
        WHERE it.raw_id = ?
        ORDER BY t.name ASC
        """,
        (raw_id,),
    ).fetchall()
    tags_text = " ".join(str(r["name"]) for r in tag_rows)
    theme_parts = [str(row["theme_zh"] or ""), str(row["theme_en"] or "")]
    theme_text = " ".join(p for p in theme_parts if p.strip())

    summary = row["summary"] or meta.get("entry_excerpt") or ""
    return {
        "title": _normalize_index_text(row["raw_title"], max_len=500),
        "summary": _normalize_index_text(str(summary), max_len=4_000),
        "body": _normalize_index_text(row["body_text"], max_len=_BODY_INDEX_CHARS),
        "tags": _normalize_index_text(tags_text, max_len=1_000),
        "author": _normalize_index_text(author_info.get("author"), max_len=200),
        "theme": _normalize_index_text(theme_text, max_len=200),
    }


def delete_fts_row(conn: sqlite3.Connection, raw_id: int) -> None:
    conn.execute("DELETE FROM knowledge_fts WHERE rowid = ?", (raw_id,))


def index_raw_item(conn: sqlite3.Connection, raw_id: int) -> None:
    """Upsert one knowledge row into FTS (rowid = raw_id)."""
    payload = _fetch_index_payload(conn, raw_id)
    has_row = (
        conn.execute("SELECT rowid FROM knowledge_fts WHERE rowid = ?", (raw_id,)).fetchone()
        is not None
    )
    if payload is None:
        if has_row:
            delete_fts_row(conn, raw_id)
        return
    if has_row:
        delete_fts_row(conn, raw_id)
    conn.execute(
        """
        INSERT INTO knowledge_fts(rowid, title, summary, body, tags, author, theme)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_id,
            payload["title"],
            payload["summary"],
            payload["body"],
            payload["tags"],
            payload["author"],
            payload["theme"],
        ),
    )


def rebuild_knowledge_fts(conn: sqlite3.Connection) -> int:
    """Rebuild the entire FTS index from raw_items. Returns rows indexed."""
    conn.execute("DELETE FROM knowledge_fts")
    rows = conn.execute(
        """
        SELECT id FROM raw_items
        WHERE extract_status IN ('ok', 'partial')
        ORDER BY id ASC
        """
    ).fetchall()
    count = 0
    for row in rows:
        index_raw_item(conn, int(row["id"]))
        count += 1
    conn.execute(
        """
        INSERT INTO knowledge_fts_meta (key, value) VALUES ('rebuilt_at', datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """
    )
    logger.info("Rebuilt knowledge FTS index: %s documents", count)
    return count


def fts_index_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM knowledge_fts").fetchone()
    return int(row["n"]) if row else 0


def search_knowledge_fts(
    conn: sqlite3.Connection,
    *,
    user_query: str,
    limit: int = 40,
    offset: int = 0,
    platform: str | None = None,
    source: str | None = None,
    theme_id: int | None = None,
    tag_ids: list[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Ranked FTS search. Returns (hits, total_estimate).
    Each hit: raw_id, search_rank, search_snippet, search_title_html, search_summary_html.
    """
    terms = _query_terms(user_query)
    if not terms:
        return [], 0
    if _has_short_trigram_terms(user_query):
        return _search_hybrid(
            conn,
            terms=terms,
            limit=limit,
            offset=offset,
            platform=platform,
            source=source,
            theme_id=theme_id,
            tag_ids=tag_ids,
        )
    return _search_fts_bm25(
        conn,
        fts_q=prepare_fts_query(user_query),
        limit=limit,
        offset=offset,
        platform=platform,
        source=source,
        theme_id=theme_id,
        tag_ids=tag_ids,
    )


def _search_fts_bm25(
    conn: sqlite3.Connection,
    *,
    fts_q: str,
    limit: int,
    offset: int,
    platform: str | None,
    source: str | None,
    theme_id: int | None,
    tag_ids: list[int] | None,
) -> tuple[list[dict[str, Any]], int]:
    where_parts = ["knowledge_fts MATCH ?"]
    params: list[Any] = [fts_q]

    if platform:
        where_parts.append("r.platform = ?")
        params.append(platform)
    if source:
        where_parts.append("r.source = ?")
        params.append(source)
    if theme_id is not None:
        where_parts.append("r.theme_id = ?")
        params.append(theme_id)
    if tag_ids:
        placeholders = ",".join("?" for _ in tag_ids)
        where_parts.append(
            f"EXISTS (SELECT 1 FROM item_tags itf WHERE itf.raw_id = r.id AND itf.tag_id IN ({placeholders}))"
        )
        params.extend(tag_ids)

    where_sql = " AND ".join(where_parts)
    bm25_args = ", ".join(str(w) for w in _BM25_WEIGHTS)

    count_row = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM knowledge_fts
        JOIN raw_items r ON r.id = knowledge_fts.rowid
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    total = int(count_row["n"]) if count_row else 0

    rows = conn.execute(
        f"""
        SELECT
            r.id AS raw_id,
            bm25(knowledge_fts, {bm25_args}) AS search_rank,
            snippet(knowledge_fts, 1, ?, ?, '…', 32) AS search_summary_html,
            snippet(knowledge_fts, 0, ?, ?, '…', 20) AS search_title_html,
            snippet(knowledge_fts, 2, ?, ?, '…', 40) AS search_body_html
        FROM knowledge_fts
        JOIN raw_items r ON r.id = knowledge_fts.rowid
        WHERE {where_sql}
        ORDER BY search_rank ASC, r.ingested_at DESC
        LIMIT ? OFFSET ?
        """,
        (
            _MARK_OPEN,
            _MARK_CLOSE,
            _MARK_OPEN,
            _MARK_CLOSE,
            _MARK_OPEN,
            _MARK_CLOSE,
            *params,
            limit,
            offset,
        ),
    ).fetchall()

    hits: list[dict[str, Any]] = []
    for row in rows:
        summary_html = row["search_summary_html"] or row["search_body_html"] or ""
        title_html = row["search_title_html"] or ""
        hits.append(
            {
                "raw_id": int(row["raw_id"]),
                "search_rank": float(row["search_rank"]) if row["search_rank"] is not None else 0.0,
                "search_snippet": _strip_marks(summary_html) or _strip_marks(row["search_body_html"] or ""),
                "search_title_html": title_html,
                "search_summary_html": summary_html or row["search_body_html"] or "",
            }
        )
    return hits, total


def _search_hybrid(
    conn: sqlite3.Connection,
    *,
    terms: list[str],
    limit: int,
    offset: int,
    platform: str | None,
    source: str | None,
    theme_id: int | None,
    tag_ids: list[int] | None,
) -> tuple[list[dict[str, Any]], int]:
    """LIKE fallback for terms shorter than trigram minimum (3 chars)."""
    where_parts = ["r.extract_status IN ('ok', 'partial')"]
    params: list[Any] = []
    for term in terms:
        like = f"%{term}%"
        where_parts.append(
            "("
            "COALESCE(r.raw_title, '') LIKE ? "
            "OR COALESCE(d.summary, '') LIKE ? "
            "OR COALESCE(r.body_text, '') LIKE ? "
            "OR EXISTS ("
            "SELECT 1 FROM item_tags it "
            "JOIN tags t ON t.id = it.tag_id "
            "WHERE it.raw_id = r.id AND t.name LIKE ?"
            ")"
            ")"
        )
        params.extend([like, like, like, like])

    if platform:
        where_parts.append("r.platform = ?")
        params.append(platform)
    if source:
        where_parts.append("r.source = ?")
        params.append(source)
    if theme_id is not None:
        where_parts.append("r.theme_id = ?")
        params.append(theme_id)
    if tag_ids:
        placeholders = ",".join("?" for _ in tag_ids)
        where_parts.append(
            f"EXISTS (SELECT 1 FROM item_tags itf WHERE itf.raw_id = r.id AND itf.tag_id IN ({placeholders}))"
        )
        params.extend(tag_ids)

    where_sql = " AND ".join(where_parts)
    rank_parts: list[str] = []
    rank_params: list[Any] = []
    for term in terms:
        like = f"%{term}%"
        rank_parts.append(
            "(CASE WHEN COALESCE(r.raw_title, '') LIKE ? THEN 15.0 ELSE 0 END + "
            "CASE WHEN COALESCE(d.summary, '') LIKE ? THEN 8.0 ELSE 0 END + "
            "CASE WHEN COALESCE(r.body_text, '') LIKE ? THEN 1.0 ELSE 0 END)"
        )
        rank_params.extend([like, like, like])

    rank_sql = " + ".join(rank_parts) if rank_parts else "0"

    count_row = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM raw_items r
        LEFT JOIN distilled_items d ON d.raw_id = r.id
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    total = int(count_row["n"]) if count_row else 0

    rows = conn.execute(
        f"""
        SELECT
            r.id AS raw_id,
            ({rank_sql}) AS search_rank,
            COALESCE(r.raw_title, '') AS raw_title,
            COALESCE(d.summary, '') AS summary,
            COALESCE(r.body_text, '') AS body_text
        FROM raw_items r
        LEFT JOIN distilled_items d ON d.raw_id = r.id
        WHERE {where_sql}
        ORDER BY search_rank DESC, r.ingested_at DESC
        LIMIT ? OFFSET ?
        """,
        (*params, *rank_params, limit, offset),
    ).fetchall()

    hits: list[dict[str, Any]] = []
    for row in rows:
        title = str(row["raw_title"] or "")
        summary = str(row["summary"] or "")
        body = str(row["body_text"] or "")
        title_html = _highlight_terms(title, terms) if title else ""
        summary_html = _highlight_terms(summary or body, terms)
        snippet = _strip_marks(summary_html) or _strip_marks(_highlight_terms(body, terms))
        hits.append(
            {
                "raw_id": int(row["raw_id"]),
                "search_rank": -float(row["search_rank"] or 0.0),
                "search_snippet": snippet[:240],
                "search_title_html": title_html,
                "search_summary_html": summary_html,
            }
        )
    return hits, total


def _highlight_terms(text: str, terms: list[str]) -> str:
    if not text:
        return ""
    result = text
    for term in sorted(terms, key=len, reverse=True):
        if not term:
            continue
        result = result.replace(term, f"{_MARK_OPEN}{term}{_MARK_CLOSE}")
    return result


def _strip_marks(html: str) -> str:
    return html.replace(_MARK_OPEN, "").replace(_MARK_CLOSE, "").strip()
