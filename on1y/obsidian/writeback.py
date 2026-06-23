"""Append-only writeback from On1y to Obsidian markdown notes."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from on1y.obsidian.settings import load_settings


def build_writeback_block(
    *,
    on1y_url: str,
    relation_type: str,
    summary: str | None,
    context: str | None,
    note: str | None = None,
    link_raw_id: int | None = None,
) -> str:
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    key = str(link_raw_id) if link_raw_id is not None else hashlib.sha1(on1y_url.encode("utf-8")).hexdigest()[:12]
    begin_marker = f"<!-- ON1Y_LINK_BEGIN:{key} -->"
    end_marker = f"<!-- ON1Y_LINK_END:{key} -->"
    lines = [
        "",
        begin_marker,
        "## On1y 关联",
        f"- 写回时间: {ts}",
        f"- 关系类型: {relation_type or 'related'}",
        f"- On1y 链接: {on1y_url}",
    ]
    if note and note.strip():
        lines.append(f"- 备注: {note.strip()[:500]}")
    if summary and summary.strip():
        lines.extend(["", "### 摘要", summary.strip()[:1200]])
    if context and context.strip():
        lines.extend(["", "### 上下文", context.strip()[:1800]])
    lines.extend(["", "---", end_marker, ""])
    return "\n".join(lines)


def enqueue_writeback(
    storage: Any,
    *,
    target_rel_path: str,
    content_md: str,
    block_anchor: str | None = None,
    link_raw_id: int | None = None,
) -> dict[str, Any]:
    queued = storage.enqueue_obsidian_writeback(
        target_rel_path=target_rel_path,
        content_md=content_md,
        block_anchor=block_anchor,
        link_raw_id=link_raw_id,
    )
    if link_raw_id is not None and hasattr(storage, "merge_source_meta"):
        storage.merge_source_meta(int(link_raw_id), {"obsidian_writeback_status": "pending"})
    return queued


def apply_writeback_queue(
    storage: Any,
    *,
    user_id: int | None = None,
    limit: int = 20,
    force: bool = False,
) -> dict[str, Any]:
    cfg = load_settings(user_id=user_id)
    if not cfg.writeback_enabled and not force:
        return {"enabled": False, "applied": 0, "failed": 0, "skipped": 0}
    vault_path = Path(cfg.vault_path).expanduser().resolve()
    if not str(cfg.vault_path or "").strip() or not vault_path.is_dir():
        return {"enabled": True, "applied": 0, "failed": 0, "skipped": 0, "reason": "vault_path_missing"}

    jobs = storage.claim_pending_obsidian_writeback(limit=max(1, int(limit)))
    report = {"enabled": True, "applied": 0, "failed": 0, "skipped": 0, "processed": len(jobs)}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for job in jobs:
        qid = int(job["id"])
        rel_path = str(job.get("target_rel_path") or "").strip().replace("\\", "/")
        if not rel_path:
            storage.mark_obsidian_writeback_status(qid, status="failed", last_error="empty target_rel_path")
            report["failed"] += 1
            continue
        try:
            target = _resolve_target_path(vault_path, rel_path)
            if target is None:
                storage.mark_obsidian_writeback_status(qid, status="skipped", last_error="target file missing")
                if job.get("link_raw_id") and hasattr(storage, "merge_source_meta"):
                    storage.merge_source_meta(int(job["link_raw_id"]), {"obsidian_writeback_status": "skipped"})
                report["skipped"] += 1
                continue
            if not str(target).startswith(str(vault_path)):
                storage.mark_obsidian_writeback_status(
                    qid, status="failed", last_error="target path escapes vault"
                )
                report["failed"] += 1
                continue
            body = target.read_text(encoding="utf-8", errors="replace")
            patch = str(job.get("content_md") or "")
            begin, end = _extract_markers(patch)
            if begin and end:
                body = _upsert_marked_block(body, patch, begin, end)
            else:
                if not body.endswith("\n"):
                    body += "\n"
                body += patch
            target.write_text(body, encoding="utf-8")
            storage.mark_obsidian_writeback_status(qid, status="applied", applied_at=now)
            if job.get("link_raw_id") and hasattr(storage, "merge_source_meta"):
                storage.merge_source_meta(
                    int(job["link_raw_id"]),
                    {"obsidian_writeback_status": "applied", "obsidian_writeback_at": now},
                )
            report["applied"] += 1
        except Exception as exc:  # noqa: BLE001
            storage.mark_obsidian_writeback_status(qid, status="failed", last_error=str(exc))
            if job.get("link_raw_id") and hasattr(storage, "merge_source_meta"):
                storage.merge_source_meta(int(job["link_raw_id"]), {"obsidian_writeback_status": "failed"})
            report["failed"] += 1
    return report


def remove_writeback_block(
    storage: Any,
    *,
    target_rel_path: str,
    link_raw_id: int,
    user_id: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    cfg = load_settings(user_id=user_id)
    if not cfg.writeback_enabled and not force:
        return {"enabled": False, "removed": 0, "skipped": 1, "reason": "disabled"}
    vault_path = Path(cfg.vault_path).expanduser().resolve()
    if not str(cfg.vault_path or "").strip() or not vault_path.is_dir():
        return {"enabled": True, "removed": 0, "skipped": 1, "reason": "vault_path_missing"}
    rel_path = str(target_rel_path or "").strip().replace("\\", "/")
    target = _resolve_target_path(vault_path, rel_path)
    if target is None:
        return {"enabled": True, "removed": 0, "skipped": 1, "reason": "target_file_missing"}
    begin_marker = f"<!-- ON1Y_LINK_BEGIN:{int(link_raw_id)} -->"
    end_marker = f"<!-- ON1Y_LINK_END:{int(link_raw_id)} -->"
    body = target.read_text(encoding="utf-8", errors="replace")
    updated = _remove_marked_block(body, begin_marker, end_marker)
    if updated == body:
        return {"enabled": True, "removed": 0, "skipped": 1, "reason": "marker_not_found"}
    target.write_text(updated, encoding="utf-8")
    return {"enabled": True, "removed": 1, "skipped": 0}


def _extract_markers(patch: str) -> tuple[str | None, str | None]:
    begin_match = re.search(r"<!--\s*ON1Y_LINK_BEGIN:[^>]+-->", patch)
    end_match = re.search(r"<!--\s*ON1Y_LINK_END:[^>]+-->", patch)
    return (begin_match.group(0) if begin_match else None, end_match.group(0) if end_match else None)


def _resolve_target_path(vault_path: Path, rel_path: str) -> Path | None:
    direct = (vault_path / rel_path).resolve()
    if direct.exists() and direct.is_file():
        return direct
    filename = Path(rel_path).name.strip()
    if not filename:
        return None
    matches = [p.resolve() for p in vault_path.rglob(filename) if p.is_file()]
    if len(matches) == 1:
        return matches[0]
    rel_norm = rel_path.replace("\\", "/")
    for item in matches:
        try:
            item_rel = item.relative_to(vault_path).as_posix()
        except ValueError:
            continue
        if item_rel.endswith(rel_norm):
            return item
    return None


def _upsert_marked_block(body: str, patch: str, begin_marker: str, end_marker: str) -> str:
    start = body.find(begin_marker)
    end = body.find(end_marker)
    if start != -1 and end != -1 and end > start:
        end_pos = end + len(end_marker)
        prefix = body[:start]
        suffix = body[end_pos:]
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if suffix and not suffix.startswith("\n"):
            suffix = "\n" + suffix
        return prefix + patch.strip("\n") + "\n" + suffix.lstrip("\n")
    if not body.endswith("\n"):
        body += "\n"
    return body + patch


def _remove_marked_block(body: str, begin_marker: str, end_marker: str) -> str:
    start = body.find(begin_marker)
    end = body.find(end_marker)
    if start == -1 or end == -1 or end <= start:
        return body
    end_pos = end + len(end_marker)
    # Remove optional trailing newline(s) after end marker for cleaner output.
    while end_pos < len(body) and body[end_pos] == "\n":
        end_pos += 1
    prefix = body[:start].rstrip("\n")
    suffix = body[end_pos:].lstrip("\n")
    if prefix and suffix:
        return prefix + "\n\n" + suffix
    if prefix:
        return prefix + "\n"
    return suffix
