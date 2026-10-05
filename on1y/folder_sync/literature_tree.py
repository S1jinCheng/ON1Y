"""Portable, content-addressed synchronization for a Literature Vault tree.

The live SQLite database and machine-local caches never enter the protocol.
Only ordinary user documents are represented, one immutable ``file`` version
per canonical relative path.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from on1y.device_sync.protocol import record_key
from on1y.folder_sync.files import (
    FileCacheUpdate,
    available,
    cached_blob,
    signature,
)
from on1y.folder_sync.protocol import (
    BlobRef,
    LiteratureFileVersion,
    canonical_relative_path,
    portable_relative_path,
)

KIND = "literature_file"
FIELD = "file"
PRISTINE_PATHS = frozenset({"_templates/paper-note.md", "_system/config.yaml"})

_EXCLUDED_DIRECTORIES = {
    ".git",
    ".obsidian",
    ".stfolder",
    ".sync",
    ".trash",
    ".trashes",
    "__pycache__",
}
_EXCLUDED_FILES = {".ds_store", "desktop.ini", "thumbs.db"}
_EXCLUDED_SUFFIXES = {
    ".crdownload",
    ".db",
    ".ffs_db",
    ".ffs_tmp",
    ".lock",
    ".part",
    ".sqlite",
    ".sqlite3",
    ".tmp",
}
_EXCLUDED_ENDINGS = (
    "-journal",
    "-shm",
    "-wal",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".sqlite-journal",
    ".sqlite-shm",
    ".sqlite-wal",
)
_REPARSE_POINT = 0x400
_PLACEHOLDER_ATTRIBUTES = 0x1000 | 0x40000 | 0x400000


@dataclass(frozen=True)
class FileObservation:
    path: Path
    exists: bool
    available: bool
    signature: str | None = None
    blob: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiteratureTreeStats:
    files: int = 0
    staged: int = 0
    cached: int = 0
    unavailable: int = 0
    excluded: int = 0
    deleted: int = 0


@dataclass(frozen=True)
class LiteratureTreeScan:
    records: dict[str, dict]
    cache_updates: tuple[FileCacheUpdate, ...]
    observations: dict[str, FileObservation]
    stats: LiteratureTreeStats


@dataclass(frozen=True)
class LiteratureApplyResult:
    applied: bool
    reason: str
    target: Path
    observation: FileObservation | None = None
    cache_update: FileCacheUpdate | None = None


def _excluded_file(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in _EXCLUDED_FILES
        or lowered.startswith("~$")
        or lowered.endswith(_EXCLUDED_ENDINGS)
        or Path(lowered).suffix in _EXCLUDED_SUFFIXES
    )


def _excluded_directory(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _EXCLUDED_DIRECTORIES or lowered in {".recovery", ".staging"}


def _entry_attributes(entry: os.DirEntry[str]) -> int:
    try:
        return int(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0))
    except OSError as exc:
        raise ValueError(f"无法读取 Literature 路径：{entry.path}") from exc


def _count_excluded(folder: Path) -> int:
    """Best-effort display count; excluded state must never block user data."""
    count = 0
    pending = [folder]
    while pending:
        current = pending.pop()
        try:
            entries = tuple(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                attributes = int(
                    getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                )
                if (
                    entry.is_dir(follow_symlinks=False)
                    and not entry.is_symlink()
                    and not attributes & _REPARSE_POINT
                ):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    count += 1
            except OSError:
                continue
    return count


def _inventory(
    root: Path, *, count_excluded_files: bool = True
) -> tuple[list[tuple[str, Path]], int]:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Literature Vault 不可用，已暂停文件树同步") from exc
    if not resolved_root.is_dir():
        raise ValueError("Literature Vault 不可用，已暂停文件树同步")

    files: list[tuple[str, Path]] = []
    excluded = 0
    # Keep the native spelling as well as the normalized identity. APFS can
    # contain two distinct names that normalize to one Windows path.
    identities: dict[str, str] = {}
    pending: list[Path] = [resolved_root]
    while pending:
        folder = pending.pop()
        try:
            entries = tuple(os.scandir(folder))
        except OSError as exc:
            raise ValueError(f"无法读取 Literature 目录：{folder}") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                relative_native = path.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError("Literature 路径逸出 Vault，已暂停同步") from exc
            native_parts = relative_native.parts
            is_system = len(native_parts) == 1 and native_parts[0].casefold() == "_system"
            try:
                is_link = entry.is_symlink()
                is_directory = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError as exc:
                raise ValueError(f"无法检查 Literature 路径：{path}") from exc

            attributes = _entry_attributes(entry)
            if is_link or (is_directory and attributes & _REPARSE_POINT):
                raise ValueError(f"Literature 包含链接，已暂停同步：{relative_native}")
            if is_directory and (is_system or _excluded_directory(entry.name)):
                if is_system:
                    config = path / "config.yaml"
                    if config.is_file() and not config.is_symlink():
                        normalized = portable_relative_path("_system/config.yaml")
                        identity = canonical_relative_path(normalized)
                        native = relative_native.joinpath("config.yaml").as_posix()
                        collision = identities.get(identity)
                        if collision is not None:
                            raise ValueError(
                                "Literature 路径在 Mac/Windows 上会冲突："
                                f"{collision} / {native}"
                            )
                        files.append((normalized, config))
                        identities[identity] = native
                        excluded += (
                            max(0, _count_excluded(path) - 1) if count_excluded_files else 1
                        )
                    else:
                        excluded += _count_excluded(path) if count_excluded_files else 1
                else:
                    excluded += _count_excluded(path) if count_excluded_files else 1
                continue
            if is_directory:
                pending.append(path)
                continue
            if not is_file:
                excluded += 1
                continue
            if _excluded_file(entry.name):
                excluded += 1
                continue
            if attributes & _REPARSE_POINT and not attributes & _PLACEHOLDER_ATTRIBUTES:
                raise ValueError(f"Literature 包含重解析文件，已暂停同步：{relative_native}")
            native = relative_native.as_posix()
            normalized = portable_relative_path(native)
            identity = canonical_relative_path(normalized)
            collision = identities.get(identity)
            if collision is not None:
                raise ValueError(
                    f"Literature 路径在 Mac/Windows 上会冲突：{collision} / {native}"
                )
            identities[identity] = native
            files.append((normalized, path))
    return files, excluded


def iter_sync_files(root: Path):
    """Yield ``(portable_relative_path, absolute_path)`` for scheduler hints."""
    files, _ = _inventory(Path(root), count_excluded_files=False)
    yield from files


def _matching_pristine_paths(scan: LiteratureTreeScan) -> set[str]:
    import yaml

    from on1y.papers.literature import DEFAULT_DAILY_TARGET, DEFAULT_PAPER_NOTE_TEMPLATE

    default_config = yaml.safe_dump(
        {
            "version": 1,
            "daily_target": DEFAULT_DAILY_TARGET,
            "source": "local-vault",
        },
        allow_unicode=True,
        sort_keys=False,
    )
    expected = {
        "_templates/paper-note.md": DEFAULT_PAPER_NOTE_TEMPLATE,
        "_system/config.yaml": default_config,
    }
    matched = set()
    for path, body in expected.items():
        observation = scan.observations.get(canonical_relative_path(path))
        if observation is None or not observation.exists or not observation.available:
            continue
        try:
            # Text mode normalizes CRLF written by Windows, so generated
            # defaults compare equally on both platforms.
            if observation.path.read_text("utf-8") == body:
                matched.add(path)
        except (OSError, UnicodeError):
            continue
    return matched


def is_pristine_scan(scan: LiteratureTreeScan | None) -> bool:
    """Whether a new Vault contains only files generated by initialize()."""
    if scan is None:
        return False
    active = {
        record["fields"][FIELD]["path"]
        for record in scan.records.values()
        if not record["fields"][FIELD]["deleted"]
    }
    return active <= _matching_pristine_paths(scan)


def is_join_baseline(scan: LiteratureTreeScan, state: dict[str, dict]) -> bool:
    """Accept generated defaults plus files already materialized from remote state."""
    defaults = _matching_pristine_paths(scan)
    for key, record in scan.records.items():
        local = record["fields"][FIELD]
        if local["deleted"]:
            continue
        if local["path"] in defaults:
            continue
        remote = state.get(key)
        if (
            remote is None
            or any(conflict["field"] == FIELD for conflict in remote["conflicts"])
            or remote["fields"].get(FIELD) != local
        ):
            return False
    return True


def _tree_previous(previous: dict[str, dict] | None) -> dict[str, dict]:
    return {
        key: record
        for key, record in (previous or {}).items()
        if record.get("kind") == KIND and isinstance(record.get("fields", {}).get(FIELD), dict)
    }


def scan_literature_tree(
    conn: sqlite3.Connection,
    root: Path,
    staging: Path,
    previous: dict[str, dict] | None = None,
) -> LiteratureTreeScan:
    """Scan outside a write transaction and stage only new content versions."""
    root = Path(root).resolve(strict=True)
    old_records = _tree_previous(previous)
    old_by_identity = {record["identity"]: record for record in old_records.values()}
    inventory, excluded = _inventory(root)
    records: dict[str, dict] = {}
    observations: dict[str, FileObservation] = {}
    updates: list[FileCacheUpdate] = []
    staged = cached = unavailable = 0

    for relative, path in inventory:
        identity = canonical_relative_path(relative)
        key = record_key(KIND, identity)
        old = old_by_identity.get(identity)
        if not available(path):
            unavailable += 1
            if old is not None:
                records[key] = {
                    "key": key,
                    "kind": KIND,
                    "identity": identity,
                    "fields": {FIELD: old["fields"][FIELD]},
                }
            observations[identity] = FileObservation(path, True, False)
            continue
        blob, update = cached_blob(conn, path, staging)
        if blob is None:
            raise ValueError(f"Literature 文件正在变化，将在下一轮重试：{relative}")
        if update is None:
            cached += 1
        else:
            staged += 1
            updates.append(update)
        version = LiteratureFileVersion(path=relative, blob=blob, deleted=False).model_dump(
            mode="json"
        )
        records[key] = {
            "key": key,
            "kind": KIND,
            "identity": identity,
            "fields": {FIELD: version},
        }
        observations[identity] = FileObservation(
            path=path,
            exists=True,
            available=True,
            signature=signature(path),
            blob=blob,
        )

    deleted = 0
    for key, old in old_records.items():
        if key in records:
            continue
        value = LiteratureFileVersion.model_validate(old["fields"][FIELD])
        target = root.joinpath(*value.path.split("/"))
        if target.exists() and not available(target):
            records[key] = {
                "key": key,
                "kind": KIND,
                "identity": old["identity"],
                "fields": {FIELD: value.model_dump(mode="json")},
            }
            observations[old["identity"]] = FileObservation(target, True, False)
            unavailable += 1
            continue
        tombstone = value.model_copy(update={"deleted": True}).model_dump(mode="json")
        records[key] = {
            "key": key,
            "kind": KIND,
            "identity": old["identity"],
            "fields": {FIELD: tombstone},
        }
        observations[old["identity"]] = FileObservation(target, False, True)
        if not value.deleted:
            deleted += 1

    return LiteratureTreeScan(
        records=records,
        cache_updates=tuple(updates),
        observations=observations,
        stats=LiteratureTreeStats(
            files=sum(not record["fields"][FIELD]["deleted"] for record in records.values()),
            staged=staged,
            cached=cached,
            unavailable=unavailable,
            excluded=excluded,
            deleted=deleted,
        ),
    )


def _safe_target(root: Path, relative: str) -> Path:
    root = root.resolve(strict=True)
    normalized = portable_relative_path(relative)
    target = root.joinpath(*normalized.split("/"))
    current = root
    for part in normalized.split("/")[:-1]:
        current = current / part
        if current.exists():
            info = current.lstat()
            attributes = int(getattr(info, "st_file_attributes", 0))
            if stat.S_ISLNK(info.st_mode) or attributes & _REPARSE_POINT:
                raise ValueError("Literature 目标路径包含链接，已暂停同步")
    if not target.resolve(strict=False).is_relative_to(root):
        raise ValueError("Literature 目标路径逸出 Vault，已暂停同步")
    return target


def _unchanged(observation: FileObservation | None) -> bool:
    if observation is None:
        return True
    if not observation.available:
        return False
    if not observation.exists:
        return not observation.path.exists()
    try:
        return observation.path.is_file() and signature(observation.path) == observation.signature
    except OSError:
        return False


def _trash_target(root: Path, relative: str) -> Path:
    relative = portable_relative_path(relative)
    trash_relative = f"_system/folder-sync-trash/{uuid4()}/{relative}"
    destination = _safe_target(root, trash_relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Re-check after creating parents so a concurrently substituted junction
    # cannot redirect the recoverable backup outside the Vault.
    return _safe_target(root, trash_relative)


def _backup_existing(root: Path, source: Path, relative: str) -> None:
    destination = _trash_target(root, relative)
    # A hard link changes source ctime on POSIX and invalidates our own
    # compare-and-swap check. It also shares later in-place edits with the backup.
    shutil.copy2(source, destination)


def _stage_verified_copy(source: Path, target: Path, ref: BlobRef) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{uuid4()}.tmp")
    hasher = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as reader, temp.open("xb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
                hasher.update(chunk)
                size += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if size != ref.size or hasher.hexdigest() != ref.sha256:
            raise ValueError("Literature 对象尚未完整下载或校验失败")
        return temp
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _still_safe_to_replace(
    target: Path, expected: FileObservation | None, *, same_location: bool = False
) -> bool:
    if expected is None:
        return not target.exists()
    if not _unchanged(expected):
        return False
    return same_location or expected.path == target or not target.exists()


def apply_literature_version(
    root: Path,
    version: dict[str, Any],
    source: Path | None,
    expected: FileObservation | None,
) -> LiteratureApplyResult:
    """Apply one winner with compare-and-swap protection and recoverable deletion."""
    root = Path(root).resolve(strict=True)
    value = LiteratureFileVersion.model_validate(version)
    target = _safe_target(root, value.path)
    if expected is None and target.exists():
        return LiteratureApplyResult(False, "changed", target)
    if not _unchanged(expected):
        return LiteratureApplyResult(False, "changed", target)

    if value.deleted:
        if expected and expected.exists:
            destination = _trash_target(root, value.path)
            if not _unchanged(expected):
                return LiteratureApplyResult(False, "changed", target)
            try:
                os.replace(expected.path, destination)
            except OSError as exc:
                raise ValueError("Literature 文件无法移入同步回收站") from exc
        observation = FileObservation(target, False, True)
        return LiteratureApplyResult(True, "deleted", target, observation)

    ref = BlobRef.model_validate(value.blob)
    if (
        expected
        and expected.exists
        and expected.available
        and expected.blob
        and expected.blob.get("sha256") == ref.sha256
        and expected.path == target
    ):
        return LiteratureApplyResult(True, "current", target, expected)
    if source is None or not available(source):
        return LiteratureApplyResult(False, "pending", target)
    if source.stat().st_size != ref.size:
        raise ValueError("Literature 对象尚未完整下载或校验失败")

    same_location = False
    if expected and expected.exists and target.exists():
        try:
            same_location = os.path.samefile(expected.path, target)
        except OSError:
            same_location = False
        if expected.path != target and not same_location:
            return LiteratureApplyResult(False, "changed", target)
    if expected and expected.exists:
        _backup_existing(root, expected.path, value.path)
    temp = _stage_verified_copy(source, target, ref)
    try:
        # Copying a large PDF may take seconds. Re-check immediately before
        # replacement so a file created or edited during that window wins.
        if not _still_safe_to_replace(target, expected, same_location=same_location):
            return LiteratureApplyResult(False, "changed", target)
        os.replace(temp, target)
        if (
            expected
            and expected.exists
            and expected.path != target
            and not same_location
            and expected.path.exists()
        ):
            destination = _trash_target(root, value.path)
            os.replace(expected.path, destination)
    finally:
        temp.unlink(missing_ok=True)
    observation = FileObservation(
        target,
        True,
        True,
        signature(target),
        ref.model_dump(mode="json"),
    )
    update = FileCacheUpdate(
        str(target), observation.signature or "", ref.model_dump(mode="json")
    )
    return LiteratureApplyResult(True, "written", target, observation, update)
