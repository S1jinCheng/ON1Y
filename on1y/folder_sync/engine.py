"""File transport with durable local operations and convergent field versions.

Only immutable JSON events and content-addressed attachments enter the cloud.
Each device has its own SQLite database. Parent sets, not wall clocks or file
arrival order, detect concurrency. Missing parents wait for a later cloud pass.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from uuid import UUID, uuid4

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.device_sync.client import sync_lock
from on1y.device_sync.library import now
from on1y.device_sync.protocol import encode, record_key
from on1y.folder_sync import records
from on1y.folder_sync.files import (
    atomic_write,
    available,
    publish_blob,
    read_json,
    receive_blob,
    safe_child,
    signature,
)
from on1y.folder_sync.protocol import MAX_EVENT_BYTES, VERSION, Event

MANIFEST = "on1y-library.json"


def suggested_folder() -> str:
    if sys.platform == "darwin":
        root = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
    else:
        root = Path.home() / "iCloudDrive"
        if not root.is_dir():
            root = Path.home() / "iCloud Drive"
    return str(root / "On1y Library") if root.is_dir() else ""


class FolderSync:
    def __init__(self, storage: SqliteStorage):
        self.storage = storage
        self.conn = storage._connect()
        self.cache = storage.db_path.parent / "folder-sync-files"
        self.staging = storage.db_path.parent / "folder-sync-staging"
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS folder_sync_config (
                id INTEGER PRIMARY KEY CHECK(id=1), user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL, folder TEXT NOT NULL, library_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0, last_sync TEXT, last_error TEXT,
                pending_files INTEGER NOT NULL DEFAULT 0,
                pending_events INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS folder_sync_mapping (
                key TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
                local_id INTEGER NOT NULL, identity TEXT NOT NULL,
                UNIQUE(user_id,kind,local_id));
            CREATE TABLE IF NOT EXISTS folder_sync_events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS folder_sync_shadow (
                key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS folder_sync_file_cache (
                path TEXT PRIMARY KEY, signature TEXT NOT NULL, data TEXT NOT NULL);
        """)

    def config(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM folder_sync_config WHERE id=1").fetchone()
        return dict(row) if row else None

    def check_owner(self, user_id: int) -> None:
        config = self.config()
        if config and config["user_id"] != user_id:
            raise ValueError("文件夹同步已绑定另一个本地账号")

    def check_relay(self) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_sync_config'"
        ).fetchone()
        if (
            exists
            and self.conn.execute("SELECT 1 FROM device_sync_config WHERE enabled=1").fetchone()
        ):
            raise ValueError("请先关闭服务地址方式的跨设备同步，再开启文件夹同步")

    def configure(self, user_id: int, folder: str, enabled: bool, *, create: bool = False) -> None:
        self.check_owner(user_id)
        old = self.config()
        if not self.conn.execute(
            "SELECT 1 FROM users WHERE id=? AND is_active=1", (user_id,)
        ).fetchone():
            raise ValueError("请先登录有效的本地账号")
        if enabled:
            self.check_relay()
        if old and not enabled and folder == old["folder"]:
            with self.conn:
                self.conn.execute("UPDATE folder_sync_config SET enabled=0 WHERE id=1")
            return
        root = Path(folder).expanduser()
        if not folder.strip() or not root.is_absolute():
            raise ValueError("请选择资料库文件夹的完整路径")
        root = root.resolve()
        db_dir = self.storage.db_path.parent.resolve()
        if db_dir.is_relative_to(root) or root.is_relative_to(db_dir):
            raise ValueError("同步目录必须与 On1y 本机数据库目录分开")
        if not root.parent.is_dir():
            raise ValueError("上级目录不存在，请先启用 iCloud Drive 或选择现有目录")
        manifest = safe_child(root, MANIFEST)
        if not manifest.is_file():
            if old or not create:
                raise ValueError("资料库标识尚未下载，请等待 iCloud 完成；新资料库请选创建")
            if root.exists() and any(root.iterdir()):
                raise ValueError("请使用空文件夹创建资料库，避免混入其他文件")
            root.mkdir(exist_ok=True)
            library_id = str(uuid4())
            atomic_write(manifest, encode({"version": VERSION, "library_id": library_id}).encode())
        info = read_json(manifest)
        if info.get("version") != VERSION:
            raise ValueError("资料库版本不兼容，请更新两端 On1y")
        library_id = str(UUID(info["library_id"]))
        if old and old["library_id"] != library_id:
            raise ValueError("此设备已绑定其他资料库，不能直接切换以免混合数据")
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO folder_sync_config(id,user_id,device_id,folder,library_id,enabled)
                VALUES (1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                folder=excluded.folder,enabled=excluded.enabled,last_error=NULL
            """,
                (
                    user_id,
                    old["device_id"] if old else str(uuid4()),
                    str(root),
                    library_id,
                    int(enabled),
                ),
            )

    def events(self) -> list[dict]:
        return [
            json.loads(row[0]) for row in self.conn.execute("SELECT data FROM folder_sync_events")
        ]

    def state(self) -> tuple[dict, int]:
        events = self.events()
        by_id = {event["id"]: event for event in events}
        applied: set[str] = set()
        state: dict[str, dict] = {}
        pending = 0
        for event in sorted(events, key=lambda e: (e["clock"], e["device_id"], e["id"])):
            parents = {p for values in event["parents"].values() for p in values}
            parents.update(event["dependencies"])
            if any(p not in applied for p in parents):
                pending += 1
                continue
            key = record_key(event["kind"], event["identity"])
            for parent_id in parents:
                parent = by_id[parent_id]
                if (parent["kind"], parent["identity"]) != (event["kind"], event["identity"]) or (
                    parent["clock"] >= event["clock"]
                ):
                    raise ValueError("同步记录的版本依赖不正确")
            record = state.setdefault(
                key,
                {
                    "key": key,
                    "kind": event["kind"],
                    "identity": event["identity"],
                    "fields": {},
                    "heads": {},
                    "conflicts": [],
                },
            )
            for field, value in event["patch"].items():
                for parent_id in event["parents"][field]:
                    parent = by_id[parent_id]
                    if (parent["kind"], parent["identity"]) != (
                        event["kind"],
                        event["identity"],
                    ) or (field not in parent["patch"] or parent["clock"] >= event["clock"]):
                        raise ValueError("同步记录的版本依赖不正确")
                heads = record["heads"].setdefault(field, {})
                for parent_id in event["parents"][field]:
                    heads.pop(parent_id, None)
                heads[event["id"]] = value
            applied.add(event["id"])
        for record in state.values():
            for field, versions in record["heads"].items():

                def rank(event_id: str, field=field, versions=versions):
                    event = by_id[event_id]
                    return (
                        field == "_deleted" and versions[event_id] is True,
                        event["clock"],
                        event["device_id"],
                        event_id,
                    )

                winner = max(versions, key=rank)
                record["fields"][field] = versions[winner]
                if len({encode(value) for value in versions.values()}) > 1:
                    record["conflicts"].append(
                        {
                            "field": field,
                            "winner": winner,
                            "versions": [
                                {"id": eid, "value": value} for eid, value in versions.items()
                            ],
                        }
                    )
            record["heads"] = {
                field: sorted(versions) for field, versions in record["heads"].items()
            }
        return state, pending

    def status(self, user_id: int) -> dict:
        self.check_owner(user_id)
        config = self.config() or {}
        state, _ = self.state()
        conflicts = []
        deleted = []
        for key, record in state.items():
            title = (
                record["fields"].get("library/title")
                or record["fields"].get("raw_title")
                or record["identity"]
            )
            conflicts.extend({"key": key, "title": title, **c} for c in record["conflicts"])
            if record["fields"].get("_deleted"):
                deleted.append({"key": key, "title": title})
        return {
            "enabled": bool(config.get("enabled")),
            "folder": config.get("folder", ""),
            "suggested_folder": suggested_folder(),
            "library_id": config.get("library_id", ""),
            "last_sync": config.get("last_sync"),
            "last_error": config.get("last_error"),
            "pending_files": config.get("pending_files", 0),
            "pending_events": config.get("pending_events", 0),
            "records": len(state),
            "conflicts": conflicts,
            "deleted": deleted,
        }

    def add_event(self, record: dict, patch: dict, heads: dict) -> str:
        config = self.config()
        clock = max((e["clock"] for e in self.events()), default=0) + 1
        event = Event(
            library_id=config["library_id"],
            id=uuid4(),
            device_id=config["device_id"],
            clock=clock,
            kind=record["kind"],
            identity=record["identity"],
            patch=patch,
            parents={f: heads.get(f, []) for f in patch},
            dependencies=sorted({p for versions in heads.values() for p in versions}),
        ).model_dump(mode="json")
        data = encode(event)
        if len(data.encode()) > MAX_EVENT_BYTES:
            raise ValueError("单条资料超过同步大小限制")
        self.conn.execute("INSERT INTO folder_sync_events VALUES (?,?)", (event["id"], data))
        return event["id"]

    def capture(self, user_id: int) -> dict:
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            local = records.snapshot(self.conn, user_id, self.staging)
            previous = {
                r[0]: json.loads(r[1])
                for r in self.conn.execute("SELECT * FROM folder_sync_shadow")
            }
            for key, old in previous.items():
                if key not in local:
                    local[key] = {**old, "fields": {**old["fields"], "_deleted": True}}
            # Pending own events are the baseline on retry, even if cloud publishing failed.
            for key, record in local.items():
                old = previous.get(key, {"fields": {}, "heads": {}})
                patch = {
                    f: record["fields"].get(f)
                    for f in set(record["fields"]) | set(old["fields"])
                    if record["fields"].get(f) != old["fields"].get(f)
                }
                if patch:
                    event_id = self.add_event(record, patch, old["heads"])
                heads = {**old["heads"], **({f: [event_id] for f in patch} if patch else {})}
                self.conn.execute(
                    "INSERT OR REPLACE INTO folder_sync_shadow VALUES (?,?)",
                    (
                        key,
                        encode(
                            {
                                **record,
                                "heads": heads,
                                "applied_heads": old.get("applied_heads", {}),
                            }
                        ),
                    ),
                )
            return local

    def sync(self, user_id: int) -> dict:
        self.check_owner(user_id)
        config = self.config()
        if not config or not config["enabled"]:
            raise ValueError("请先开启文件夹同步")
        self.check_relay()
        root = Path(config["folder"])
        marker = safe_child(root, MANIFEST)
        if not available(marker):
            raise ValueError("资料库目录不可用或尚未下载，已暂停同步")
        manifest = read_json(marker)
        if manifest.get("library_id") != config["library_id"] or manifest.get("version") != VERSION:
            raise ValueError("资料库标识或版本已改变，已暂停同步")
        captured = self.capture(user_id)
        events_dir = safe_child(root, "events")
        events_dir.mkdir(exist_ok=True)
        checked_blobs = set()
        for event in self.events():
            if attachment := event["patch"].get("attachment"):
                sha = attachment["sha256"]
                if sha not in checked_blobs:
                    object_path = safe_child(root, "objects", sha)
                    cached = self.conn.execute(
                        "SELECT signature FROM folder_sync_file_cache WHERE path=?",
                        (str(object_path),),
                    ).fetchone()
                    if not (
                        available(object_path) and cached and cached[0] == signature(object_path)
                    ) and publish_blob(self.staging, root, attachment):
                        with self.conn:
                            self.conn.execute(
                                "INSERT OR REPLACE INTO folder_sync_file_cache VALUES (?,?,?)",
                                (str(object_path), signature(object_path), encode(attachment)),
                            )
                    checked_blobs.add(sha)
            target = safe_child(root, "events", event["id"] + ".json")
            payload = encode(event).encode()
            if target.exists():
                if read_json(target) != event:
                    raise ValueError("同步记录被改写，已停止")
            else:
                atomic_write(target, payload)
        incoming = []
        waiting = 0
        for path in events_dir.iterdir():
            if path.name.endswith(".json.icloud"):
                waiting += 1
                continue
            if path.name.startswith(".") or path.suffix != ".json":
                continue
            safe_child(root, "events", path.name)
            if not available(path):
                waiting += 1
                continue
            try:
                event = Event.model_validate(read_json(path)).model_dump(mode="json")
            except (FileNotFoundError, json.JSONDecodeError):
                waiting += 1
                continue
            if event["library_id"] != config["library_id"]:
                raise ValueError("文件夹中混入其他资料库的记录，已停止")
            old = self.conn.execute(
                "SELECT data FROM folder_sync_events WHERE id=?", (event["id"],)
            ).fetchone()
            if old and json.loads(old[0]) != event:
                raise ValueError("同一同步记录出现不同内容，已停止")
            incoming.append(event)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            for event in incoming:
                self.conn.execute(
                    "INSERT OR IGNORE INTO folder_sync_events VALUES (?,?)",
                    (event["id"], encode(event)),
                )
        state, pending_events = self.state()
        paths = {}
        pending_files = 0
        for key, record in state.items():
            if record["fields"].get("_deleted"):
                continue
            if attachment := record["fields"].get("attachment"):
                path = receive_blob(root, self.cache, key, attachment, self.conn)
                if path:
                    paths[key] = path
                else:
                    pending_files += 1
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current = records.snapshot(self.conn, user_id, self.staging)
            shadows = {
                row[0]: json.loads(row[1])
                for row in self.conn.execute("SELECT * FROM folder_sync_shadow")
            }
            themes_changed = any(
                r["kind"] == "theme" and r["heads"] != shadows.get(k, {}).get("applied_heads")
                for k, r in state.items()
            )
            protected: dict[str, dict] = {}
            for key, record in sorted(state.items(), key=lambda pair: pair[1]["kind"] != "theme"):
                before = captured.get(key, {}).get("fields", {})
                live = current.get(key, {}).get("fields", {})
                if key in captured and key not in current:
                    live = {**before, "_deleted": True}
                changes = {
                    f: live.get(f) for f in set(before) | set(live) if live.get(f) != before.get(f)
                }
                if key in captured and key not in current and not before.get("_deleted"):
                    # Physical local deletion during cloud I/O stays deleted.
                    protected[key] = {"_deleted": True}
                    continue
                protected[key] = changes
                if themes_changed or record["heads"] != shadows.get(key, {}).get("applied_heads"):
                    records.write_record(
                        self.conn, user_id, {**record, "fields": {**record["fields"], **changes}}
                    )
                if key in paths and "attachment" not in changes:
                    records.bind_attachment(self.conn, user_id, key, paths[key])
            normalized = records.snapshot(self.conn, user_id, self.staging)
            for key, record in state.items():
                baseline = dict(normalized.get(key, record)["fields"])
                for field in protected.get(key, {}):
                    baseline[field] = record["fields"].get(field)
                self.conn.execute(
                    "INSERT OR REPLACE INTO folder_sync_shadow VALUES (?,?)",
                    (
                        key,
                        encode({**record, "fields": baseline, "applied_heads": record["heads"]}),
                    ),
                )
            self.conn.execute(
                """UPDATE folder_sync_config SET last_sync=?,last_error=NULL,
                pending_files=?,pending_events=? WHERE id=1""",
                (now(), pending_files, pending_events + waiting),
            )
        return self.status(user_id)

    def resolve(self, user_id: int, key: str, field: str, version: str) -> None:
        self.check_owner(user_id)
        state, _ = self.state()
        record = state.get(key)
        if not record or version not in record["heads"].get(field, []):
            raise ValueError("冲突版本已变化，请刷新后重新选择")
        event = next(e for e in self.events() if e["id"] == version)
        with self.conn:
            self.add_event(record, {field: event["patch"][field]}, record["heads"])

    def restore(self, user_id: int, key: str) -> None:
        self.check_owner(user_id)
        state, _ = self.state()
        record = state.get(key)
        if not record or not record["fields"].get("_deleted"):
            raise ValueError("该资料没有同步删除记录")
        with self.conn:
            self.add_event(record, {"_deleted": False}, record["heads"])


def run_folder_sync(
    path: Path,
    user_id: int | None = None,
    *,
    resolve: dict | None = None,
    restore: str | None = None,
):
    with sync_lock(path):
        storage = SqliteStorage(path)
        try:
            sync = FolderSync(storage)
            config = sync.config()
            if not config or not config["enabled"]:
                return None
            uid = user_id if user_id is not None else config["user_id"]
            sync.check_owner(uid)
            if not sync.conn.execute(
                "SELECT 1 FROM users WHERE id=? AND is_active=1", (uid,)
            ).fetchone():
                raise ValueError("绑定的本地账号已停用")
            if resolve or restore:
                sync.sync(uid)
                if resolve:
                    sync.resolve(uid, **resolve)
                if restore:
                    sync.restore(uid, restore)
            return sync.sync(uid)
        except Exception as exc:
            message = (
                str(exc)[:200]
                if isinstance(exc, ValueError)
                else "文件夹同步未完成，请检查目录可用性与 iCloud 下载状态"
            )
            try:
                with storage._connect() as conn:
                    conn.execute(
                        "UPDATE folder_sync_config SET last_error=? WHERE id=1", (message,)
                    )
            except sqlite3.Error:
                pass
            raise ValueError(message) from exc
        finally:
            storage.close()
