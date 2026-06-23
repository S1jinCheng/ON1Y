"""Import Markdown notes from Obsidian vault into raw_items."""

from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from on1y.distill.processor import distill_raw_item
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.obsidian.settings import resolve_paths
from on1y.ports.storage import StoragePort
from on1y.utils.platform import normalize_url

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 2 * 1024 * 1024
_OBSIDIAN_AVATAR = "https://obsidian.md/images/obsidian-logo-gradient.svg"


@dataclass(slots=True)
class ParsedObsidianNote:
    path: Path
    rel_path: str
    title: str
    body_text: str
    url: str | None
    tags: list[str]
    theme_slug: str | None
    source_url: str | None
    author: str | None
    description: str | None
    frontmatter: dict[str, Any]
    content_hash: str
    mtime: float
    abs_path: str


def import_obsidian_batch(
    storage: StoragePort,
    *,
    user_id: int | None = None,
    limit: int = 50,
    auto_distill: bool | None = None,
) -> dict[str, Any]:
    cfg, inbox_dir, archive_dir = resolve_paths(user_id=user_id)
    if not cfg.enabled:
        return {"enabled": False, "reason": "disabled", "scanned": 0, "imported": 0, "failed": 0, "skipped": 0}
    if inbox_dir is None:
        return {
            "enabled": True,
            "reason": "vault_path_missing",
            "scanned": 0,
            "imported": 0,
            "failed": 0,
            "skipped": 0,
        }
    if not inbox_dir.is_dir():
        return {
            "enabled": True,
            "reason": "inbox_not_found",
            "inbox": str(inbox_dir),
            "scanned": 0,
            "imported": 0,
            "failed": 0,
            "skipped": 0,
        }

    should_distill = cfg.auto_distill if auto_distill is None else bool(auto_distill)
    rows = sorted((p for p in inbox_dir.rglob("*.md") if p.is_file()), key=lambda p: p.stat().st_mtime)
    report: dict[str, Any] = {
        "enabled": True,
        "reason": "ok",
        "scanned": 0,
        "imported": 0,
        "failed": 0,
        "skipped": 0,
        "distilled": 0,
        "errors": [],
        "inbox": str(inbox_dir),
        "archive": str(archive_dir) if archive_dir is not None else None,
    }
    for file_path in rows[: max(1, limit)]:
        report["scanned"] += 1
        try:
            parsed = _parse_note(file_path, inbox_dir=inbox_dir)
            if parsed is None:
                report["skipped"] += 1
                continue
            existing = storage.get_raw_by_url(parsed.url) if parsed.url else None
            if existing and _already_imported_from_same_note(existing.source_meta, parsed):
                report["skipped"] += 1
                continue
            raw = _upsert_note(storage, parsed)
            if parsed.tags or parsed.theme_slug:
                storage.set_item_classification(
                    raw.id,
                    theme_slug=parsed.theme_slug,
                    tags=parsed.tags,
                    source="manual",
                )
            if should_distill:
                try:
                    distill_raw_item(storage, raw.id)
                    report["distilled"] += 1
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"distill #{raw.id}: {exc}")
            # Keep Obsidian vault as the source of truth: never move/delete source notes.
            _post_import_file(file_path, parsed.rel_path, "keep", archive_dir=archive_dir)
            report["imported"] += 1
        except Exception as exc:  # noqa: BLE001
            report["failed"] += 1
            report["errors"].append(f"{file_path}: {exc}")
            logger.warning("Obsidian import failed for %s: %s", file_path, exc)
    report["error_count"] = len(report["errors"])
    return report


def _parse_note(path: Path, *, inbox_dir: Path) -> ParsedObsidianNote | None:
    if path.stat().st_size > _MAX_FILE_BYTES:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _split_frontmatter(text)
    body = body.strip()
    if not body:
        return None
    title = _pick_title(frontmatter, body, fallback=path.stem)
    url_raw = str(
        frontmatter.get("source")
        or frontmatter.get("url")
        or frontmatter.get("source_url")
        or ""
    ).strip()
    normalized_url = normalize_url(url_raw) if url_raw else None
    tags = _parse_tags(frontmatter.get("tags"))
    theme_slug = str(frontmatter.get("theme") or frontmatter.get("theme_slug") or "").strip() or None
    author = str(frontmatter.get("author") or "").strip() or None
    description = str(frontmatter.get("description") or "").strip() or None
    content_hash = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()
    rel_path = path.relative_to(inbox_dir).as_posix()
    source_url = normalized_url or f"on1y://obsidian/{content_hash}"
    return ParsedObsidianNote(
        path=path,
        rel_path=rel_path,
        title=title,
        body_text=body,
        url=source_url,
        tags=tags,
        theme_slug=theme_slug,
        source_url=normalized_url,
        author=author,
        description=description,
        frontmatter=frontmatter,
        content_hash=content_hash,
        mtime=path.stat().st_mtime,
        abs_path=str(path.resolve()),
    )


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    fm: dict[str, Any] = {}
    for line in raw.splitlines():
        row = line.strip()
        if not row or row.startswith("#") or ":" not in row:
            continue
        key, value = row.split(":", 1)
        fm[key.strip().lower()] = value.strip().strip('"').strip("'")
    return fm, body


def _parse_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw]
        return [v for v in values if v]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (ValueError, SyntaxError):
            pass
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _pick_title(frontmatter: dict[str, Any], body: str, *, fallback: str) -> str:
    title = str(frontmatter.get("title") or "").strip()
    if title:
        return title[:500]
    for line in body.splitlines()[:20]:
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()[:500]
    return fallback[:500]


def _already_imported_from_same_note(meta: dict[str, Any] | None, parsed: ParsedObsidianNote) -> bool:
    current = dict(meta or {})
    old_hash = str(current.get("obsidian_hash") or "").strip()
    old_path = str(current.get("obsidian_path") or "").strip()
    old_mtime = float(current.get("obsidian_mtime") or 0.0)
    return old_hash == parsed.content_hash and old_path == parsed.rel_path and old_mtime >= parsed.mtime


def _upsert_note(storage: StoragePort, parsed: ParsedObsidianNote):
    obsidian_uri = _build_obsidian_uri(parsed.abs_path)
    source_meta = {
        "clip_source": "obsidian",
        "obsidian_path": parsed.rel_path,
        "obsidian_abs_path": parsed.abs_path,
        "obsidian_uri": obsidian_uri,
        "obsidian_source_url": parsed.source_url or "",
        "obsidian_hash": parsed.content_hash,
        "obsidian_mtime": parsed.mtime,
        "obsidian_frontmatter": parsed.frontmatter,
        "obsidian_title": parsed.title,
        "obsidian_description": parsed.description or "",
        "author": parsed.author or "Obsidian",
        "author_avatar": _OBSIDIAN_AVATAR,
        "author_url": "https://obsidian.md/",
    }
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url=parsed.url or f"on1y://obsidian/{parsed.content_hash}",
            platform="obsidian",
            source=SourceType.MANUAL,
            raw_title=parsed.title,
            body_text=parsed.body_text,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            extract_error=None,
            source_meta=source_meta,
        )
    )
    return raw


def _post_import_file(path: Path, rel_path: str, mode: str, *, archive_dir: Path | None) -> None:
    normalized = (mode or "keep").strip().lower()
    if normalized == "keep":
        return
    # Obsidian notes are user-owned source files. Keep behavior readonly.
    return


def _build_obsidian_uri(abs_path: str) -> str:
    # Obsidian desktop supports opening file paths via obsidian://open?path=<absolute-path>
    return f"obsidian://open?path={quote(abs_path)}"
