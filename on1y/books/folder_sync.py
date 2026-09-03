"""Import ebook files from the configured books folder into the user's shelf."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from on1y.books.file_validate import validate_ebook_bytes
from on1y.books.settings_store import load_book_settings
from on1y.books.zlib_links import BOOK_FORMATS

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()


def _state_path(user_id: int) -> Path:
    from on1y.user.paths import user_dir

    path = user_dir(user_id) / "books" / "folder_sync.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_state(user_id: int) -> dict[str, Any]:
    path = _state_path(user_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(user_id: int, state: dict[str, Any]) -> None:
    _state_path(user_id).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _file_key(path: Path) -> str:
    return str(path.resolve()).lower()


def _title_from_path(path: Path) -> str:
    title = path.stem.replace("_", " ").replace("-", " ")
    return " ".join(title.split()) or path.stem or "未命名电子书"


def _scan_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower().lstrip(".") in BOOK_FORMATS
        ),
        key=lambda path: path.name.lower(),
    )


def import_local_file(
    user_id: int,
    path: Path,
    *,
    source: str = "folder-sync",
    title: str | None = None,
    author: str | None = None,
    status: str = "reading",
) -> dict[str, Any]:
    """Import one already-present file, create its shelf card, and email it to Kindle."""
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.books.acquire import KINDLE_EMAIL_MAX_BYTES, maybe_send_kindle
    from on1y.books.display_name import format_book_label
    from on1y.books.kindle_notes import merge_kindle_status
    from on1y.books.knowledge_sync import prepare_shelf_item
    from on1y.books.models import BookLink, BookShelfCreate
    from on1y.books.shelf import create_shelf_item
    from on1y.user.profile import load_user_profile

    fmt = path.suffix.lower().lstrip(".")
    book_title = (title or _title_from_path(path)).strip() or _title_from_path(path)
    book_author = (author or "").strip() or None
    data = path.read_bytes()
    validation = validate_ebook_bytes(data, fmt)
    if not validation.get("ok"):
        raise ValueError(str(validation.get("detail") or "电子书文件无效"))
    if len(data) > KINDLE_EMAIL_MAX_BYTES:
        kindle_status, kindle_detail = "skipped", "文件超过 Kindle 邮件上限（50MB）"
        kindle_sent = False
    else:
        with user_context(user_id):
            profile = load_user_profile(user_id)
            kindle_config = profile.get("kindle") if isinstance(profile.get("kindle"), dict) else {}
            if kindle_config.get("enabled", True):
                kindle_sent, kindle_status, kindle_detail = maybe_send_kindle(
                    user_id,
                    path,
                    title=format_book_label(title=book_title, author=book_author),
                )
            else:
                kindle_sent, kindle_status, kindle_detail = False, "skipped", "Kindle 推送已关闭"
    notes = f"cached: {path.resolve()}\nsource: {source}\noriginal: {path.name}"
    notes = merge_kindle_status(notes, kindle_status, kindle_detail)
    link = BookLink(label=f"本地 {fmt.upper()}", url=path.resolve().as_uri())
    with user_context(user_id):
        storage = get_storage()
        try:
            item = create_shelf_item(
                storage,
                user_id,
                BookShelfCreate(
                    title=book_title,
                    author=book_author,
                    status=status if status in {"reading", "read"} else "reading",
                    links=[link],
                    notes=notes,
                    cached_format=fmt,
                ),
            )
            item = prepare_shelf_item(storage, user_id, item)
        finally:
            storage.close()
    return {
        "ok": True,
        "shelf_item": item.model_dump(),
        "kindle_sent": kindle_sent,
        "kindle_status": kindle_status,
        "kindle_detail": kindle_detail,
        "format": fmt,
        "local_path": str(path.resolve()),
    }

def mark_file_seen(user_id: int, path: Path, result: dict[str, Any]) -> None:
    """Prevent a manually uploaded file from being imported again by the watcher."""
    stat = path.stat()
    state = _load_state(user_id)
    state[_file_key(path)] = {
        "signature": f"{stat.st_size}:{stat.st_mtime_ns}",
        "shelf_item_id": result.get("shelf_item", {}).get("id"),
        "kindle_status": result.get("kindle_status"),
    }
    _save_state(user_id, state)

def _existing_shelf_id_for_path(user_id: int, path: Path) -> int | None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.books.models import parse_cached_path

    target = str(path.resolve())
    storage = get_storage()
    try:
        rows = storage._connect().execute(
            "SELECT id, notes FROM book_shelf_items WHERE user_id = ? AND notes IS NOT NULL",
            (user_id,),
        ).fetchall()
        for row in rows:
            if parse_cached_path(row["notes"]) == target:
                return int(row["id"])
    finally:
        storage.close()
    return None

def scan_user_folder(user_id: int) -> dict[str, Any]:
    settings = load_book_settings(user_id)
    if not settings.folder_sync_enabled:
        return {"enabled": False, "imported": 0, "skipped": 0, "errors": []}
    from on1y.user.paths import resolve_books_cache_dir

    folder = resolve_books_cache_dir(user_id, settings.cache_dir)
    state = _load_state(user_id)
    imported = 0
    skipped = 0
    errors: list[str] = []
    for path in _scan_files(folder):
        try:
            stat = path.stat()
            signature = f"{stat.st_size}:{stat.st_mtime_ns}"
            key = _file_key(path)
            previous = state.get(key)
            if isinstance(previous, dict) and previous.get("signature") == signature:
                skipped += 1
                continue
            existing_id = _existing_shelf_id_for_path(user_id, path)
            if existing_id is not None:
                state[key] = {
                    "signature": signature,
                    "shelf_item_id": existing_id,
                    "kindle_status": "existing",
                }
                skipped += 1
                continue
            result = import_local_file(user_id, path)
            state[key] = {
                "signature": signature,
                "shelf_item_id": result["shelf_item"]["id"],
                "kindle_status": result["kindle_status"],
            }
            imported += 1
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            logger.warning("Book folder import failed for %s: %s", path, exc)
    _save_state(user_id, state)
    return {
        "enabled": True,
        "folder": str(folder),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def _loop() -> None:
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
                scan_user_folder(user_id)
        except Exception:
            logger.exception("Book folder sync tick failed")
        _stop.wait(timeout=15)


def start_folder_sync_loop() -> None:
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="on1y-book-folder-sync", daemon=True)
        _thread.start()


def stop_folder_sync_loop() -> None:
    _stop.set()
