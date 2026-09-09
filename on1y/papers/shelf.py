"""Per-user paper library CRUD."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.papers.models import (
    PaperAuthor,
    PaperCreate,
    PaperItem,
    PaperUpdate,
    paper_from_row,
)
from on1y.utils.json_util import dumps_json


def _tags(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        name = str(value).strip().lstrip("#")
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


_DOI_PREFIX = re.compile(
    r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)",
    flags=re.IGNORECASE,
)


def normalize_doi(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    normalized = _DOI_PREFIX.sub("", normalized).split("?", 1)[0].split("#", 1)[0]
    return normalized.rstrip(" .;,").casefold()


def normalize_title(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    if normalized.endswith(".pdf"):
        normalized = normalized[:-4]
    return "".join(char for char in normalized if char.isalnum())


def normalize_pdf_path(value: str | None) -> str:
    if not value:
        return ""
    try:
        resolved = str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        resolved = str(value)
    return os.path.normcase(resolved).casefold()


def _author_keys(values: Iterable[PaperAuthor | str] | None) -> set[str]:
    result: set[str] = set()
    for value in values or []:
        name = value.name if isinstance(value, PaperAuthor) else str(value)
        key = normalize_title(name)
        if key:
            result.add(key)
    return result


def find_matching_paper(
    storage: SqliteStorage,
    user_id: int,
    *,
    zotero_library_id: str | None = None,
    zotero_key: str | None = None,
    doi: str | None = None,
    title: str | None = None,
    year: int | None = None,
    authors: Iterable[PaperAuthor | str] | None = None,
    pdf_path: str | None = None,
) -> PaperItem | None:
    """Find the same paper across Zotero, DOI metadata, and local files."""

    if zotero_key and zotero_library_id:
        exact = get_paper_by_zotero(
            storage,
            user_id,
            zotero_library_id.strip(),
            zotero_key.strip(),
        )
        if exact is not None:
            return exact

    rows = (
        storage._connect()
        .execute(
            "SELECT * FROM paper_items WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        )
        .fetchall()
    )
    items = [paper_from_row(row) for row in rows]

    doi_key = normalize_doi(doi)
    if doi_key:
        for item in items:
            if normalize_doi(item.doi) == doi_key:
                return item

    path_key = normalize_pdf_path(pdf_path)
    if path_key:
        for item in items:
            if normalize_pdf_path(item.pdf_path) == path_key:
                return item

    title_key = normalize_title(title)
    if not title_key:
        return None
    incoming_authors = _author_keys(authors)
    for item in items:
        if normalize_title(item.title) != title_key:
            continue
        if year and item.year and year != item.year:
            continue
        existing_authors = _author_keys(item.authors)
        if incoming_authors and existing_authors and incoming_authors.isdisjoint(existing_authors):
            continue
        return item
    return None


def count_papers(storage: SqliteStorage, user_id: int) -> int:
    row = (
        storage._connect()
        .execute("SELECT COUNT(*) AS n FROM paper_items WHERE user_id = ?", (user_id,))
        .fetchone()
    )
    return int(row["n"]) if row else 0


def list_papers(
    storage: SqliteStorage,
    user_id: int,
    *,
    status: str | None = None,
    query: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[PaperItem]:
    where = ["user_id = ?"]
    params: list[Any] = [user_id]
    if status in {"to_read", "reading", "read"}:
        where.append("status = ?")
        params.append(status)
    if query and query.strip():
        needle = f"%{query.strip()}%"
        where.append(
            "(title LIKE ? OR authors_json LIKE ? OR COALESCE(abstract, '') LIKE ? "
            "OR COALESCE(doi, '') LIKE ? OR COALESCE(venue, '') LIKE ?)"
        )
        params.extend([needle] * 5)
    params.extend([limit, offset])
    rows = (
        storage._connect()
        .execute(
            f"""
        SELECT * FROM paper_items WHERE {" AND ".join(where)}
        ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?
        """,
            params,
        )
        .fetchall()
    )
    return [paper_from_row(row) for row in rows]


def get_paper(storage: SqliteStorage, user_id: int, item_id: int) -> PaperItem | None:
    row = (
        storage._connect()
        .execute("SELECT * FROM paper_items WHERE user_id = ? AND id = ?", (user_id, item_id))
        .fetchone()
    )
    return paper_from_row(row) if row else None


def get_paper_by_zotero(
    storage: SqliteStorage, user_id: int, library_id: str, zotero_key: str
) -> PaperItem | None:
    row = (
        storage._connect()
        .execute(
            """SELECT * FROM paper_items
           WHERE user_id = ? AND zotero_library_id = ? AND zotero_key = ?""",
            (user_id, library_id, zotero_key),
        )
        .fetchone()
    )
    return paper_from_row(row) if row else None


def create_paper(storage: SqliteStorage, user_id: int, payload: PaperCreate) -> PaperItem:
    cur = storage._connect().execute(
        """
        INSERT INTO paper_items (
            user_id, title, authors_json, abstract, status, year, venue, doi, url,
            pdf_path, zotero_key, zotero_library_id, zotero_attachment_key,
            zotero_library_type, zotero_version, citation_count, tags_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            payload.title.strip(),
            dumps_json([row.model_dump() for row in payload.authors]),
            (payload.abstract or "").strip() or None,
            payload.status,
            payload.year,
            (payload.venue or "").strip() or None,
            (payload.doi or "").strip() or None,
            (payload.url or "").strip() or None,
            (payload.pdf_path or "").strip() or None,
            (payload.zotero_key or "").strip() or None,
            (payload.zotero_library_id or "").strip() or None,
            (payload.zotero_attachment_key or "").strip() or None,
            payload.zotero_library_type,
            payload.zotero_version,
            payload.citation_count,
            dumps_json(_tags(payload.tags)),
        ),
    )
    storage._connect().commit()
    item = get_paper(storage, user_id, int(cur.lastrowid))
    assert item is not None
    return item


def update_paper(
    storage: SqliteStorage, user_id: int, item_id: int, payload: PaperUpdate
) -> PaperItem | None:
    existing = get_paper(storage, user_id, item_id)
    if existing is None:
        return None
    supplied = payload.model_fields_set

    def choose(name: str, old: Any) -> Any:
        value = getattr(payload, name)
        return value if name in supplied else old

    authors = choose("authors", existing.authors) or []
    tags = _tags(choose("tags", existing.tags) or [])
    values = {
        "title": choose("title", existing.title),
        "abstract": choose("abstract", existing.abstract),
        "status": choose("status", existing.status),
        "year": choose("year", existing.year),
        "venue": choose("venue", existing.venue),
        "doi": choose("doi", existing.doi),
        "url": choose("url", existing.url),
        "pdf_path": choose("pdf_path", existing.pdf_path),
        "citation_count": choose("citation_count", existing.citation_count),
        "user_note_html": choose("user_note_html", existing.user_note_html),
        "importance": choose("importance", existing.importance),
        "theme_slug": choose("theme_slug", existing.theme_slug),
        "zotero_key": choose("zotero_key", existing.zotero_key),
        "zotero_library_id": choose("zotero_library_id", existing.zotero_library_id),
        "zotero_attachment_key": choose("zotero_attachment_key", existing.zotero_attachment_key),
        "zotero_library_type": choose("zotero_library_type", existing.zotero_library_type),
        "zotero_version": choose("zotero_version", existing.zotero_version),
    }
    for key in (
        "title",
        "abstract",
        "venue",
        "doi",
        "url",
        "pdf_path",
        "user_note_html",
        "theme_slug",
        "zotero_key",
        "zotero_library_id",
        "zotero_attachment_key",
        "zotero_library_type",
    ):
        if isinstance(values[key], str):
            values[key] = values[key].strip() or None
    values["title"] = values["title"] or existing.title
    conn = storage._connect()
    conn.execute(
        """
        UPDATE paper_items SET title = ?, authors_json = ?, abstract = ?, status = ?,
            year = ?, venue = ?, doi = ?, url = ?, pdf_path = ?, citation_count = ?,
            user_note_html = ?, importance = ?, theme_slug = ?, tags_json = ?,
            zotero_key = ?, zotero_library_id = ?, zotero_attachment_key = ?,
            zotero_library_type = ?, zotero_version = ?,
            updated_at = datetime('now')
        WHERE user_id = ? AND id = ?
        """,
        (
            values["title"],
            dumps_json([row.model_dump() for row in authors]),
            values["abstract"],
            values["status"],
            values["year"],
            values["venue"],
            values["doi"],
            values["url"],
            values["pdf_path"],
            values["citation_count"],
            values["user_note_html"],
            values["importance"],
            values["theme_slug"],
            dumps_json(tags),
            values["zotero_key"],
            values["zotero_library_id"],
            values["zotero_attachment_key"],
            values["zotero_library_type"],
            values["zotero_version"],
            user_id,
            item_id,
        ),
    )
    conn.commit()
    return get_paper(storage, user_id, item_id)


def delete_paper(storage: SqliteStorage, user_id: int, item_id: int) -> bool:
    existing = get_paper(storage, user_id, item_id)
    if existing is None:
        return False
    conn = storage._connect()
    conn.execute("DELETE FROM paper_items WHERE user_id = ? AND id = ?", (user_id, item_id))
    if existing.raw_id is not None:
        conn.execute(
            "DELETE FROM raw_items WHERE id = ? AND user_id = ?", (existing.raw_id, user_id)
        )
    conn.commit()
    return True
