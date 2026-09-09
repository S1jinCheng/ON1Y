"""Upload and folder-sync local PDF files into the Paper library."""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from on1y.papers.models import PaperAuthor, PaperCreate, PaperUpdate
from on1y.papers.settings_store import load_paper_settings, resolve_paper_cache_dir
from on1y.papers.sync_lock import paper_sync_lock

logger = logging.getLogger(__name__)
_thread: threading.Thread | None = None
_stop = threading.Event()

_UNSAFE = re.compile(r"[^\w\-. ()\[\]]+", re.UNICODE)


def safe_pdf_name(title: str) -> str:
    stem = _UNSAFE.sub("_", title.strip()).strip(" ._")[:180] or "paper"
    return f"{stem}.pdf"


def validate_pdf(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 5:
        raise ValueError("PDF 文件为空或不存在")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError("文件不是有效的 PDF")


def import_pdf(
    user_id: int,
    path: Path,
    *,
    title: str | None = None,
    authors: list[str] | None = None,
    status: str = "to_read",
) -> dict[str, Any]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.papers.knowledge_sync import prepare_paper
    from on1y.papers.shelf import create_paper, find_matching_paper, update_paper

    validate_pdf(path)
    resolved = path.resolve()
    paper_title = (
        title or path.stem.replace("_", " ").replace("-", " ")
    ).strip() or "未命名论文"
    paper_authors = [
        PaperAuthor(name=name)
        for name in authors or []
        if name.strip()
    ]
    with paper_sync_lock(user_id), user_context(user_id):
        storage = get_storage()
        try:
            existing = find_matching_paper(
                storage,
                user_id,
                title=paper_title,
                authors=paper_authors,
                pdf_path=str(resolved),
            )
            if existing is not None:
                changes: dict[str, Any] = {}
                if not existing.pdf_path:
                    changes["pdf_path"] = str(resolved)
                    changes["url"] = resolved.as_uri()
                if paper_authors and not existing.authors:
                    changes["authors"] = paper_authors
                item = (
                    update_paper(
                        storage,
                        user_id,
                        existing.id,
                        PaperUpdate(**changes),
                    )
                    if changes
                    else existing
                )
                assert item is not None
                item = prepare_paper(storage, user_id, item)
                return {
                    "ok": True,
                    "created": False,
                    "paper": item,
                    "local_path": str(resolved),
                }

            item = create_paper(
                storage,
                user_id,
                PaperCreate(
                    title=paper_title,
                    authors=paper_authors,
                    status=(
                        status
                        if status in {"to_read", "reading", "read"}
                        else "to_read"
                    ),
                    pdf_path=str(resolved),
                    url=resolved.as_uri(),
                ),
            )
            item = prepare_paper(storage, user_id, item)
            return {
                "ok": True,
                "created": True,
                "paper": item,
                "local_path": str(resolved),
            }
        finally:
            storage.close()

def scan_paper_folder(user_id: int) -> dict[str, Any]:
    from on1y.adapters.sqlite_storage import get_storage

    settings = load_paper_settings(user_id)
    folder = resolve_paper_cache_dir(user_id, settings.cache_dir)
    if not settings.folder_sync_enabled:
        return {"enabled": False, "folder": str(folder), "imported": 0, "skipped": 0, "errors": []}
    state_path = folder / ".on1y-paper-sync.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except Exception:
        state = {}
    storage = get_storage()
    try:
        known = {
            str(row["pdf_path"]).lower()
            for row in storage._connect()
            .execute(
                "SELECT pdf_path FROM paper_items WHERE user_id = ? AND pdf_path IS NOT NULL",
                (user_id,),
            )
            .fetchall()
        }
    finally:
        storage.close()
    imported = 0
    skipped = 0
    errors: list[str] = []
    for path in sorted(folder.rglob("*.pdf")):
        if path.name.startswith("."):
            continue
        key = str(path.resolve()).lower()
        signature = f"{path.stat().st_size}:{path.stat().st_mtime_ns}"
        if key in known or state.get(key) == signature:
            skipped += 1
            state[key] = signature
            continue
        try:
            result = import_pdf(user_id, path)
            state[key] = signature
            known.add(key)
            if result.get("created"):
                imported += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "enabled": True,
        "folder": str(folder),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def _folder_sync_loop() -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import list_sync_user_ids

    while not _stop.is_set():
        try:
            storage = get_storage()
            try:
                user_ids = list_sync_user_ids(storage, current_user_only=True)
            finally:
                storage.close()
            for user_id in user_ids:
                try:
                    scan_paper_folder(user_id)
                except Exception:
                    logger.exception("Paper folder sync failed for user %s", user_id)
        except Exception:
            logger.exception("Paper folder sync tick failed")
        _stop.wait(timeout=15)


def start_paper_folder_sync_loop() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_folder_sync_loop,
        name="on1y-paper-folder-sync",
        daemon=True,
    )
    _thread.start()


def stop_paper_folder_sync_loop() -> None:
    _stop.set()
