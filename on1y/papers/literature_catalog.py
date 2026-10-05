"""Portable, allow-listed sidecars for rebuilding a Literature catalog.

The live ``_system/papers.db`` database is intentionally device-local.  This
module serializes only the canonical catalog rows needed to reconstruct the
``papers``, ``batches`` and ``batch_papers`` tables.  Operational tables such
as translation jobs, download attempts and scan caches are not portable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from on1y.papers.literature import (
    READING_STATUSES,
    LiteratureVault,
    normalize_arxiv,
    normalize_doi,
    normalize_title,
)

CATALOG_VERSION = 1
CATALOG_ROOT = Path("_catalog") / f"v{CATALOG_VERSION}"
MAX_SIDECAR_BYTES = 4 * 1024 * 1024
MAX_ID_LENGTH = 512
MAX_PATH_LENGTH = 4096

_PAPER_KEYS = {
    "id",
    "title",
    "authors",
    "abstract",
    "year",
    "venue",
    "doi",
    "arxiv_id",
    "semantic_scholar_id",
    "source_url",
    "pdf_url",
    "citation_count",
    "area",
    "age_category",
    "recommendation",
    "status",
    "read_date",
    "pdf_sha256",
    "created_at",
    "updated_at",
    "roles",
}
_BATCH_KEYS = {
    "id",
    "field",
    "field_slug",
    "field_code",
    "batch_date",
    "status",
    "created_at",
    "published_at",
}
_MEMBER_KEYS = {"paper_id", "position"}
_ROLE_KEYS = {"original", "bilingual", "note"}
_BATCH_STATUSES = {"draft", "publishing", "published", "error"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT = 0x400


class LiteratureCatalogError(ValueError):
    """A portable catalog is malformed or unsafe to apply."""


class LiteratureCatalogConflictError(LiteratureCatalogError):
    """Incoming catalog state conflicts with non-empty local catalog state."""


@dataclass(frozen=True)
class CatalogPlan:
    """A fully validated, write-free reconciliation plan."""

    library_id: str
    papers: tuple[dict[str, Any], ...]
    batches: tuple[dict[str, Any], ...]
    memberships: tuple[tuple[str, str, int], ...]
    deleted_paper_ids: tuple[str, ...]
    deleted_batch_ids: tuple[str, ...]


def _canonical_library_id(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LiteratureCatalogError("invalid catalog library_id") from exc


def _catalog_filename(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest() + ".json"


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"


def _atomic_write_text(path: Path, body: str) -> bool:
    """Atomically write changed content and return whether bytes changed."""

    if path.exists():
        info = path.lstat()
        attributes = int(getattr(info, "st_file_attributes", 0))
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or (
            attributes & _REPARSE_POINT
        ):
            raise LiteratureCatalogError("catalog sidecar target is unsafe")
        if path.read_text(encoding="utf-8") == body:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _catalog_directory(root: Path, leaf: str, *, create: bool) -> Path:
    """Resolve an app-owned catalog directory without following links."""
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise LiteratureCatalogError("Literature Vault is unavailable") from exc
    current = resolved_root
    for part in (*CATALOG_ROOT.parts, leaf):
        current = current / part
        if current.exists():
            info = current.lstat()
            attributes = int(getattr(info, "st_file_attributes", 0))
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or attributes & _REPARSE_POINT
            ):
                raise LiteratureCatalogError("catalog directory is unsafe")
        elif create:
            current.mkdir()
        else:
            return current
        if not current.resolve(strict=False).is_relative_to(resolved_root):
            raise LiteratureCatalogError("catalog directory escapes Literature Vault")
    return current


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LiteratureCatalogError(f"{label} must be an object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing=" + ",".join(sorted(missing)))
        if extra:
            detail.append("extra=" + ",".join(sorted(extra)))
        raise LiteratureCatalogError(f"invalid {label} fields ({'; '.join(detail)})")


def _required_text(value: object, label: str, *, maximum: int = 8192) -> str:
    if not isinstance(value, str):
        raise LiteratureCatalogError(f"{label} must be text")
    text = value.strip()
    if not text or len(text) > maximum or any(ord(char) < 32 for char in text):
        raise LiteratureCatalogError(f"invalid {label}")
    return text


def _optional_text(value: object, label: str, *, maximum: int = 2_000_000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise LiteratureCatalogError(f"invalid {label}")
    return value.strip() or None


def _optional_integer(value: object, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        raise LiteratureCatalogError(f"invalid {label}")
    return value


def _optional_iso_date(value: object, label: str) -> str | None:
    text = _optional_text(value, label, maximum=64)
    if text is None:
        return None
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise LiteratureCatalogError(f"invalid {label}") from exc
    return text


def _required_timestamp(value: object, label: str) -> str:
    text = _required_text(value, label, maximum=128)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiteratureCatalogError(f"invalid {label}") from exc
    return text


def _optional_timestamp(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_timestamp(value, label)


def _portable_url(value: object, label: str) -> str | None:
    text = _optional_text(value, label, maximum=8192)
    if text is None:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError as exc:
        raise LiteratureCatalogError(f"invalid {label}") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise LiteratureCatalogError(f"{label} must be a public http(s) URL")
    return text


def _export_url(value: object) -> str | None:
    """Drop local or credential-bearing URLs instead of exporting them."""

    if not value:
        return None
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return None
    return str(value)


def _relative_role_path(root: Path, value: object, role: str) -> str | None:
    text = _optional_text(value, f"roles.{role}", maximum=MAX_PATH_LENGTH)
    if text is None:
        return None
    if text != unicodedata.normalize("NFC", text) or "\\" in text:
        raise LiteratureCatalogError(f"roles.{role} is not a canonical POSIX path")
    pure = PurePosixPath(text)
    expected_directory = {"original": "Original", "bilingual": "Bilingual", "note": "Notes"}[
        role
    ]
    expected_suffix = ".md" if role == "note" else ".pdf"
    if (
        pure.is_absolute()
        or len(pure.parts) < 4
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.parts[-2] != expected_directory
        or pure.suffix.casefold() != expected_suffix
    ):
        raise LiteratureCatalogError(f"invalid roles.{role} path")
    resolved_root = root.resolve(strict=False)
    candidate = root.joinpath(*pure.parts)
    resolved = candidate.resolve(strict=False)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise LiteratureCatalogError(f"roles.{role} escapes Literature Vault")
    if candidate.is_symlink() or not candidate.is_file():
        raise LiteratureCatalogError(f"roles.{role} file is missing or unsafe: {text}")
    return text


def _authors(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 1000:
        raise LiteratureCatalogError("paper.authors must be a list")
    result = []
    for author in value:
        result.append(_required_text(author, "paper.authors[]", maximum=1000))
    return result


def _validate_paper_payload(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    _require_exact_keys(payload, _PAPER_KEYS, "paper")
    paper_id = _required_text(payload["id"], "paper.id", maximum=MAX_ID_LENGTH)
    title = _required_text(payload["title"], "paper.title", maximum=100_000)
    roles = _require_object(payload["roles"], "paper.roles")
    _require_exact_keys(roles, _ROLE_KEYS, "paper.roles")
    status = _required_text(payload["status"], "paper.status", maximum=32)
    if status not in READING_STATUSES:
        raise LiteratureCatalogError("invalid paper.status")
    doi = _optional_text(payload["doi"], "paper.doi", maximum=8192)
    arxiv_id = _optional_text(payload["arxiv_id"], "paper.arxiv_id", maximum=8192)
    sha256 = _optional_text(payload["pdf_sha256"], "paper.pdf_sha256", maximum=64)
    if sha256 is not None and not _SHA256_RE.fullmatch(sha256):
        raise LiteratureCatalogError("invalid paper.pdf_sha256")
    return {
        "id": paper_id,
        "title": title,
        "authors": _authors(payload["authors"]),
        "abstract": _optional_text(payload["abstract"], "paper.abstract"),
        "year": _optional_integer(payload["year"], "paper.year"),
        "venue": _optional_text(payload["venue"], "paper.venue", maximum=100_000),
        "doi": normalize_doi(doi) if doi else None,
        "arxiv_id": normalize_arxiv(arxiv_id) if arxiv_id else None,
        "semantic_scholar_id": _optional_text(
            payload["semantic_scholar_id"],
            "paper.semantic_scholar_id",
            maximum=8192,
        ),
        "source_url": _portable_url(payload["source_url"], "paper.source_url"),
        "pdf_url": _portable_url(payload["pdf_url"], "paper.pdf_url"),
        "citation_count": _optional_integer(
            payload["citation_count"], "paper.citation_count"
        ),
        "area": _optional_text(payload["area"], "paper.area", maximum=100_000),
        "age_category": _optional_text(
            payload["age_category"], "paper.age_category", maximum=100_000
        ),
        "recommendation": _optional_text(payload["recommendation"], "paper.recommendation"),
        "status": status,
        "read_date": _optional_iso_date(payload["read_date"], "paper.read_date"),
        "pdf_sha256": sha256,
        "created_at": _required_timestamp(payload["created_at"], "paper.created_at"),
        "updated_at": _required_timestamp(payload["updated_at"], "paper.updated_at"),
        "roles": {
            role: _relative_role_path(root, roles[role], role) for role in sorted(_ROLE_KEYS)
        },
    }


def _validate_batch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _require_exact_keys(payload, _BATCH_KEYS, "batch")
    batch_id = _required_text(payload["id"], "batch.id", maximum=MAX_ID_LENGTH)
    field_slug = _required_text(payload["field_slug"], "batch.field_slug", maximum=512)
    pure_slug = PurePosixPath(field_slug)
    if (
        pure_slug.is_absolute()
        or len(pure_slug.parts) != 1
        or field_slug in {".", ".."}
        or "\\" in field_slug
    ):
        raise LiteratureCatalogError("invalid batch.field_slug")
    batch_date = _required_text(payload["batch_date"], "batch.batch_date", maximum=32)
    try:
        date.fromisoformat(batch_date)
    except ValueError as exc:
        raise LiteratureCatalogError("invalid batch.batch_date") from exc
    status = _required_text(payload["status"], "batch.status", maximum=32)
    if status not in _BATCH_STATUSES:
        raise LiteratureCatalogError("invalid batch.status")
    return {
        "id": batch_id,
        "field": _required_text(payload["field"], "batch.field", maximum=100_000),
        "field_slug": field_slug,
        "field_code": _required_text(
            payload["field_code"], "batch.field_code", maximum=512
        ),
        "batch_date": batch_date,
        "status": status,
        "created_at": _required_timestamp(payload["created_at"], "batch.created_at"),
        "published_at": _optional_timestamp(
            payload["published_at"], "batch.published_at"
        ),
    }


def _validate_member_payload(payload: dict[str, Any]) -> tuple[str, int]:
    _require_exact_keys(payload, _MEMBER_KEYS, "batch member")
    paper_id = _required_text(
        payload["paper_id"], "batch.members[].paper_id", maximum=MAX_ID_LENGTH
    )
    position = payload["position"]
    if type(position) is not int or position < 1 or position > 100_000:
        raise LiteratureCatalogError("invalid batch.members[].position")
    return paper_id, position


def _validate_sidecar_header(
    payload: dict[str, Any], *, kind: str, library_id: str
) -> bool:
    deleted = payload.get("deleted") is True
    expected = (
        {"version", "kind", "library_id", "deleted", "id"}
        if deleted
        else {"version", "kind", "library_id", kind}
    )
    if kind == "batch" and not deleted:
        expected.add("members")
    _require_exact_keys(payload, expected, f"{kind} sidecar")
    if payload["version"] != CATALOG_VERSION or payload["kind"] != kind:
        raise LiteratureCatalogError(f"unsupported {kind} sidecar version or kind")
    if _canonical_library_id(payload["library_id"]) != library_id:
        raise LiteratureCatalogConflictError("catalog library_id does not match sync library")
    return deleted


def _sidecar_identity(
    payload: dict[str, Any], *, kind: str, library_id: str
) -> tuple[str, bool]:
    deleted = _validate_sidecar_header(
        payload, kind=kind, library_id=library_id
    )
    container = payload if deleted else _require_object(payload[kind], kind)
    raw_id = container.get("id")
    return _required_text(raw_id, f"{kind}.id", maximum=MAX_ID_LENGTH), deleted


def _read_sidecar(path: Path) -> dict[str, Any]:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or attributes & _REPARSE_POINT
    ):
        raise LiteratureCatalogError(f"unsafe catalog sidecar: {path.name}")
    if path.stat().st_size > MAX_SIDECAR_BYTES:
        raise LiteratureCatalogError(f"catalog sidecar is too large: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiteratureCatalogError(f"invalid catalog JSON: {path.name}") from exc
    return _require_object(payload, "catalog sidecar")


def plan_catalog_reconcile(
    vault: LiteratureVault, *, library_id: str
) -> CatalogPlan:
    """Read and fully validate sidecars without creating or changing a database."""

    canonical_library_id = _canonical_library_id(library_id)
    root = vault.root
    paper_dir = _catalog_directory(root, "papers", create=False)
    batch_dir = _catalog_directory(root, "batches", create=False)
    paper_paths = sorted(paper_dir.glob("*.json")) if paper_dir.is_dir() else []
    batch_paths = sorted(batch_dir.glob("*.json")) if batch_dir.is_dir() else []
    papers: dict[str, dict[str, Any]] = {}
    deleted_paper_ids: set[str] = set()
    for path in paper_paths:
        sidecar = _read_sidecar(path)
        paper_id, deleted = _sidecar_identity(
            sidecar, kind="paper", library_id=canonical_library_id
        )
        if path.name != _catalog_filename(paper_id):
            raise LiteratureCatalogError("paper sidecar filename does not match its id")
        if deleted:
            deleted_paper_ids.add(paper_id)
            continue
        paper = _validate_paper_payload(root, _require_object(sidecar["paper"], "paper"))
        if paper["id"] in papers:
            raise LiteratureCatalogConflictError(f"duplicate paper sidecar: {paper['id']}")
        papers[paper["id"]] = paper

    batches: dict[str, dict[str, Any]] = {}
    deleted_batch_ids: set[str] = set()
    memberships: list[tuple[str, str, int]] = []
    for path in batch_paths:
        sidecar = _read_sidecar(path)
        batch_id, deleted = _sidecar_identity(
            sidecar, kind="batch", library_id=canonical_library_id
        )
        if path.name != _catalog_filename(batch_id):
            raise LiteratureCatalogError("batch sidecar filename does not match its id")
        if deleted:
            deleted_batch_ids.add(batch_id)
            continue
        batch = _validate_batch_payload(_require_object(sidecar["batch"], "batch"))
        if batch["id"] in batches:
            raise LiteratureCatalogConflictError(f"duplicate batch sidecar: {batch['id']}")
        raw_members = sidecar["members"]
        if not isinstance(raw_members, list) or len(raw_members) > 100_000:
            raise LiteratureCatalogError("batch.members must be a list")
        seen_papers: set[str] = set()
        seen_positions: set[int] = set()
        for raw_member in raw_members:
            paper_id, position = _validate_member_payload(
                _require_object(raw_member, "batch member")
            )
            if paper_id not in papers:
                raise LiteratureCatalogError(
                    f"batch {batch['id']} references missing paper sidecar {paper_id}"
                )
            if paper_id in seen_papers or position in seen_positions:
                raise LiteratureCatalogConflictError(
                    f"duplicate paper or position in batch {batch['id']}"
                )
            seen_papers.add(paper_id)
            seen_positions.add(position)
            memberships.append((batch["id"], paper_id, position))
        batches[batch["id"]] = batch

    return CatalogPlan(
        library_id=canonical_library_id,
        papers=tuple(papers[key] for key in sorted(papers)),
        batches=tuple(batches[key] for key in sorted(batches)),
        memberships=tuple(sorted(memberships)),
        deleted_paper_ids=tuple(sorted(deleted_paper_ids)),
        deleted_batch_ids=tuple(sorted(deleted_batch_ids)),
    )


def _open_existing_catalog(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _has_core_schema(conn: sqlite3.Connection) -> bool:
    names = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('papers','batches','batch_papers')"
        )
    }
    return names == {"papers", "batches", "batch_papers"}


def _paper_sidecar(row: sqlite3.Row, *, library_id: str) -> dict[str, Any]:
    try:
        authors = json.loads(row["authors_json"] or "[]")
    except json.JSONDecodeError as exc:
        raise LiteratureCatalogError(f"invalid authors_json for paper {row['id']}") from exc
    return {
        "version": CATALOG_VERSION,
        "kind": "paper",
        "library_id": library_id,
        "paper": {
            "id": row["id"],
            "title": row["title"],
            "authors": authors,
            "abstract": row["abstract"],
            "year": row["year"],
            "venue": row["venue"],
            "doi": row["doi"],
            "arxiv_id": row["arxiv_id"],
            "semantic_scholar_id": row["semantic_scholar_id"],
            "source_url": _export_url(row["source_url"]),
            "pdf_url": _export_url(row["pdf_url"]),
            "citation_count": row["citation_count"],
            "area": row["area"],
            "age_category": row["age_category"],
            "recommendation": row["recommendation"],
            "status": row["status"],
            "read_date": row["read_date"],
            "pdf_sha256": row["pdf_sha256"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "roles": {
                "original": row["original_pdf_relpath"],
                "bilingual": row["bilingual_pdf_relpath"],
                "note": row["note_relpath"],
            },
        },
    }


def _batch_sidecar(
    row: sqlite3.Row,
    members: list[dict[str, Any]],
    *,
    library_id: str,
) -> dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "kind": "batch",
        "library_id": library_id,
        "batch": {
            "id": row["id"],
            "field": row["field"],
            "field_slug": row["field_slug"],
            "field_code": row["field_code"],
            "batch_date": row["batch_date"],
            "status": row["status"],
            "created_at": row["created_at"],
            "published_at": row["published_at"],
        },
        "members": members,
    }


def _deletion_sidecar(kind: str, identifier: str, *, library_id: str) -> dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "kind": kind,
        "library_id": library_id,
        "deleted": True,
        "id": identifier,
    }


def export_catalog_sidecars(
    vault: LiteratureVault, *, library_id: str, authoritative: bool = False
) -> dict[str, Any]:
    """Export canonical catalog rows and optional creator deletion markers.

    A missing database is always a strict no-op.  An empty database is also a
    no-op by default, which protects a new receiving device before remote files
    arrive.  Only the persisted creator role may set ``authoritative``; a
    complete but empty creator database then emits tombstones for previously
    exported rows.
    """

    canonical_library_id = _canonical_library_id(library_id)
    if not vault.db_path.is_file():
        return {
            "exported": False,
            "skipped": "db_missing",
            "papers": 0,
            "batches": 0,
            "files_written": 0,
        }
    with closing(_open_existing_catalog(vault.db_path)) as conn:
        if not _has_core_schema(conn):
            return {
                "exported": False,
                "skipped": "db_uninitialized",
                "papers": 0,
                "batches": 0,
                "files_written": 0,
            }
        paper_rows = conn.execute("SELECT * FROM papers ORDER BY id").fetchall()
        batch_rows = conn.execute("SELECT * FROM batches ORDER BY id").fetchall()
        if not paper_rows and not batch_rows and not authoritative:
            return {
                "exported": False,
                "skipped": "db_empty",
                "papers": 0,
                "batches": 0,
                "files_written": 0,
            }
        if not authoritative and (not paper_rows or not batch_rows):
            raise LiteratureCatalogError("incomplete local Literature catalog")
        member_rows = conn.execute(
            "SELECT batch_id,paper_id,position FROM batch_papers "
            "ORDER BY batch_id,position,paper_id"
        ).fetchall()

    paper_payloads: list[tuple[str, dict[str, Any]]] = []
    paper_ids = {str(row["id"]) for row in paper_rows}
    for row in paper_rows:
        payload = _paper_sidecar(row, library_id=canonical_library_id)
        paper = _validate_paper_payload(
            vault.root, _require_object(payload["paper"], "paper")
        )
        paper_payloads.append((paper["id"], payload))

    members_by_batch: dict[str, list[dict[str, Any]]] = {
        str(row["id"]): [] for row in batch_rows
    }
    seen_memberships: set[tuple[str, str]] = set()
    seen_positions: set[tuple[str, int]] = set()
    for row in member_rows:
        batch_id = str(row["batch_id"])
        paper_id = str(row["paper_id"])
        position = int(row["position"])
        if batch_id not in members_by_batch or paper_id not in paper_ids:
            raise LiteratureCatalogError("local batch_papers contains an orphan reference")
        if (batch_id, paper_id) in seen_memberships or (batch_id, position) in seen_positions:
            raise LiteratureCatalogConflictError(
                "local batch_papers contains duplicate membership"
            )
        seen_memberships.add((batch_id, paper_id))
        seen_positions.add((batch_id, position))
        member = {"paper_id": paper_id, "position": position}
        _validate_member_payload(member)
        members_by_batch[batch_id].append(member)

    batch_payloads: list[tuple[str, dict[str, Any]]] = []
    for row in batch_rows:
        batch_id = str(row["id"])
        payload = _batch_sidecar(
            row,
            members_by_batch[batch_id],
            library_id=canonical_library_id,
        )
        _validate_batch_payload(_require_object(payload["batch"], "batch"))
        batch_payloads.append((batch_id, payload))

    written = 0
    paper_dir = _catalog_directory(vault.root, "papers", create=True)
    batch_dir = _catalog_directory(vault.root, "batches", create=True)
    for paper_id, payload in paper_payloads:
        written += int(
            _atomic_write_text(
                paper_dir / _catalog_filename(paper_id),
                _canonical_json(payload),
            )
        )
    for batch_id, payload in batch_payloads:
        written += int(
            _atomic_write_text(
                batch_dir / _catalog_filename(batch_id),
                _canonical_json(payload),
            )
        )
    tombstones_written = 0
    if authoritative:
        expected = {
            "paper": {_catalog_filename(identifier) for identifier, _ in paper_payloads},
            "batch": {_catalog_filename(identifier) for identifier, _ in batch_payloads},
        }
        for kind, directory in (("paper", paper_dir), ("batch", batch_dir)):
            for path in sorted(directory.glob("*.json")):
                if path.name in expected[kind]:
                    continue
                payload = _read_sidecar(path)
                identifier, _deleted = _sidecar_identity(
                    payload, kind=kind, library_id=canonical_library_id
                )
                if path.name != _catalog_filename(identifier):
                    raise LiteratureCatalogError(
                        f"{kind} sidecar filename does not match its id"
                    )
                changed = _atomic_write_text(
                    path,
                    _canonical_json(
                        _deletion_sidecar(
                            kind, identifier, library_id=canonical_library_id
                        )
                    ),
                )
                tombstones_written += int(changed)
                written += int(changed)
    return {
        "exported": True,
        "skipped": None,
        "papers": len(paper_payloads),
        "batches": len(batch_payloads),
        "memberships": len(member_rows),
        "files_written": written,
        "tombstones_written": tombstones_written,
    }


def _is_empty(name: str, value: object) -> bool:
    if value is None or value == "":
        return True
    return name == "authors_json" and value == "[]"


def _warn_on_preserved(
    warnings: list[str], *, kind: str, identifier: str, field: str, local: object, remote: object
) -> None:
    if not _is_empty(field, remote) and local != remote:
        warnings.append(f"preserved local {kind} {identifier} field {field}")


def _paper_values(paper: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_title(paper["title"])
    roles = paper["roles"]
    return {
        "title": paper["title"],
        "title_normalized": normalized,
        "title_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "authors_json": json.dumps(paper["authors"], ensure_ascii=False),
        "abstract": paper["abstract"],
        "year": paper["year"],
        "venue": paper["venue"],
        "doi": paper["doi"],
        "arxiv_id": paper["arxiv_id"],
        "semantic_scholar_id": paper["semantic_scholar_id"],
        "source_url": paper["source_url"],
        "pdf_url": paper["pdf_url"],
        "citation_count": paper["citation_count"],
        "area": paper["area"],
        "age_category": paper["age_category"],
        "recommendation": paper["recommendation"],
        "status": paper["status"],
        "read_date": paper["read_date"],
        "original_pdf_relpath": roles["original"],
        "bilingual_pdf_relpath": roles["bilingual"],
        "note_relpath": roles["note"],
        "pdf_sha256": paper["pdf_sha256"],
        "created_at": paper["created_at"],
        "updated_at": paper["updated_at"],
    }


def _natural_paper_conflict(
    conn: sqlite3.Connection, paper_id: str, values: dict[str, Any]
) -> None:
    for field in ("doi", "arxiv_id", "semantic_scholar_id", "title_hash"):
        value = values[field]
        if value is None:
            continue
        row = conn.execute(f"SELECT id FROM papers WHERE {field}=?", (value,)).fetchone()
        if row is not None and str(row["id"]) != paper_id:
            raise LiteratureCatalogConflictError(
                f"paper {paper_id} conflicts with {row['id']} by {field}"
            )


def _insert_or_fill_paper(
    conn: sqlite3.Connection,
    paper: dict[str, Any],
    warnings: list[str],
) -> tuple[bool, int]:
    paper_id = paper["id"]
    values = _paper_values(paper)
    row = conn.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
    _natural_paper_conflict(conn, paper_id, values)
    if row is None:
        columns = ["id", *values]
        conn.execute(
            f"INSERT INTO papers({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            (paper_id, *values.values()),
        )
        return True, 0

    for field in ("doi", "arxiv_id", "semantic_scholar_id"):
        if (
            not _is_empty(field, row[field])
            and not _is_empty(field, values[field])
            and row[field] != values[field]
        ):
            raise LiteratureCatalogConflictError(
                f"paper {paper_id} has conflicting {field}"
            )
    updates: dict[str, Any] = {}
    immutable_computed = {"title_normalized", "title_hash"}
    for field, incoming in values.items():
        local = row[field]
        if field in immutable_computed:
            continue
        if _is_empty(field, local) and not _is_empty(field, incoming):
            if field in {"doi", "arxiv_id", "semantic_scholar_id"}:
                _natural_paper_conflict(conn, paper_id, {**values, field: incoming})
            updates[field] = incoming
        elif not _is_empty(field, local):
            _warn_on_preserved(
                warnings,
                kind="paper",
                identifier=paper_id,
                field=field,
                local=local,
                remote=incoming,
            )
    if updates:
        conn.execute(
            f"UPDATE papers SET {','.join(field + '=?' for field in updates)} WHERE id=?",
            (*updates.values(), paper_id),
        )
    return False, len(updates)


def _insert_or_fill_batch(
    conn: sqlite3.Connection,
    batch: dict[str, Any],
    warnings: list[str],
) -> tuple[bool, int]:
    batch_id = batch["id"]
    collision = conn.execute(
        "SELECT id FROM batches WHERE field_slug=? AND batch_date=?",
        (batch["field_slug"], batch["batch_date"]),
    ).fetchone()
    if collision is not None and str(collision["id"]) != batch_id:
        raise LiteratureCatalogConflictError(
            f"batch {batch_id} conflicts with {collision['id']} by field/date"
        )
    row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO batches(
            id,field,field_slug,field_code,batch_date,status,error,created_at,published_at)
            VALUES(?,?,?,?,?,?,NULL,?,?)""",
            (
                batch_id,
                batch["field"],
                batch["field_slug"],
                batch["field_code"],
                batch["batch_date"],
                batch["status"],
                batch["created_at"],
                batch["published_at"],
            ),
        )
        return True, 0
    if row["field_slug"] != batch["field_slug"] or row["batch_date"] != batch["batch_date"]:
        raise LiteratureCatalogConflictError(f"batch {batch_id} has conflicting identity")
    updates: dict[str, Any] = {}
    for field in ("field", "field_code", "status", "created_at", "published_at"):
        incoming = batch[field]
        local = row[field]
        if _is_empty(field, local) and not _is_empty(field, incoming):
            updates[field] = incoming
        elif not _is_empty(field, local):
            _warn_on_preserved(
                warnings,
                kind="batch",
                identifier=batch_id,
                field=field,
                local=local,
                remote=incoming,
            )
    if updates:
        conn.execute(
            f"UPDATE batches SET {','.join(field + '=?' for field in updates)} WHERE id=?",
            (*updates.values(), batch_id),
        )
    return False, len(updates)


def _insert_membership(
    conn: sqlite3.Connection, batch_id: str, paper_id: str, position: int
) -> bool:
    row = conn.execute(
        "SELECT position FROM batch_papers WHERE batch_id=? AND paper_id=?",
        (batch_id, paper_id),
    ).fetchone()
    if row is not None:
        if int(row["position"]) != position:
            raise LiteratureCatalogConflictError(
                f"membership {batch_id}/{paper_id} has conflicting position"
            )
        return False
    occupied = conn.execute(
        "SELECT paper_id FROM batch_papers WHERE batch_id=? AND position=?",
        (batch_id, position),
    ).fetchone()
    if occupied is not None:
        raise LiteratureCatalogConflictError(
            f"batch {batch_id} position {position} is already occupied"
        )
    conn.execute(
        "INSERT INTO batch_papers(batch_id,paper_id,position) VALUES(?,?,?)",
        (batch_id, paper_id, position),
    )
    return True


def reconcile_catalog_sidecars(
    vault: LiteratureVault,
    *,
    library_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fill missing local catalog state from validated sidecars.

    Existing non-empty values and memberships are never overwritten. Explicit
    creator tombstones delete matching rows. A structural conflict raises
    ``LiteratureCatalogConflictError`` and rolls the whole transaction back.
    """

    plan = plan_catalog_reconcile(vault, library_id=library_id)
    if not (
        plan.papers
        or plan.batches
        or plan.deleted_paper_ids
        or plan.deleted_batch_ids
    ):
        return {
            "reconciled": False,
            "dry_run": dry_run,
            "skipped": "catalog_missing",
            "papers_inserted": 0,
            "batches_inserted": 0,
            "memberships_inserted": 0,
            "fields_filled": 0,
            "papers_deleted": 0,
            "batches_deleted": 0,
            "warnings": [],
        }

    vault.initialize()
    warnings: list[str] = []
    papers_inserted = batches_inserted = memberships_inserted = fields_filled = 0
    papers_deleted = batches_deleted = 0
    with closing(vault.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for batch_id in plan.deleted_batch_ids:
                batches_deleted += conn.execute(
                    "DELETE FROM batches WHERE id=?", (batch_id,)
                ).rowcount
            for paper_id in plan.deleted_paper_ids:
                papers_deleted += conn.execute(
                    "DELETE FROM papers WHERE id=?", (paper_id,)
                ).rowcount
            for paper in plan.papers:
                inserted, filled = _insert_or_fill_paper(conn, paper, warnings)
                papers_inserted += int(inserted)
                fields_filled += filled
            for batch in plan.batches:
                inserted, filled = _insert_or_fill_batch(conn, batch, warnings)
                batches_inserted += int(inserted)
                fields_filled += filled
            for batch_id, paper_id, position in plan.memberships:
                memberships_inserted += int(
                    _insert_membership(conn, batch_id, paper_id, position)
                )
            foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise LiteratureCatalogConflictError(
                    "catalog reconciliation failed foreign key check"
                )
            if dry_run:
                conn.rollback()
            else:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "reconciled": not dry_run,
        "dry_run": dry_run,
        "skipped": None,
        "papers_inserted": papers_inserted,
        "batches_inserted": batches_inserted,
        "memberships_inserted": memberships_inserted,
        "fields_filled": fields_filled,
        "papers_deleted": papers_deleted,
        "batches_deleted": batches_deleted,
        "warnings": sorted(set(warnings)),
    }
