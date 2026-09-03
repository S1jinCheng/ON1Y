"""Import ebook files from the configured books folder into the user's shelf."""

from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from on1y.books.file_validate import validate_ebook_file
from on1y.books.settings_store import load_book_settings
from on1y.books.zlib_links import BOOK_FORMATS

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()
_user_locks: dict[int, threading.RLock] = {}


@contextmanager
def folder_sync_lock(user_id: int) -> Iterator[None]:
    """Serialize manual imports and background scans for one user."""
    with _lock:
        user_lock = _user_locks.setdefault(user_id, threading.RLock())
    with user_lock:
        yield


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
        logger.warning("Invalid book folder sync state, rebuilding: %s", path)
        return {}


def _save_state(user_id: int, state: dict[str, Any]) -> None:
    path = _state_path(user_id)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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
    """Import one file, persist its shelf card, then attempt Kindle delivery."""
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.books.acquire import maybe_send_kindle
    from on1y.books.display_name import format_book_label
    from on1y.books.kindle_notes import merge_kindle_status
    from on1y.books.knowledge_sync import prepare_shelf_item
    from on1y.books.models import BookLink, BookShelfCreate, BookShelfUpdate
    from on1y.books.shelf import create_shelf_item, delete_shelf_item, update_shelf_item

    fmt = path.suffix.lower().lstrip(".")
    book_title = (title or _title_from_path(path)).strip() or _title_from_path(path)
    book_author = (author or "").strip() or None
    validation = validate_ebook_file(path, fmt)
    if not validation.get("ok"):
        raise ValueError(str(validation.get("detail") or "电子书文件无效"))

    notes = f"cached: {path.resolve()}\nsource: {source}\noriginal: {path.name}"
    notes = merge_kindle_status(notes, "pending", "正在准备 Kindle 推送")
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
            try:
                item = prepare_shelf_item(storage, user_id, item)
            except Exception:
                delete_shelf_item(storage, user_id, int(item.id))
                raise
        finally:
            storage.close()

    kindle_sent, kindle_status, kindle_detail = maybe_send_kindle(
        user_id,
        path,
        title=format_book_label(title=book_title, author=book_author),
    )
    final_notes = merge_kindle_status(notes, kindle_status, kindle_detail)
    with user_context(user_id):
        storage = get_storage()
        try:
            try:
                updated = update_shelf_item(
                    storage,
                    user_id,
                    int(item.id),
                    BookShelfUpdate(notes=final_notes),
                )
                if updated is not None:
                    item = updated
            except Exception:
                # The shelf card and local file are already durable. Keep the
                # pending card if only the delivery-status update fails.
                logger.exception("Could not update Kindle status for shelf item %s", item.id)
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
    with folder_sync_lock(user_id):
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


def _retry_kindle(user_id: int, path: Path, shelf_item_id: int) -> tuple[str, str | None]:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import user_context
    from on1y.books.acquire import maybe_send_kindle
    from on1y.books.display_name import format_book_label_from_shelf
    from on1y.books.kindle_notes import merge_kindle_status
    from on1y.books.models import BookShelfUpdate
    from on1y.books.shelf import get_shelf_item, update_shelf_item

    with user_context(user_id):
        storage = get_storage()
        try:
            item = get_shelf_item(storage, user_id, shelf_item_id)
            if item is None:
                return "missing", "书库条目不存在"
            _sent, status, detail = maybe_send_kindle(
                user_id,
                path,
                title=format_book_label_from_shelf(item),
            )
            update_shelf_item(
                storage,
                user_id,
                shelf_item_id,
                BookShelfUpdate(notes=merge_kindle_status(item.notes, status, detail)),
            )
            return status, detail
        finally:
            storage.close()


def _scan_user_folder(user_id: int) -> dict[str, Any]:
    settings = load_book_settings(user_id)
    if not settings.folder_sync_enabled:
        return {"enabled": False, "imported": 0, "skipped": 0, "errors": []}
    from on1y.user.paths import resolve_books_cache_dir

    folder = resolve_books_cache_dir(user_id, settings.cache_dir)
    state = _load_state(user_id)
    imported = 0
    skipped = 0
    dirty = False
    errors: list[str] = []
    now = time.time()
    for path in _scan_files(folder):
        key = _file_key(path)
        signature = ""
        try:
            stat = path.stat()
            signature = f"{stat.st_size}:{stat.st_mtime_ns}"
            key = _file_key(path)
            previous = state.get(key)
            if isinstance(previous, dict) and previous.get("signature") == signature:
                if previous.get("kindle_status") == "failed":
                    retry_at = float(previous.get("retry_at") or 0)
                    if retry_at > now:
                        skipped += 1
                        continue
                    shelf_id = int(previous.get("shelf_item_id") or 0)
                    if shelf_id:
                        status, detail = _retry_kindle(user_id, path, shelf_id)
                        previous["kindle_status"] = status
                        previous["kindle_detail"] = detail
                        previous["retry_at"] = now + 60 if status == "failed" else None
                        dirty = True
                        skipped += 1
                        continue
                elif previous.get("kindle_status") == "import_failed":
                    if float(previous.get("retry_at") or 0) > now:
                        skipped += 1
                        continue
                else:
                    skipped += 1
                    continue

            existing_id = _existing_shelf_id_for_path(user_id, path)
            if existing_id is not None:
                state[key] = {
                    "signature": signature,
                    "shelf_item_id": existing_id,
                    "kindle_status": "existing",
                }
                dirty = True
                skipped += 1
                continue
            result = import_local_file(user_id, path)
            state[key] = {
                "signature": signature,
                "shelf_item_id": result["shelf_item"]["id"],
                "kindle_status": result["kindle_status"],
                "retry_at": now + 60 if result["kindle_status"] == "failed" else None,
            }
            dirty = True
            imported += 1
        except Exception as exc:
            state[key] = {
                "signature": signature,
                "kindle_status": "import_failed",
                "retry_at": now + 60,
            }
            dirty = True
            errors.append(f"{path.name}: {exc}")
            logger.warning("Book folder import failed for %s: %s", path, exc)
    if dirty:
        _save_state(user_id, state)
    return {
        "enabled": True,
        "folder": str(folder),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


def scan_user_folder(user_id: int) -> dict[str, Any]:
    with folder_sync_lock(user_id):
        return _scan_user_folder(user_id)


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
