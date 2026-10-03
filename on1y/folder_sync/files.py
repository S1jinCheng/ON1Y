"""Atomic immutable cloud objects and verified, editable local attachment copies."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
from pathlib import Path
from uuid import uuid4

from on1y.folder_sync.protocol import MAX_EVENT_BYTES, Attachment


def safe_child(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("同步目录包含指向外部的链接，已停止")
    return path


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_EVENT_BYTES:
        raise ValueError("同步记录超过大小限制")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("同步记录格式不正确")
    return data


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{uuid4()}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def available(path: Path) -> bool:
    if not path.is_file():
        return False
    flags = getattr(path.stat(), "st_flags", 0)
    return not flags & getattr(stat, "UF_DATALESS", 0x40000000)


def signature(path: Path) -> str:
    info = path.stat()
    return f"{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}:{info.st_ino}"


def cached_attachment(conn: sqlite3.Connection, path: Path, staging: Path) -> dict | None:
    if not available(path):
        return None
    value = signature(path)
    cached = conn.execute(
        "SELECT * FROM folder_sync_file_cache WHERE path=?", (str(path),)
    ).fetchone()
    if cached and cached["signature"] == value:
        attachment = json.loads(cached["data"])
        if safe_child(staging, attachment["sha256"]).is_file():
            return attachment
    attachment = stage_attachment(path, staging)
    if attachment:
        conn.execute(
            "INSERT OR REPLACE INTO folder_sync_file_cache VALUES (?,?,?)",
            (str(path), value, json.dumps(attachment)),
        )
    return attachment


def stage_attachment(path: Path, staging: Path) -> dict | None:
    """Missing/offloaded files never mean remote deletion."""
    from on1y.folder_sync.protocol import EXTENSIONS

    if not available(path) or path.suffix.lower() not in EXTENSIONS:
        return None
    before = path.stat()
    if before.st_size > 2 * 1024**3:
        raise ValueError("第一版附件上限为 2 GiB，请移除过大的附件后重试")
    staging.mkdir(parents=True, exist_ok=True)
    temp = staging / f".{uuid4()}.tmp"
    try:
        shutil.copyfile(path, temp)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("附件正在修改，将在下一轮同步")
        sha = digest(temp)
        destination = safe_child(staging, sha)
        if not destination.exists():
            os.replace(temp, destination)
        return {"sha256": sha, "extension": path.suffix.lower(), "size": before.st_size}
    finally:
        temp.unlink(missing_ok=True)


def publish_blob(staging: Path, root: Path, attachment: dict) -> bool:
    ref = Attachment.model_validate(attachment)
    target = safe_child(root, "objects", ref.sha256)
    if target.is_file():
        if not available(target):
            return False
        if target.stat().st_size != ref.size or digest(target) != ref.sha256:
            raise ValueError("云端附件校验失败，已停止同步")
        return True
    source = safe_child(staging, ref.sha256)
    if not available(source):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{uuid4()}.tmp")
    try:
        shutil.copyfile(source, temp)
        if temp.stat().st_size != ref.size or digest(temp) != ref.sha256:
            raise ValueError("本地附件校验失败")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return True


def receive_blob(
    root: Path,
    cache: Path,
    key: str,
    attachment: dict,
    conn: sqlite3.Connection | None = None,
) -> Path | None:
    ref = Attachment.model_validate(attachment)
    # Each content version gets its own editable copy. Never overwrite an open PDF.
    target = safe_child(cache, key, ref.sha256 + ref.extension)
    copy_number = 0
    while target.is_file():
        cached = (
            conn.execute(
                "SELECT * FROM folder_sync_file_cache WHERE path=?", (str(target),)
            ).fetchone()
            if conn is not None
            else None
        )
        checksum = (
            json.loads(cached["data"])["sha256"]
            if cached and cached["signature"] == signature(target)
            else digest(target)
        )
        if checksum == ref.sha256:
            return target
        # An external reader edited this copy. Preserve it even when an older
        # revision is explicitly restored or a concurrent revision wins.
        copy_number += 1
        target = safe_child(cache, key, f"{ref.sha256}-{copy_number}{ref.extension}")
    source = safe_child(root, "objects", ref.sha256)
    if not available(source):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{uuid4()}.tmp")
    try:
        shutil.copyfile(source, temp)
        if temp.stat().st_size != ref.size or digest(temp) != ref.sha256:
            raise ValueError("附件尚未完整下载或校验失败，请等待 iCloud 下载完成")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target
