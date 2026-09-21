"""Vault-backed Literature reading batches."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unicodedata
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

import httpx
import yaml

from on1y.papers.settings_store import resolve_literature_vault

logger = logging.getLogger(__name__)
_feedback_stop = threading.Event()
_feedback_thread: threading.Thread | None = None
DEFAULT_DAILY_TARGET = 20
READING_STATUSES = {"to_read", "reading", "read", "dismissed"}

DEFAULT_PAPER_NOTE_TEMPLATE = (
    "---\npaper_id: {{paper_id}}\ntitle: {{title}}\nauthors: {{authors}}\n"
    "year: {{year}}\nvenue: {{venue}}\ndoi: {{doi}}\nstatus: unread\n---\n"
    "# {{title}}\n\n{{pdf_link}}\n\n"
)
_LEGACY_NOTE_HEADINGS = re.compile(
    r"(?m)^## (?:My Summary|Important Points|Problems / Criticism|Questions|Ideas|Connections)"
    r"[ \t]*(?:\r?\n|$)"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
 id TEXT PRIMARY KEY, field TEXT NOT NULL, field_slug TEXT NOT NULL,
 field_code TEXT NOT NULL, batch_date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','publishing','published','error')),
 error TEXT, created_at TEXT NOT NULL, published_at TEXT,
 UNIQUE(field_slug,batch_date));
CREATE TABLE IF NOT EXISTS papers (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, title_normalized TEXT NOT NULL,
 title_hash TEXT NOT NULL, authors_json TEXT NOT NULL DEFAULT '[]',
 abstract TEXT, year INTEGER, venue TEXT, doi TEXT, arxiv_id TEXT,
 semantic_scholar_id TEXT, source_url TEXT, pdf_url TEXT, citation_count INTEGER,
 area TEXT, age_category TEXT, recommendation TEXT,
 status TEXT NOT NULL DEFAULT 'to_read', read_date TEXT,
 original_pdf_relpath TEXT, bilingual_pdf_relpath TEXT, note_relpath TEXT,
 pdf_sha256 TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS lit_doi ON papers(doi) WHERE doi IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS lit_arxiv ON papers(arxiv_id) WHERE arxiv_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS lit_s2 ON papers(semantic_scholar_id)
 WHERE semantic_scholar_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS lit_title ON papers(title_hash);
CREATE TABLE IF NOT EXISTS batch_papers (
 batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
 paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, PRIMARY KEY(batch_id,paper_id), UNIQUE(batch_id,position));
CREATE TABLE IF NOT EXISTS download_attempts (
 id INTEGER PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 url TEXT, status TEXT NOT NULL, detail TEXT, attempted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS note_scan_state (
 note_relpath TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
 sha256 TEXT NOT NULL, scanned_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback_snapshots (
 batch_id TEXT PRIMARY KEY REFERENCES batches(id) ON DELETE CASCADE,
 content_sha256 TEXT NOT NULL, generated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS translation_jobs (
 id TEXT PRIMARY KEY,
 batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
 paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
 provider TEXT NOT NULL, model TEXT, source_lang TEXT NOT NULL, target_lang TEXT NOT NULL,
 input_relpath TEXT NOT NULL, output_relpath TEXT,
 attempt INTEGER NOT NULL DEFAULT 0, progress REAL NOT NULL DEFAULT 0, stage TEXT,
 error TEXT, input_tokens INTEGER NOT NULL DEFAULT 0,
 output_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
 character_count INTEGER NOT NULL DEFAULT 0, log_tail TEXT,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS lit_translation_batch ON translation_jobs(batch_id,created_at);
CREATE INDEX IF NOT EXISTS lit_translation_status ON translation_jobs(status,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS lit_translation_active ON translation_jobs(paper_id)
 WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS paper_rollovers (
 id TEXT PRIMARY KEY,
 paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
 from_batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
 to_batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
 from_position INTEGER NOT NULL, to_position INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('planned','committed','failed')),
 old_paths_json TEXT NOT NULL DEFAULT '{}', new_paths_json TEXT NOT NULL DEFAULT '{}',
 error TEXT, created_at TEXT NOT NULL, committed_at TEXT,
 UNIQUE(to_batch_id,paper_id));
CREATE INDEX IF NOT EXISTS lit_rollover_from ON paper_rollovers(from_batch_id,status);
CREATE INDEX IF NOT EXISTS lit_rollover_to ON paper_rollovers(to_batch_id,status);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_write_text(path: Path, body: str) -> None:
    """Replace a UTF-8 text file without exposing a partially-written version."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(body, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def normalize_doi(value: object) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    text = re.sub(r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", "", text)
    text = text.split("?", 1)[0].split("#", 1)[0].rstrip(" .;,")
    return text or None


def normalize_arxiv(value: object) -> str | None:
    text = str(value or "").strip()
    text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text, flags=re.I)
    text = re.sub(r"^arxiv\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\.pdf$", "", text, flags=re.I)
    return re.sub(r"v\d+$", "", text, flags=re.I).casefold() or None


def normalize_title(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return "".join(char for char in re.sub(r"\.pdf$", "", text) if char.isalnum())


def slugify(value: str, fallback: str = "Literature") -> str:
    return re.sub(r"[^\w-]+", "-", unicodedata.normalize("NFKC", value)).strip("-_") or fallback


def safe_stem(value: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return (text[:120] or "paper").replace(" ", "_")


def remove_legacy_note_headings(body: str) -> str:
    """Remove the old writing prompts without touching the user's prose."""

    cleaned, removed = _LEGACY_NOTE_HEADINGS.subn("", body)
    if not removed:
        return body
    cleaned = cleaned.replace("\r\n", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.rstrip() + "\n"


def freeform_note_body(body: str) -> str:
    """Return only what the reader wrote in a free-form paper note."""

    cleaned = re.sub(r"\A---\r?\n.*?^---[ \t]*\r?\n?", "", body, count=1, flags=re.M | re.S)
    cleaned = re.sub(
        r"(?s)<!-- on1y:pdf-links:start -->.*?<!-- on1y:pdf-links:end -->",
        "",
        cleaned,
        count=1,
    )
    cleaned = re.sub(r"(?m)^# [^\r\n]*(?:\r?\n|$)", "", cleaned, count=1)
    cleaned = remove_legacy_note_headings(cleaned)
    return cleaned.strip()


def parse_paper(raw: dict[str, Any]) -> dict[str, Any]:
    title = str(raw.get("title") or "").strip()
    doi = normalize_doi(raw.get("doi"))
    arxiv = normalize_arxiv(raw.get("arxiv_id"))
    s2 = str(raw.get("semantic_scholar_id") or "").strip().casefold() or None
    if not title and not any((doi, arxiv, s2)):
        raise ValueError("title or a stable identifier is required")
    title = title or doi or arxiv or s2 or "Untitled"
    authors = raw.get("authors") or []
    if isinstance(authors, str):
        authors = [part.strip() for part in re.split(r"[;；]", authors) if part.strip()]
    authors = [
        str(row.get("name") if isinstance(row, dict) else row).strip()
        for row in authors
        if str(row.get("name") if isinstance(row, dict) else row).strip()
    ]
    normalized = normalize_title(title)
    return {
        "id": str(raw.get("id") or uuid4()),
        "title": title,
        "title_normalized": normalized,
        "title_hash": hashlib.sha256(normalized.encode()).hexdigest(),
        "authors": authors,
        "abstract": str(raw.get("abstract") or "").strip() or None,
        "year": int(raw["year"]) if raw.get("year") not in (None, "") else None,
        "venue": str(raw.get("venue") or "").strip() or None,
        "doi": doi,
        "arxiv_id": arxiv,
        "semantic_scholar_id": s2,
        "source_url": str(raw.get("source_url") or raw.get("url") or "").strip() or None,
        "pdf_url": str(raw.get("pdf_url") or "").strip() or None,
        "local_pdf_path": str(raw.get("local_pdf_path") or "").strip() or None,
        "citation_count": int(raw["citation_count"])
        if raw.get("citation_count") not in (None, "")
        else None,
        "area": str(raw.get("area") or "").strip() or None,
        "age_category": str(raw.get("age_category") or "").strip() or None,
        "recommendation": str(raw.get("recommendation") or "").strip(),
    }


class LiteratureVault:
    def __init__(self, user_id: int, path: Path | None = None) -> None:
        self.user_id = user_id
        self.root = (path or resolve_literature_vault(user_id)).resolve(strict=False)
        self.db_path = self.root / "_system" / "papers.db"

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def initialize(self) -> dict[str, Any]:
        if self.root.drive and not Path(self.root.anchor).exists():
            raise OSError(f"drive unavailable: {self.root.anchor}")
        (self.root / "_system" / "cache" / "figures").mkdir(parents=True, exist_ok=True)
        (self.root / "_templates").mkdir(parents=True, exist_ok=True)
        template = self.root / "_templates" / "paper-note.md"
        if not template.exists():
            template.write_text(DEFAULT_PAPER_NOTE_TEMPLATE, encoding="utf-8")
        else:
            previous_template = template.read_text("utf-8")
            freeform_template = remove_legacy_note_headings(previous_template)
            if freeform_template != previous_template:
                template.write_text(freeform_template, encoding="utf-8")
        config = self.root / "_system" / "config.yaml"
        if not config.exists():
            config.write_text(
                yaml.safe_dump(
                    {
                        "version": 1,
                        "daily_target": DEFAULT_DAILY_TARGET,
                        "source": "local-vault",
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()
        return {"path": str(self.root), "db_path": str(self.db_path), "initialized": True}

    def config(self) -> dict[str, Any]:
        """Read the Vault-owned Literature configuration."""

        self.initialize()
        path = self.root / "_system" / "config.yaml"
        try:
            payload = yaml.safe_load(path.read_text("utf-8")) or {}
        except Exception:
            payload = {}
        try:
            daily_target = int(payload.get("daily_target", DEFAULT_DAILY_TARGET))
        except (TypeError, ValueError):
            daily_target = DEFAULT_DAILY_TARGET
        return {
            "version": 1,
            "daily_target": max(1, min(100, daily_target)),
            "source": "local-vault",
        }

    def update_config(self, *, daily_target: int) -> dict[str, Any]:
        """Persist the daily target inside the Vault, its canonical location."""

        self.initialize()
        target = int(daily_target)
        if not 1 <= target <= 100:
            raise ValueError("daily_target must be between 1 and 100")
        payload = {"version": 1, "daily_target": target, "source": "local-vault"}
        _atomic_write_text(
            self.root / "_system" / "config.yaml",
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        )
        self.write_reading_state()
        return payload

    def validate(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        self.initialize()
        accepted, duplicates, errors = [], [], []
        seen: set[tuple[str, str]] = set()
        with closing(self.connect()) as conn:
            for index, raw in enumerate(records):
                try:
                    paper = parse_paper(raw)
                except Exception as exc:
                    errors.append({"index": index, "detail": str(exc), "record": raw})
                    continue
                keys = [
                    (key, paper[key])
                    for key in ("doi", "arxiv_id", "semantic_scholar_id", "title_hash")
                ]
                duplicate = None
                for field, value in keys:
                    if not value:
                        continue
                    if (field, value) in seen:
                        duplicate = {"index": index, "matched_by": field}
                        break
                    row = conn.execute(
                        f"SELECT id,title FROM papers WHERE {field}=?", (value,)
                    ).fetchone()
                    if row:
                        duplicate = {
                            "index": index,
                            "matched_by": field,
                            "paper_id": row["id"],
                            "title": row["title"],
                        }
                        break
                if duplicate:
                    duplicates.append(duplicate)
                    continue
                seen.update((field, value) for field, value in keys if value)
                accepted.append(paper)
        return {"accepted": accepted, "duplicates": duplicates, "errors": errors}

    def daily_plan(self, *, target_date: str, field: str) -> dict[str, Any]:
        """Return the unread carryover queue and remaining slots for one reading day."""

        date.fromisoformat(target_date)
        requested_field = field.strip()
        requested_slug = slugify(requested_field) if requested_field else ""
        target = int(self.config()["daily_target"])
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """WITH ranked AS (
                    SELECT p.*,bp.position AS from_position,b.id AS from_batch_id,
                    b.field AS from_field,b.field_slug AS from_field_slug,
                    b.field_code AS from_field_code,b.batch_date AS from_date,
                    ROW_NUMBER() OVER (
                      PARTITION BY p.id ORDER BY b.batch_date DESC,b.created_at DESC
                    ) AS rank
                    FROM papers p
                    JOIN batch_papers bp ON bp.paper_id=p.id
                    JOIN batches b ON b.id=bp.batch_id
                    WHERE b.status='published' AND b.batch_date < ?
                      AND p.status NOT IN ('read','dismissed')
                )
                SELECT * FROM ranked WHERE rank=1
                ORDER BY from_date,from_position,title""",
                (target_date,),
            ).fetchall()
        pending = [
            {
                **dict(row),
                "authors": json.loads(row["authors_json"] or "[]"),
            }
            for row in rows
        ]
        blocking_fields = sorted(
            {
                str(row["from_field"])
                for row in pending
                if requested_slug and str(row["from_field_slug"]) != requested_slug
            }
        )
        selected = pending[:target]
        return {
            "target_date": target_date,
            "field": requested_field,
            "daily_target": target,
            "carryover": selected,
            "carryover_count": len(selected),
            "new_slots": max(0, target - len(selected)),
            "backlog_remaining": max(0, len(pending) - len(selected)),
            "blocking_fields": blocking_fields,
            "can_change_field": not blocking_fields,
        }

    @staticmethod
    def _note_status_body(body: str, status: str) -> str:
        note_status = "unread" if status == "to_read" else status
        pattern = r"(?m)^status:\s*[^\s]+[ \t]*$"
        if re.search(pattern, body):
            return re.sub(pattern, f"status: {note_status}", body, count=1)
        if body.startswith("---\n"):
            return body.replace("---\n", f"---\nstatus: {note_status}\n", 1)
        return body

    def set_paper_statuses(self, paper_ids: list[str], status: str) -> dict[str, Any]:
        """Update canonical reading state and its Markdown frontmatter together."""

        if status not in READING_STATUSES:
            raise ValueError("invalid paper status")
        unique_ids = list(dict.fromkeys(str(value).strip() for value in paper_ids if str(value).strip()))
        if not unique_ids:
            return {"updated": 0, "paper_ids": [], "status": status, "affected_batches": []}
        if len(unique_ids) > 500:
            raise ValueError("at most 500 papers can be updated at once")
        self.initialize()
        placeholders = ",".join("?" for _value in unique_ids)
        with closing(self.connect()) as conn:
            papers = conn.execute(
                f"SELECT id,note_relpath,status FROM papers WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()
            found_ids = [str(row["id"]) for row in papers]
            if len(found_ids) != len(unique_ids):
                missing = sorted(set(unique_ids) - set(found_ids))
                raise LookupError("paper not found: " + ", ".join(missing))
            batch_rows = conn.execute(
                f"""SELECT DISTINCT bp.batch_id FROM batch_papers bp
                WHERE bp.paper_id IN ({placeholders})""",
                unique_ids,
            ).fetchall()

        note_backups: dict[Path, str] = {}
        try:
            for row in papers:
                relpath = row["note_relpath"]
                if not relpath:
                    continue
                note = self.root / str(relpath)
                if not note.is_file():
                    continue
                before = note.read_text("utf-8")
                after = self._note_status_body(before, status)
                if after != before:
                    note_backups[note] = before
                    _atomic_write_text(note, after)
            with closing(self.connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    f"""UPDATE papers SET status=?,read_date=?,updated_at=?
                    WHERE id IN ({placeholders})""",
                    (
                        status,
                        date.today().isoformat() if status == "read" else None,
                        utc_now(),
                        *unique_ids,
                    ),
                )
                conn.commit()
        except Exception:
            for note, body in note_backups.items():
                _atomic_write_text(note, body)
            raise

        affected = [str(row["batch_id"]) for row in batch_rows]
        for batch_id in affected:
            current = self.batch(batch_id)
            if current and current["status"] == "published":
                self.rebuild_feedback(batch_id)
        self.write_reading_state()
        return {
            "updated": len(unique_ids),
            "paper_ids": unique_ids,
            "status": status,
            "affected_batches": affected,
        }

    def create_batch(
        self, *, field: str, field_code: str, batch_date: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not field.strip() or not field_code.strip():
            raise ValueError("field and field_code are required")
        date.fromisoformat(batch_date)
        plan = self.daily_plan(target_date=batch_date, field=field)
        if plan["blocking_fields"]:
            blocked = ", ".join(plan["blocking_fields"])
            raise ValueError(f"请先读完或移出 {blocked} 的未读论文，再切换研究领域")
        checked = self.validate(records)
        carryover = list(plan["carryover"])
        total = len(carryover) + len(checked["accepted"])
        if total > int(plan["daily_target"]):
            checked["errors"].append(
                {
                    "detail": (
                        f"daily target is {plan['daily_target']}: "
                        f"{len(carryover)} carryover + {len(checked['accepted'])} new papers"
                    )
                }
            )
        if not total:
            checked["errors"].append({"detail": "no papers remain after deduplication"})
        if checked["errors"]:
            return {**checked, "created": False, "plan": plan}
        batch_id, now, field_slug = str(uuid4()), utc_now(), slugify(field)
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "INSERT INTO batches VALUES(?,?,?,?,?,'draft',NULL,?,NULL)",
                    (
                        batch_id,
                        field.strip(),
                        field_slug,
                        field_code.strip().upper(),
                        batch_date,
                        now,
                    ),
                )
                for position, paper in enumerate(carryover, 1):
                    conn.execute(
                        "INSERT INTO batch_papers VALUES(?,?,?)",
                        (batch_id, paper["id"], position),
                    )
                    conn.execute(
                        """INSERT INTO paper_rollovers(
                        id,paper_id,from_batch_id,to_batch_id,from_position,to_position,
                        status,old_paths_json,new_paths_json,error,created_at,committed_at)
                        VALUES(?,?,?,?,?,?,'planned','{}','{}',NULL,?,NULL)""",
                        (
                            str(uuid4()),
                            paper["id"],
                            paper["from_batch_id"],
                            batch_id,
                            int(paper["from_position"]),
                            position,
                            now,
                        ),
                    )
                for position, paper in enumerate(checked["accepted"], len(carryover) + 1):
                    source_url = paper["source_url"]
                    if paper["local_pdf_path"]:
                        source_url = Path(paper["local_pdf_path"]).expanduser().resolve().as_uri()
                    conn.execute(
                        """INSERT INTO papers(id,title,title_normalized,title_hash,authors_json,
                        abstract,year,venue,doi,arxiv_id,semantic_scholar_id,source_url,pdf_url,
                        citation_count,area,age_category,recommendation,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            paper["id"],
                            paper["title"],
                            paper["title_normalized"],
                            paper["title_hash"],
                            json.dumps(paper["authors"], ensure_ascii=False),
                            paper["abstract"],
                            paper["year"],
                            paper["venue"],
                            paper["doi"],
                            paper["arxiv_id"],
                            paper["semantic_scholar_id"],
                            source_url,
                            paper["pdf_url"],
                            paper["citation_count"],
                            paper["area"],
                            paper["age_category"],
                            paper["recommendation"],
                            now,
                            now,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO batch_papers VALUES(?,?,?)", (batch_id, paper["id"], position)
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            **checked,
            "created": True,
            "batch_id": batch_id,
            "carryover_count": len(carryover),
            "new_count": len(checked["accepted"]),
            "daily_target": plan["daily_target"],
            "remaining_slots": int(plan["daily_target"]) - total,
            "plan": plan,
        }

    def list_batches(self) -> list[dict[str, Any]]:
        self.initialize()
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """SELECT b.*,COUNT(bp.paper_id) paper_count FROM batches b
                LEFT JOIN batch_papers bp ON bp.batch_id=b.id GROUP BY b.id
                ORDER BY b.batch_date DESC,b.created_at DESC"""
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["translation"] = self._translation_summary(conn, str(row["id"]))
                item["progress"] = self._batch_progress(conn, str(row["id"]))
                result.append(item)
        return result

    @staticmethod
    def _batch_progress(conn: sqlite3.Connection, batch_id: str) -> dict[str, int]:
        rows = conn.execute(
            """SELECT p.status,
            EXISTS(SELECT 1 FROM paper_rollovers r WHERE r.from_batch_id=bp.batch_id
              AND r.paper_id=bp.paper_id AND r.status='committed') AS carried
            FROM batch_papers bp JOIN papers p ON p.id=bp.paper_id
            WHERE bp.batch_id=?""",
            (batch_id,),
        ).fetchall()
        result = {"total": len(rows), "read": 0, "dismissed": 0, "pending": 0, "carried": 0}
        for row in rows:
            if int(row["carried"] or 0):
                result["carried"] += 1
            elif row["status"] == "read":
                result["read"] += 1
            elif row["status"] == "dismissed":
                result["dismissed"] += 1
            else:
                result["pending"] += 1
        return result

    def batch(self, batch_id: str) -> dict[str, Any] | None:
        self.initialize()
        with closing(self.connect()) as conn:
            batch = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                return None
            papers = conn.execute(
                """SELECT p.*,bp.position,
                inbound.from_batch_id AS carryover_from_batch_id,
                inbound.from_position AS carryover_from_position,
                source_batch.batch_date AS carryover_from_date,
                outbound.to_batch_id AS carried_to_batch_id,
                target_batch.batch_date AS carried_to_date
                FROM papers p JOIN batch_papers bp ON bp.paper_id=p.id
                LEFT JOIN paper_rollovers inbound ON inbound.to_batch_id=?
                  AND inbound.paper_id=p.id AND inbound.status IN ('planned','committed')
                LEFT JOIN batches source_batch ON source_batch.id=inbound.from_batch_id
                LEFT JOIN paper_rollovers outbound ON outbound.from_batch_id=?
                  AND outbound.paper_id=p.id AND outbound.status='committed'
                LEFT JOIN batches target_batch ON target_batch.id=outbound.to_batch_id
                WHERE bp.batch_id=? ORDER BY bp.position""",
                (batch_id, batch_id, batch_id),
            ).fetchall()
            jobs = self._translation_jobs(conn, batch_id)
            summary = self._translation_summary(conn, batch_id)
        result = dict(batch)
        result["papers"] = [
            {**dict(row), "authors": json.loads(row["authors_json"] or "[]")} for row in papers
        ]
        result["translation_jobs"] = jobs
        result["translation"] = summary
        with closing(self.connect()) as conn:
            result["progress"] = self._batch_progress(conn, batch_id)
        return result

    @staticmethod
    def _translation_jobs(conn: sqlite3.Connection, batch_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """SELECT tj.*,bp.position,p.title FROM translation_jobs tj
            JOIN batch_papers bp ON bp.batch_id=tj.batch_id AND bp.paper_id=tj.paper_id
            JOIN papers p ON p.id=tj.paper_id WHERE tj.batch_id=?
            ORDER BY tj.created_at DESC,tj.rowid DESC""",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _translation_summary(
        self,
        conn: sqlite3.Connection,
        batch_id: str,
    ) -> dict[str, Any]:
        total = int(
            conn.execute(
                "SELECT COUNT(*) FROM batch_papers WHERE batch_id=?", (batch_id,)
            ).fetchone()[0]
        )
        eligible = int(
            conn.execute(
                """SELECT COUNT(*) FROM batch_papers bp JOIN papers p ON p.id=bp.paper_id
                WHERE bp.batch_id=? AND p.original_pdf_relpath IS NOT NULL""",
                (batch_id,),
            ).fetchone()[0]
        )
        available = int(
            conn.execute(
                """SELECT COUNT(*) FROM batch_papers bp JOIN papers p ON p.id=bp.paper_id
                WHERE bp.batch_id=? AND p.bilingual_pdf_relpath IS NOT NULL""",
                (batch_id,),
            ).fetchone()[0]
        )
        rows = conn.execute(
            """SELECT tj.* FROM translation_jobs tj
            WHERE tj.batch_id=? ORDER BY tj.created_at,tj.rowid""",
            (batch_id,),
        ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[str(row["paper_id"])] = row
        counts = {name: 0 for name in ("queued", "running", "succeeded", "failed", "cancelled")}
        for row in latest.values():
            counts[str(row["status"])] += 1
        if counts["queued"] or counts["running"]:
            state = "translating"
        elif eligible and available == eligible and not counts["failed"]:
            state = "ready"
        elif counts["failed"]:
            state = "ready_with_warnings" if available else "failed"
        elif eligible:
            state = "pending"
        else:
            state = "unavailable"
        return {
            "state": state,
            "total": total,
            "eligible": eligible,
            "not_queued": max(eligible - len(latest), 0),
            **counts,
            "succeeded": available,
            "latest_succeeded": counts["succeeded"],
            "input_tokens": sum(int(row["input_tokens"] or 0) for row in rows),
            "output_tokens": sum(int(row["output_tokens"] or 0) for row in rows),
            "total_tokens": sum(int(row["total_tokens"] or 0) for row in rows),
            "character_count": sum(int(row["character_count"] or 0) for row in rows),
        }

    def translation_status(self, batch_id: str) -> dict[str, Any]:
        self.initialize()
        with closing(self.connect()) as conn:
            found = conn.execute("SELECT 1 FROM batches WHERE id=?", (batch_id,)).fetchone()
            if not found:
                raise LookupError("batch not found")
            return {
                "batch_id": batch_id,
                "summary": self._translation_summary(conn, batch_id),
                "jobs": self._translation_jobs(conn, batch_id),
            }

    def _translation_identity(self) -> tuple[str, str, str, str]:
        from on1y.llm.settings import resolve_llm_settings
        from on1y.papers.settings_store import load_paper_settings

        settings = load_paper_settings(self.user_id)
        provider = settings.translation_provider
        source = settings.translation_source_lang
        target = settings.translation_target_lang
        if provider == "deepl":
            if not str(settings.translation_api_key or "").strip():
                raise ValueError("请先在 Papers 设置中填写 DeepL API Key")
            model = "DeepL"
        else:
            llm = resolve_llm_settings(user_id=self.user_id)
            if not llm.api_key_set:
                raise ValueError("请先在设置 → AI 模型中填写 API Key")
            model = settings.translation_model_override or llm.model
        return provider, model, source, target

    def enqueue_translations(self, batch_id: str, *, force: bool = False) -> dict[str, Any]:
        current = self.batch(batch_id)
        if not current:
            raise LookupError("batch not found")
        if current["status"] != "published":
            raise ValueError("only a published batch can be translated")
        provider, model, source, target = self._translation_identity()
        now = utc_now()
        queued = skipped = 0
        pending_notes: list[str] = []
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for paper in current["papers"]:
                input_relpath = paper.get("original_pdf_relpath")
                if not input_relpath:
                    skipped += 1
                    continue
                latest = conn.execute(
                    """SELECT * FROM translation_jobs WHERE paper_id=?
                    ORDER BY created_at DESC,rowid DESC LIMIT 1""",
                    (paper["id"],),
                ).fetchone()
                if latest and latest["status"] in {"queued", "running"}:
                    skipped += 1
                    continue
                if latest and latest["status"] == "succeeded" and not force:
                    skipped += 1
                    continue
                if latest and latest["status"] in {"failed", "cancelled"} and not force:
                    conn.execute(
                        """UPDATE translation_jobs SET status='queued',provider=?,model=?,
                        source_lang=?,target_lang=?,progress=0,stage='queued',error=NULL,
                        started_at=NULL,finished_at=NULL,updated_at=? WHERE id=?""",
                        (provider, model, source, target, now, latest["id"]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO translation_jobs(
                        id,batch_id,paper_id,status,provider,model,source_lang,target_lang,
                        input_relpath,created_at,updated_at,stage)
                        VALUES(?,?,?,'queued',?,?,?,?,?,?,?,'queued')""",
                        (
                            str(uuid4()),
                            batch_id,
                            paper["id"],
                            provider,
                            model,
                            source,
                            target,
                            input_relpath,
                            now,
                            now,
                        ),
                    )
                queued += 1
                pending_notes.append(str(paper["id"]))
            conn.commit()
        for paper_id in pending_notes:
            self._update_note_pdf_links(paper_id)
        result = self.translation_status(batch_id)
        result.update({"queued_now": queued, "skipped": skipped})
        return result

    def retry_translation_job(self, job_id: str) -> dict[str, Any]:
        provider, model, source, target = self._translation_identity()
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM translation_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                conn.rollback()
                raise LookupError("translation job not found")
            if row["status"] not in {"failed", "cancelled"}:
                conn.rollback()
                raise ValueError("only failed or cancelled jobs can be retried")
            conn.execute(
                """UPDATE translation_jobs SET status='queued',provider=?,model=?,source_lang=?,
                target_lang=?,progress=0,stage='queued',error=NULL,started_at=NULL,
                finished_at=NULL,updated_at=? WHERE id=?""",
                (provider, model, source, target, now, job_id),
            )
            conn.commit()
            paper_id = str(row["paper_id"])
            batch_id = str(row["batch_id"])
        self._update_note_pdf_links(paper_id)
        return self.translation_status(batch_id)

    def claim_next_translation_job(self) -> dict[str, Any] | None:
        self.initialize()
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM translation_jobs WHERE status='queued'
                ORDER BY created_at,rowid LIMIT 1"""
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            changed = conn.execute(
                """UPDATE translation_jobs SET status='running',attempt=attempt+1,
                progress=1,stage='starting',started_at=?,finished_at=NULL,updated_at=?
                WHERE id=? AND status='queued'""",
                (now, now, row["id"]),
            ).rowcount
            if not changed:
                conn.rollback()
                return None
            conn.commit()
            claimed = conn.execute(
                "SELECT * FROM translation_jobs WHERE id=?", (row["id"],)
            ).fetchone()
        return dict(claimed) if claimed else None

    def update_translation_progress(self, job_id: str, progress: float, stage: str) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """UPDATE translation_jobs SET progress=?,stage=?,updated_at=?
                WHERE id=? AND status='running'""",
                (max(0.0, min(float(progress), 99.0)), stage[:200], utc_now(), job_id),
            )
            conn.commit()

    def complete_translation_job(
        self,
        job_id: str,
        output_path: Path,
        usage: dict[str, Any],
    ) -> None:
        output = output_path.resolve(strict=True)
        try:
            output_relpath = output.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise ValueError("translated PDF must stay inside the Literature Vault") from exc
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM translation_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                conn.rollback()
                raise LookupError("translation job not found")
            conn.execute(
                """UPDATE translation_jobs SET status='succeeded',output_relpath=?,progress=100,
                stage='completed',error=NULL,input_tokens=?,output_tokens=?,total_tokens=?,
                character_count=?,log_tail=?,finished_at=?,updated_at=? WHERE id=?""",
                (
                    output_relpath,
                    int(usage.get("input_tokens") or 0),
                    int(usage.get("output_tokens") or 0),
                    int(usage.get("total_tokens") or 0),
                    int(usage.get("character_count") or 0),
                    str(usage.get("log_tail") or "")[-8000:] or None,
                    now,
                    now,
                    job_id,
                ),
            )
            conn.execute(
                "UPDATE papers SET bilingual_pdf_relpath=?,updated_at=? WHERE id=?",
                (output_relpath, now, row["paper_id"]),
            )
            conn.commit()
            paper_id = str(row["paper_id"])
        self._update_note_pdf_links(paper_id, bilingual_relpath=output_relpath)

    def fail_translation_job(self, job_id: str, error: str) -> None:
        now = utc_now()
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM translation_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return
            conn.execute(
                """UPDATE translation_jobs SET status='failed',stage='failed',error=?,
                finished_at=?,updated_at=? WHERE id=?""",
                (error[-8000:], now, now, job_id),
            )
            conn.commit()
            paper_id = str(row["paper_id"])
        self._update_note_pdf_links(paper_id, error=error)

    def recover_stale_translation_jobs(self) -> int:
        self.initialize()
        with closing(self.connect()) as conn:
            changed = conn.execute(
                """UPDATE translation_jobs SET status='queued',progress=0,stage='recovered',
                error='On1y restarted while this translation was running',started_at=NULL,
                finished_at=NULL,updated_at=? WHERE status='running'""",
                (utc_now(),),
            ).rowcount
            conn.commit()
        return int(changed)

    def _update_note_pdf_links(
        self,
        paper_id: str,
        *,
        bilingual_relpath: str | None = None,
        error: str | None = None,
    ) -> None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """SELECT note_relpath,original_pdf_relpath,bilingual_pdf_relpath
                FROM papers WHERE id=?""",
                (paper_id,),
            ).fetchone()
        if not row or not row["note_relpath"]:
            return
        note = self.root / str(row["note_relpath"])
        if not note.is_file():
            return
        bilingual = bilingual_relpath or row["bilingual_pdf_relpath"]
        lines = ["<!-- on1y:pdf-links:start -->"]
        if bilingual:
            lines.append(f"[[../Bilingual/{Path(str(bilingual)).name}|Open bilingual PDF]]")
        elif error:
            short_error = " ".join(str(error).split())[:300]
            lines.append(f"**Bilingual translation failed:** {short_error}")
        else:
            lines.append("**Bilingual translation pending**")
        if row["original_pdf_relpath"]:
            lines.append(
                f"[[../Original/{Path(str(row['original_pdf_relpath'])).name}|Open original PDF]]"
            )
        lines.append("<!-- on1y:pdf-links:end -->")
        managed = "\n".join(lines)
        body = note.read_text("utf-8")
        pattern = r"(?s)<!-- on1y:pdf-links:start -->.*?<!-- on1y:pdf-links:end -->"
        if not re.search(pattern, body):
            return
        updated = re.sub(pattern, lambda _match: managed, body, count=1)
        if updated != body:
            note.write_text(updated, "utf-8")

    def _pdf_source(self, paper: dict[str, Any]) -> tuple[str, str] | None:
        source = str(paper.get("source_url") or "")
        if source.startswith("file:"):
            return "file", source
        if paper.get("pdf_url"):
            return "url", str(paper["pdf_url"])
        if paper.get("arxiv_id"):
            return "url", f"https://arxiv.org/pdf/{paper['arxiv_id']}"
        if "aclanthology.org/" in source:
            return "url", source.rstrip("/") + ("" if source.endswith(".pdf") else ".pdf")
        return None

    def _obtain_pdf(
        self, paper: dict[str, Any], destination: Path
    ) -> tuple[str | None, str | None]:
        candidate = self._pdf_source(paper)
        if not candidate:
            return None, "Full text unavailable automatically"
        kind, value = candidate
        temporary = destination.with_suffix(".downloading")
        try:
            if kind == "file":
                parsed = urlparse(value)
                raw_path = unquote(parsed.path)
                if parsed.netloc:
                    raw_path = f"//{parsed.netloc}{raw_path}"
                if re.match(r"^/[A-Za-z]:", raw_path):
                    raw_path = raw_path[1:]
                shutil.copy2(Path(raw_path), temporary)
            else:
                with httpx.stream("GET", value, follow_redirects=True, timeout=60) as response:
                    response.raise_for_status()
                    total = 0
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_bytes(1024 * 1024):
                            total += len(chunk)
                            if total > 500 * 1024 * 1024:
                                raise ValueError("PDF exceeds 500MB")
                            handle.write(chunk)
            if temporary.read_bytes()[:5] != b"%PDF-":
                raise ValueError("response is not a PDF")
            import pymupdf

            document = pymupdf.open(temporary)
            try:
                if document.page_count < 1:
                    raise ValueError("PDF has no pages")
            finally:
                document.close()
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            temporary.replace(destination)
            return digest, None
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            return None, str(exc)

    @staticmethod
    def _managed_pdf_links(original_name: str | None, bilingual_name: str | None) -> str:
        lines = ["<!-- on1y:pdf-links:start -->"]
        if bilingual_name:
            lines.append(f"[[../Bilingual/{bilingual_name}|Open bilingual PDF]]")
        elif original_name:
            lines.append("**Bilingual translation pending**")
        else:
            lines.append("**Full text unavailable automatically**")
        if original_name:
            lines.append(f"[[../Original/{original_name}|Open original PDF]]")
        lines.append("<!-- on1y:pdf-links:end -->")
        return "\n".join(lines)

    @staticmethod
    def _renamed_bilingual_file(
        old_original: str | None,
        old_bilingual: str | None,
        new_stem: str,
    ) -> str | None:
        if not old_bilingual:
            return None
        old_name = Path(old_bilingual).name
        if old_original:
            original_stem = Path(old_original).stem
            if old_name.startswith(original_stem):
                return new_stem + old_name[len(original_stem) :]
        suffix = re.search(r"(_[A-Za-z]{2,}(?:-[A-Za-z]{2,})?(?:_v\d+)?\.pdf)$", old_name)
        return new_stem + (suffix.group(1) if suffix else "_bilingual.pdf")

    def _rewrite_link_target(
        self,
        raw_target: str,
        note_path: Path,
        mapping: dict[Path, Path],
    ) -> str:
        target, marker, fragment = raw_target.partition("#")
        if not target or re.match(r"^[a-z][a-z0-9+.-]*://", target, flags=re.I):
            return raw_target
        normalized = target.replace("\\", "/")
        bare = "/" not in normalized
        candidates: list[Path] = []
        if bare:
            candidates = [old for old in mapping if old.name == Path(normalized).name]
        else:
            relative_candidate = (note_path.parent / normalized).resolve(strict=False)
            vault_candidate = (self.root / normalized.lstrip("/")).resolve(strict=False)
            candidates = [old for old in mapping if old in {relative_candidate, vault_candidate}]
        if not candidates:
            candidates = [old for old in mapping if old.name == Path(normalized).name]
        if len(candidates) != 1:
            return raw_target
        old = candidates[0]
        new = mapping[old]
        if bare:
            rewritten = new.name
        elif normalized.startswith("."):
            resolved_from_note = (note_path.parent / normalized).resolve(strict=False)
            if resolved_from_note == old:
                rewritten = Path(os.path.relpath(new, note_path.parent)).as_posix()
            else:
                rewritten = str(Path(normalized).with_name(new.name)).replace("\\", "/")
        else:
            rewritten = new.relative_to(self.root).as_posix()
        return rewritten + (marker + fragment if marker else "")

    def _rewrite_vault_links(self, mapping: dict[Path, Path]) -> dict[Path, str]:
        """Rewrite only Markdown link targets and return originals for rollback."""

        backups: dict[Path, str] = {}
        wiki_pattern = re.compile(r"(!?\[\[)([^\]|]+)(\|[^\]]*)?(\]\])")
        markdown_pattern = re.compile(r"(\]\()([^\s)]+)(\))")
        for note in self.root.rglob("*.md"):
            try:
                relative = note.relative_to(self.root)
            except ValueError:
                continue
            if relative.parts and relative.parts[0] == "_system":
                continue
            before = note.read_text("utf-8")

            def rewrite_wiki(match: re.Match[str]) -> str:
                target = self._rewrite_link_target(match.group(2), note, mapping)
                return f"{match.group(1)}{target}{match.group(3) or ''}{match.group(4)}"

            def rewrite_markdown(match: re.Match[str]) -> str:
                target = self._rewrite_link_target(match.group(2), note, mapping)
                return f"{match.group(1)}{target}{match.group(3)}"

            after = wiki_pattern.sub(rewrite_wiki, before)
            after = markdown_pattern.sub(rewrite_markdown, after)
            if after != before:
                backups[note] = before
                _atomic_write_text(note, after)
        return backups

    @staticmethod
    def _restore_markdown(backups: dict[Path, str]) -> None:
        for path, body in backups.items():
            _atomic_write_text(path, body)

    def _annotate_rollover_sources(
        self,
        rows: list[dict[str, Any]],
        target_batch: dict[str, Any],
    ) -> None:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            source_date = str(row.get("carryover_from_date") or "")
            source_batch_id = str(row.get("carryover_from_batch_id") or "")
            if source_date and source_batch_id:
                grouped.setdefault((source_batch_id, source_date), []).append(row)
        for (_source_batch_id, source_date), members in grouped.items():
            reading_list = (
                self.root
                / str(target_batch["field_slug"])
                / source_date
                / "00-Reading-List.md"
            )
            if not reading_list.is_file():
                continue
            lines = [
                "<!-- on1y:carryover:start -->",
                "",
                f"## Carried forward to {target_batch['batch_date']}",
                "",
            ]
            for row in members:
                link = Path(os.path.relpath(self.root / str(row["note_rel"]), reading_list.parent))
                lines.append(
                    f"- {int(row['carryover_from_position']):02d} → "
                    f"[[{link.as_posix()}|{row['title']}]]"
                )
            lines.extend(["", "<!-- on1y:carryover:end -->"])
            managed = "\n".join(lines)
            body = reading_list.read_text("utf-8")
            pattern = r"(?s)<!-- on1y:carryover:start -->.*?<!-- on1y:carryover:end -->"
            updated = (
                re.sub(pattern, lambda _match: managed, body, count=1)
                if re.search(pattern, body)
                else body.rstrip() + "\n\n" + managed + "\n"
            )
            _atomic_write_text(reading_list, updated)

    def publish(self, batch_id: str) -> dict[str, Any]:
        current = self.batch(batch_id)
        if not current:
            raise LookupError("batch not found")
        final = self.root / current["field_slug"] / current["batch_date"]
        if current["status"] == "published" and final.is_dir():
            return current
        if final.exists():
            raise FileExistsError(str(final))
        daily_target = int(self.config()["daily_target"])
        if len(current["papers"]) > daily_target:
            raise ValueError(
                f"batch contains {len(current['papers'])} papers; daily target is {daily_target}"
            )
        carryover_ids = [
            str(paper["id"])
            for paper in current["papers"]
            if paper.get("carryover_from_batch_id")
        ]
        if carryover_ids:
            placeholders = ",".join("?" for _paper_id in carryover_ids)
            with closing(self.connect()) as conn:
                active = conn.execute(
                    f"""SELECT COUNT(*) FROM translation_jobs
                    WHERE paper_id IN ({placeholders}) AND status IN ('queued','running')""",
                    carryover_ids,
                ).fetchone()[0]
            if int(active):
                raise ValueError("请等待待结转论文的双语 PDF 任务完成后再发布明日清单")
        staging_root = self.root / "_system" / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=batch_id + "-", dir=staging_root))
        for name in ("Original", "Bilingual", "Notes"):
            (staging / name).mkdir()
        rows: list[dict[str, Any]] = []
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE batches SET status='publishing',error=NULL WHERE id=?", (batch_id,)
            )
            conn.commit()
        final_created = False
        database_committed = False
        markdown_backups: dict[Path, str] = {}
        path_mapping: dict[Path, Path] = {}
        source_cleanup: list[Path] = []
        try:
            template = (self.root / "_templates" / "paper-note.md").read_text("utf-8")
            for paper in current["papers"]:
                pos = int(paper["position"])
                display_id = (
                    f"{current['field_code']}-{current['batch_date'].replace('-', '')}-{pos:03d}"
                )
                stem = f"{pos:03d}_{safe_stem(paper['title'])}"
                pdf_name, note_name = stem + ".pdf", stem + ".md"
                carryover = bool(paper.get("carryover_from_batch_id"))
                note_rel = (
                    Path(current["field_slug"]) / current["batch_date"] / "Notes" / note_name
                ).as_posix()
                pdf_rel: str | None = None
                bilingual_rel: str | None = None
                digest: str | None = None
                error: str | None = None
                old_paths = {
                    "original": paper.get("original_pdf_relpath"),
                    "bilingual": paper.get("bilingual_pdf_relpath"),
                    "note": paper.get("note_relpath"),
                }

                if carryover:
                    old_original = str(old_paths["original"] or "") or None
                    old_bilingual = str(old_paths["bilingual"] or "") or None
                    old_note = str(old_paths["note"] or "") or None
                    if old_original:
                        source = self.root / old_original
                        if not source.is_file():
                            raise FileNotFoundError(f"carryover original PDF not found: {source}")
                        destination = staging / "Original" / pdf_name
                        shutil.copy2(source, destination)
                        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                        if paper.get("pdf_sha256") and digest != paper["pdf_sha256"]:
                            raise ValueError(f"carryover PDF hash mismatch: {source}")
                        pdf_rel = (
                            Path(current["field_slug"])
                            / current["batch_date"]
                            / "Original"
                            / pdf_name
                        ).as_posix()
                    else:
                        error = "Full text unavailable automatically"

                    bilingual_name = self._renamed_bilingual_file(
                        old_original, old_bilingual, stem
                    )
                    if old_bilingual and bilingual_name:
                        source = self.root / old_bilingual
                        if not source.is_file():
                            raise FileNotFoundError(f"carryover bilingual PDF not found: {source}")
                        shutil.copy2(source, staging / "Bilingual" / bilingual_name)
                        bilingual_rel = (
                            Path(current["field_slug"])
                            / current["batch_date"]
                            / "Bilingual"
                            / bilingual_name
                        ).as_posix()

                    if not old_note or not (self.root / old_note).is_file():
                        raise FileNotFoundError(f"carryover note not found: {old_note or paper['id']}")
                    note = (self.root / old_note).read_text("utf-8")
                    note = re.sub(
                        r"(?m)^paper_id:\s*.*$", f"paper_id: {display_id}", note, count=1
                    )
                    managed = self._managed_pdf_links(pdf_name if pdf_rel else None, bilingual_name)
                    note = re.sub(
                        r"(?s)<!-- on1y:pdf-links:start -->.*?<!-- on1y:pdf-links:end -->",
                        lambda _match: managed,
                        note,
                        count=1,
                    )
                else:
                    digest, error = self._obtain_pdf(paper, staging / "Original" / pdf_name)
                    pdf_rel = (
                        (
                            Path(current["field_slug"])
                            / current["batch_date"]
                            / "Original"
                            / pdf_name
                        ).as_posix()
                        if digest
                        else None
                    )
                    managed = self._managed_pdf_links(pdf_name if digest else None, None)
                    note = template
                    replacements = {
                        "{{paper_id}}": display_id,
                        "{{title}}": paper["title"],
                        "{{authors}}": ", ".join(paper["authors"]),
                        "{{year}}": str(paper["year"] or ""),
                        "{{venue}}": str(paper["venue"] or ""),
                        "{{doi}}": str(paper["doi"] or ""),
                        "{{pdf_link}}": managed,
                    }
                    for key, value in replacements.items():
                        note = note.replace(key, value)

                (staging / "Notes" / note_name).write_text(note, encoding="utf-8")
                new_paths = {
                    "original": pdf_rel,
                    "bilingual": bilingual_rel,
                    "note": note_rel,
                }
                if carryover:
                    for kind in ("original", "bilingual", "note"):
                        old_rel = old_paths.get(kind)
                        new_rel = new_paths.get(kind)
                        if old_rel and new_rel:
                            old_absolute = (self.root / str(old_rel)).resolve(strict=False)
                            new_absolute = (self.root / str(new_rel)).resolve(strict=False)
                            path_mapping[old_absolute] = new_absolute
                            source_cleanup.append(old_absolute)
                rows.append(
                    {
                        **paper,
                        "pdf_rel": pdf_rel,
                        "bilingual_rel": bilingual_rel,
                        "note_rel": note_rel,
                        "pdf_sha256": digest,
                        "download_error": error,
                        "old_paths": old_paths,
                        "new_paths": new_paths,
                        "carryover": carryover,
                    }
                )
            reading = [
                f"# Reading List - {current['field']} - {current['batch_date']}",
                "",
                "| # | Status | Paper | Year | Venue | Area | Citations | Recommendation |",
                "|---:|---|---|---:|---|---|---:|---|",
            ]
            for row in rows:
                warning = " [classic]" if row.get("age_category") == "classic" else ""
                rec = str(row.get("recommendation") or "").replace("|", "\\|")
                if row["carryover"]:
                    rec = (
                        f"[carryover from {row.get('carryover_from_date')} "
                        f"#{int(row.get('carryover_from_position') or 0):02d}] {rec}"
                    ).strip()
                if row["download_error"]:
                    rec = (rec + " [Full text unavailable automatically]").strip()
                display_title = str(row["title"]).replace("|", "\\|")
                note_link = f"[[Notes/{Path(str(row['note_rel'])).name}\\|{display_title}]]"
                reading.append(
                    f"| {row['position']:02d} | {'carryover' if row['carryover'] else 'unread'} | "
                    f"{note_link} | "
                    f"{row.get('year') or ''}{warning} | {row.get('venue') or ''} | "
                    f"{row.get('area') or ''} | {row.get('citation_count') or ''} | {rec} |"
                )
            (staging / "00-Reading-List.md").write_text("\n".join(reading) + "\n", "utf-8")
            venues = sorted({str(row["venue"]) for row in rows if row.get("venue")})
            (staging / "01-Venue-Guide.md").write_text(
                "# Venue Guide\n\n" + "\n".join(f"- {v}" for v in venues) + "\n", "utf-8"
            )
            (staging / "Feedback.md").write_text(
                f"# {current['batch_date']} Feedback\n\nRead: 0 / {len(rows)}\n"
                f"Dismissed: 0\nPending: {len(rows)}\nCarried in: {len(carryover_ids)}\n",
                "utf-8",
            )
            final.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(5):
                try:
                    staging.replace(final)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    # Windows virus scanners/indexers can briefly hold a newly
                    # written PDF while the atomic directory publish occurs.
                    time.sleep(0.05 * (attempt + 1))
            final_created = True
            if path_mapping:
                markdown_backups = self._rewrite_vault_links(path_mapping)
            now = utc_now()
            with closing(self.connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                for row in rows:
                    conn.execute(
                        """UPDATE papers SET original_pdf_relpath=?,bilingual_pdf_relpath=?,
                        note_relpath=?,pdf_sha256=?,source_url=?,updated_at=? WHERE id=?""",
                        (
                            row["pdf_rel"],
                            row["bilingual_rel"],
                            row["note_rel"],
                            row["pdf_sha256"],
                            (
                                (self.root / str(row["pdf_rel"])).as_uri()
                                if row["carryover"]
                                and str(row.get("source_url") or "").startswith("file:")
                                and row["pdf_rel"]
                                else row.get("source_url")
                            ),
                            now,
                            row["id"],
                        ),
                    )
                    if row["carryover"]:
                        old_paths = row["old_paths"]
                        if old_paths.get("original") and row["pdf_rel"]:
                            conn.execute(
                                """UPDATE translation_jobs SET input_relpath=?,updated_at=?
                                WHERE paper_id=? AND input_relpath=?""",
                                (row["pdf_rel"], now, row["id"], old_paths["original"]),
                            )
                        if old_paths.get("bilingual") and row["bilingual_rel"]:
                            conn.execute(
                                """UPDATE translation_jobs SET output_relpath=?,updated_at=?
                                WHERE paper_id=? AND output_relpath=?""",
                                (
                                    row["bilingual_rel"],
                                    now,
                                    row["id"],
                                    old_paths["bilingual"],
                                ),
                            )
                        if old_paths.get("note"):
                            conn.execute(
                                "DELETE FROM note_scan_state WHERE note_relpath=?",
                                (old_paths["note"],),
                            )
                        conn.execute(
                            """UPDATE paper_rollovers SET status='committed',
                            old_paths_json=?,new_paths_json=?,error=NULL,committed_at=?
                            WHERE to_batch_id=? AND paper_id=?""",
                            (
                                json.dumps(old_paths, ensure_ascii=False),
                                json.dumps(row["new_paths"], ensure_ascii=False),
                                now,
                                batch_id,
                                row["id"],
                            ),
                        )
                    else:
                        conn.execute(
                            """INSERT INTO download_attempts(
                            paper_id,url,status,detail,attempted_at) VALUES(?,?,?,?,?)""",
                            (
                                row["id"],
                                row.get("pdf_url") or row.get("source_url"),
                                "ok" if row["pdf_sha256"] else "unavailable",
                                row["download_error"],
                                now,
                            ),
                        )
                conn.execute(
                    """UPDATE batches SET status='published',published_at=?,
                    error=NULL WHERE id=?""",
                    (now, batch_id),
                )
                conn.commit()
            database_committed = True
            try:
                self._annotate_rollover_sources(rows, current)
            except Exception:
                logger.exception("Could not annotate source reading list for %s", batch_id)
            for source in source_cleanup:
                try:
                    resolved = source.resolve(strict=False)
                    if self.root != resolved and self.root in resolved.parents and resolved.is_file():
                        resolved.unlink()
                except Exception:
                    logger.exception("Could not remove committed rollover source %s", source)
            from on1y.papers.settings_store import load_paper_settings

            settings = load_paper_settings(self.user_id)
            if settings.translation_enabled and settings.translation_auto_enqueue:
                try:
                    self.enqueue_translations(batch_id)
                except Exception as exc:
                    logger.warning("Could not auto-enqueue translations for %s: %s", batch_id, exc)
            self.write_reading_state()
            return self.batch(batch_id) or current
        except Exception as exc:
            if not database_committed:
                if markdown_backups:
                    self._restore_markdown(markdown_backups)
                if final_created and final.is_dir():
                    shutil.rmtree(final, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)
            with closing(self.connect()) as conn:
                if not database_committed:
                    conn.execute(
                        "UPDATE batches SET status='error',error=? WHERE id=?",
                        (str(exc), batch_id),
                    )
                conn.commit()
            raise

    def rebuild_feedback(self, batch_id: str) -> dict[str, Any]:
        current = self.batch(batch_id)
        if not current or current["status"] != "published":
            raise ValueError("published batch not found")
        output_rows = [f"# {current['batch_date']} Feedback", ""]
        changed = 0
        with closing(self.connect()) as conn:
            for paper in current["papers"]:
                rel = paper.get("note_relpath")
                note = self.root / rel if rel else None
                if not note or not note.is_file():
                    continue
                body, stat = note.read_text("utf-8"), note.stat()
                digest = hashlib.sha256(body.encode()).hexdigest()
                old = conn.execute(
                    "SELECT sha256 FROM note_scan_state WHERE note_relpath=?", (rel,)
                ).fetchone()
                changed += int(old is None or old["sha256"] != digest)
                match = re.search(r"(?m)^status:\s*([^\s]+)", body)
                status = match.group(1).casefold() if match else "unread"
                if status in {"read", "done", "finished"}:
                    canonical_status = "read"
                elif status in {"dismissed", "skipped"}:
                    canonical_status = "dismissed"
                elif status == "reading":
                    canonical_status = "reading"
                else:
                    canonical_status = "to_read"
                conn.execute(
                    """UPDATE papers SET status=?,read_date=?,updated_at=? WHERE id=?""",
                    (
                        canonical_status,
                        date.today().isoformat() if canonical_status == "read" else None,
                        utc_now(),
                        paper["id"],
                    ),
                )
                conn.execute(
                    """INSERT INTO note_scan_state VALUES(?,?,?,?,?)
                    ON CONFLICT(note_relpath) DO UPDATE SET mtime_ns=excluded.mtime_ns,
                    size=excluded.size,sha256=excluded.sha256,scanned_at=excluded.scanned_at""",
                    (rel, stat.st_mtime_ns, stat.st_size, digest, utc_now()),
                )
                note_body = freeform_note_body(body)
                if note_body:
                    output_rows.extend(
                        [f"## {paper['position']:03d} - {paper['title']}", "", note_body, ""]
                    )
            progress = self._batch_progress(conn, batch_id)
            output_rows[2:2] = [
                f"Read: {progress['read']} / {progress['total']}",
                f"Dismissed: {progress['dismissed']}",
                f"Pending: {progress['pending']}",
                f"Carried: {progress['carried']}",
                f"Changed notes: {changed}",
                "",
            ]
            content = "\n".join(output_rows).rstrip() + "\n"
            output = self.root / current["field_slug"] / current["batch_date"] / "Feedback.md"
            _atomic_write_text(output, content)
            digest = hashlib.sha256(content.encode()).hexdigest()
            conn.execute(
                """INSERT INTO feedback_snapshots VALUES(?,?,?)
                ON CONFLICT(batch_id) DO UPDATE SET content_sha256=excluded.content_sha256,
                generated_at=excluded.generated_at""",
                (batch_id, digest, utc_now()),
            )
            conn.commit()
        return {
            "batch_id": batch_id,
            **progress,
            "changed_notes": changed,
            "path": str(output),
        }

    def write_reading_state(self) -> dict[str, Any]:
        """Write a compact machine-readable handoff for the next Codex discussion."""

        self.initialize()
        published = [row for row in self.list_batches() if row.get("status") == "published"]
        latest = published[0] if published else None
        if latest:
            latest_date = date.fromisoformat(str(latest["batch_date"]))
            target = max(date.today(), latest_date.fromordinal(latest_date.toordinal() + 1))
            plan = self.daily_plan(target_date=target.isoformat(), field=str(latest["field"]))
            current = {
                "batch_id": latest["id"],
                "date": latest["batch_date"],
                "field": latest["field"],
                **latest["progress"],
            }
        else:
            target = date.today()
            plan = {
                "target_date": target.isoformat(),
                "field": "",
                "daily_target": int(self.config()["daily_target"]),
                "carryover": [],
                "carryover_count": 0,
                "new_slots": int(self.config()["daily_target"]),
                "backlog_remaining": 0,
                "blocking_fields": [],
                "can_change_field": True,
            }
            current = None
        carryover = [
            {
                "paper_id": row["id"],
                "title": row["title"],
                "from_date": row["from_date"],
                "from_position": row["from_position"],
                "field": row["from_field"],
            }
            for row in plan["carryover"]
        ]
        payload = {
            "version": 1,
            "generated_at": utc_now(),
            "current": current,
            "next": {
                "date": plan["target_date"],
                "field": plan["field"],
                "daily_target": plan["daily_target"],
                "carryover_count": plan["carryover_count"],
                "new_slots": plan["new_slots"],
                "backlog_remaining": plan["backlog_remaining"],
                "blocking_fields": plan["blocking_fields"],
                "carryover": carryover,
            },
        }
        path = self.root / "_system" / "reading-state.json"
        _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return {**payload, "path": str(path)}


def sync_published_to_shelf(
    storage: Any,
    user_id: int,
    *,
    vault: LiteratureVault | None = None,
    batch_id: str | None = None,
) -> dict[str, int]:
    """Project published Vault papers into On1y's Paper shelf.

    The Vault remains the source of truth.  This projection exists so the main
    Paper UI can read the same files, filter by their real folders, and switch
    to a bilingual PDF as soon as translation finishes.
    """

    from on1y.papers.knowledge_sync import prepare_paper
    from on1y.papers.models import PaperAuthor, PaperCreate, PaperFolder, PaperUpdate
    from on1y.papers.shelf import (
        create_paper,
        find_matching_paper,
        get_paper_by_literature_id,
        update_paper,
    )

    source = vault or LiteratureVault(user_id)
    batches = [source.batch(batch_id)] if batch_id else [
        source.batch(str(row["id"]))
        for row in source.list_batches()
        if row.get("status") == "published"
    ]
    created = updated = unchanged = 0
    for batch in batches:
        if not batch or batch.get("status") != "published":
            continue
        for row in batch.get("papers", []):
            literature_id = str(row["id"])
            bilingual_rel = row.get("bilingual_pdf_relpath")
            original_rel = row.get("original_pdf_relpath")
            preferred_rel = bilingual_rel or original_rel
            location_rel = preferred_rel or row.get("note_relpath")
            location_parts = Path(str(location_rel)).parts if location_rel else ()
            field_slug = (
                str(location_parts[0]) if len(location_parts) >= 2 else str(batch["field_slug"])
            )
            batch_date = (
                str(location_parts[1]) if len(location_parts) >= 2 else str(batch["batch_date"])
            )
            root_key = f"vault:{field_slug}"
            leaf_key = f"{root_key}/{batch_date}"
            folders = [
                PaperFolder(key=root_key, name=field_slug, path=field_slug),
                PaperFolder(
                    key=leaf_key,
                    name=batch_date,
                    path=f"{field_slug}/{batch_date}",
                    parent_key=root_key,
                ),
            ]
            pdf_path = (
                str((source.root / str(preferred_rel)).resolve(strict=False))
                if preferred_rel
                else None
            )
            authors = [PaperAuthor(name=name) for name in row.get("authors", [])]
            existing = get_paper_by_literature_id(storage, user_id, literature_id)
            if existing is None:
                existing = find_matching_paper(
                    storage,
                    user_id,
                    doi=row.get("doi"),
                    title=row.get("title"),
                    year=row.get("year"),
                    authors=authors,
                    pdf_path=pdf_path,
                )
            area = str(row.get("area") or "").strip()
            if existing is None:
                item = create_paper(
                    storage,
                    user_id,
                    PaperCreate(
                        title=str(row["title"]),
                        authors=authors,
                        abstract=row.get("abstract"),
                        status=(
                            str(row.get("status"))
                            if row.get("status") in READING_STATUSES
                            else "to_read"
                        ),
                        year=row.get("year"),
                        venue=row.get("venue"),
                        doi=row.get("doi"),
                        url=row.get("source_url"),
                        pdf_path=pdf_path,
                        citation_count=row.get("citation_count"),
                        tags=[area] if area else [],
                        folders=folders,
                        literature_paper_id=literature_id,
                    ),
                )
                prepare_paper(storage, user_id, item)
                created += 1
                continue

            changes: dict[str, Any] = {}
            current_folders = [folder for folder in existing.folders if not folder.key.startswith("vault:")]
            merged_folders = [*current_folders, *folders]
            if [value.model_dump() for value in merged_folders] != [
                value.model_dump() for value in existing.folders
            ]:
                changes["folders"] = merged_folders
            if existing.literature_paper_id != literature_id:
                changes["literature_paper_id"] = literature_id
            if pdf_path and existing.pdf_path != pdf_path:
                changes["pdf_path"] = pdf_path
            canonical_status = (
                str(row.get("status")) if row.get("status") in READING_STATUSES else "to_read"
            )
            if existing.status != canonical_status:
                changes["status"] = canonical_status
            if authors and not existing.authors:
                changes["authors"] = authors
            for name in ("abstract", "venue", "doi", "url", "year", "citation_count"):
                incoming = row.get("source_url") if name == "url" else row.get(name)
                if incoming not in (None, "") and getattr(existing, name) in (None, ""):
                    changes[name] = incoming
            if area and area.casefold() not in {tag.casefold() for tag in existing.tags}:
                changes["tags"] = [*existing.tags, area]
            if changes:
                item = update_paper(storage, user_id, existing.id, PaperUpdate(**changes))
                updated += 1
            else:
                item = existing
                unchanged += 1
            if item is not None and item.raw_id is None:
                prepare_paper(storage, user_id, item)
    return {"created": created, "updated": updated, "unchanged": unchanged}


def scan_published_feedback(user_id: int) -> dict[str, int]:
    """Rebuild machine feedback for every published batch in one user's Vault."""
    vault = LiteratureVault(user_id)
    scanned = changed = 0
    for batch in vault.list_batches():
        if batch.get("status") != "published":
            continue
        result = vault.rebuild_feedback(str(batch["id"]))
        scanned += 1
        changed += int(result["changed_notes"])
    vault.write_reading_state()
    return {"batches": scanned, "changed_notes": changed}


def _feedback_loop() -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import list_sync_user_ids

    while not _feedback_stop.is_set():
        try:
            storage = get_storage()
            try:
                user_ids = list_sync_user_ids(storage, current_user_only=True)
            finally:
                storage.close()
            for user_id in user_ids:
                try:
                    scan_published_feedback(user_id)
                except Exception:
                    logger.exception("Literature feedback scan failed for user %s", user_id)
        except Exception:
            logger.exception("Literature feedback watcher tick failed")
        _feedback_stop.wait(timeout=60)


def start_literature_feedback_loop() -> None:
    global _feedback_thread
    if _feedback_thread and _feedback_thread.is_alive():
        return
    _feedback_stop.clear()
    _feedback_thread = threading.Thread(
        target=_feedback_loop,
        name="on1y-literature-feedback",
        daemon=True,
    )
    _feedback_thread.start()


def stop_literature_feedback_loop() -> None:
    _feedback_stop.set()
