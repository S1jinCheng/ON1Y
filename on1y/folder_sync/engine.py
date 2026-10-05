"""File transport with durable local operations and convergent field versions.

Only immutable JSON events and content-addressed attachments enter the cloud.
Each device has its own SQLite database. Parent sets, not wall clocks or file
arrival order, detect concurrency. Missing parents wait for a later cloud pass.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
from functools import lru_cache
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
from on1y.folder_sync.protocol import MAX_EVENT_BYTES, VERSION, Event, LiteratureSeed

MANIFEST = "on1y-library.json"


@lru_cache(maxsize=1)
def suggested_folder() -> str:
    if sys.platform == "darwin":
        root = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
    else:
        candidates = [Path.home() / "iCloudDrive", Path.home() / "iCloud Drive"]
        if sys.platform == "win32":
            drives = (
                os.listdrives()
                if hasattr(os, "listdrives")
                else [
                    f"{chr(letter)}:/"
                    for letter in range(ord("A"), ord("Z") + 1)
                    if Path(f"{chr(letter)}:/").is_dir()
                ]
            )
            for drive in drives:
                volume = Path(drive)
                candidates.extend(
                    (
                        volume / "iCloudDrive",
                        volume / "iCloud Drive",
                        volume / "iCloud" / "iCloudDrive",
                        volume / "iCloud" / "iCloud Drive",
                    )
                )
        root = next((candidate for candidate in candidates if candidate.is_dir()), None)
    return str(root / "On1y" / "Library") if root is not None and root.is_dir() else ""


class FolderSync:
    def __init__(self, storage: SqliteStorage):
        self.storage = storage
        self.conn = storage._connect()
        self.cache = storage.db_path.parent / "folder-sync-files"
        self.staging = storage.db_path.parent / "folder-sync-staging"
        self._last_clock: int | None = None
        self._captured_tree_scan = None
        self._joining_pristine_tree = False
        self._cloud_tree_history = False
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS folder_sync_config (
                id INTEGER PRIMARY KEY CHECK(id=1), user_id INTEGER NOT NULL,
                device_id TEXT NOT NULL, folder TEXT NOT NULL, library_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0, last_sync TEXT, last_error TEXT,
                pending_files INTEGER NOT NULL DEFAULT 0,
                pending_events INTEGER NOT NULL DEFAULT 0,
                literature_files_enabled INTEGER NOT NULL DEFAULT 0,
                literature_vault_path TEXT NOT NULL DEFAULT '',
                literature_files INTEGER NOT NULL DEFAULT 0,
                literature_excluded INTEGER NOT NULL DEFAULT 0,
                literature_last_scan TEXT,
                literature_initialized INTEGER NOT NULL DEFAULT 0,
                literature_creator INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS folder_sync_mapping (
                key TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
                local_id INTEGER NOT NULL, identity TEXT NOT NULL,
                UNIQUE(user_id,kind,local_id));
            CREATE TABLE IF NOT EXISTS folder_sync_events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS folder_sync_shadow (
                key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS folder_sync_file_cache (
                path TEXT PRIMARY KEY, signature TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS folder_sync_literature_outbox (
                user_id INTEGER NOT NULL, paper_id INTEGER NOT NULL,
                literature_paper_id TEXT NOT NULL,
                field TEXT NOT NULL CHECK(field IN ('status','importance')),
                data TEXT NOT NULL,
                PRIMARY KEY(user_id,paper_id,field));
        """)
        # Existing preview libraries predate the Literature tree columns.
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(folder_sync_config)")
        }
        additions = {
            "literature_files_enabled": "INTEGER NOT NULL DEFAULT 0",
            "literature_vault_path": "TEXT NOT NULL DEFAULT ''",
            "literature_files": "INTEGER NOT NULL DEFAULT 0",
            "literature_excluded": "INTEGER NOT NULL DEFAULT 0",
            "literature_last_scan": "TEXT",
            "literature_initialized": "INTEGER NOT NULL DEFAULT 0",
            "literature_creator": "INTEGER NOT NULL DEFAULT 0",
        }
        with self.conn:
            for name, declaration in additions.items():
                if name not in columns:
                    self.conn.execute(
                        f"ALTER TABLE folder_sync_config ADD COLUMN {name} {declaration}"
                    )

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

    def configure(
        self,
        user_id: int,
        folder: str,
        enabled: bool,
        *,
        create: bool = False,
        literature_files: bool | None = None,
    ) -> None:
        self.check_owner(user_id)
        old = self.config()
        if not self.conn.execute(
            "SELECT 1 FROM users WHERE id=? AND is_active=1", (user_id,)
        ).fetchone():
            raise ValueError("请先登录有效的本地账号")
        if enabled:
            self.check_relay()
        tree_enabled = (
            bool(old.get("literature_files_enabled"))
            if literature_files is None and old
            else bool(literature_files)
        )
        if literature_files is True and not enabled:
            raise ValueError("Literature 文件树同步需要先开启文件夹自动同步")
        if not enabled:
            tree_enabled = False
        if old and not enabled and folder == old["folder"]:
            with self.conn:
                self.conn.execute(
                    """UPDATE folder_sync_config SET enabled=0,
                    literature_files_enabled=0 WHERE id=1"""
                )
            return
        root = Path(folder).expanduser()
        if not folder.strip() or not root.is_absolute():
            raise ValueError("请选择资料库文件夹的完整路径")
        root = root.resolve()
        db_dir = self.storage.db_path.parent.resolve()
        if db_dir.is_relative_to(root) or root.is_relative_to(db_dir):
            raise ValueError("同步目录必须与 On1y 本机数据库目录分开")
        from on1y.papers.settings_store import resolve_literature_vault

        vault = resolve_literature_vault(user_id).resolve(strict=False)
        if root == vault or root.is_relative_to(vault) or vault.is_relative_to(root):
            raise ValueError("同步资料库文件夹必须与 Literature Vault 分开，不能互相包含")
        if tree_enabled and not vault.is_dir():
            raise ValueError("Literature Vault 不可用，请先在 Paper 设置中选择本机文件夹")
        if tree_enabled:
            self._validate_literature_marker(vault)
        if not root.parent.is_dir():
            raise ValueError("上级目录不存在，请先启用 iCloud Drive 或选择现有目录")
        manifest = safe_child(root, MANIFEST)
        created_manifest = False
        if not manifest.is_file():
            if old or not create:
                raise ValueError("资料库标识尚未下载，请等待 iCloud 完成；新资料库请选创建")
            if root.exists() and any(root.iterdir()):
                raise ValueError("请使用空文件夹创建资料库，避免混入其他文件")
            root.mkdir(exist_ok=True)
            library_id = str(uuid4())
            atomic_write(manifest, encode({"version": VERSION, "library_id": library_id}).encode())
            created_manifest = True
        info = read_json(manifest)
        if info.get("version") != VERSION:
            raise ValueError("资料库版本不兼容，请更新两端 On1y")
        library_id = str(UUID(info["library_id"]))
        if old and old["library_id"] != library_id:
            raise ValueError("此设备已绑定其他资料库，不能直接切换以免混合数据")
        old_vault = (
            Path(str(old.get("literature_vault_path") or "")).resolve(strict=False)
            if old and str(old.get("literature_vault_path") or "").strip()
            else None
        )
        vault_changed = old_vault is not None and old_vault != vault
        literature_creator = (
            bool(old.get("literature_creator"))
            if old and not vault_changed
            else created_manifest
        )
        if (
            tree_enabled
            and not literature_creator
            and (vault_changed or not bool(old and old.get("literature_files_enabled")))
            and self._vault_has_catalog_data(vault)
        ):
            # Upgrade path for the Windows device that created an older
            # protocol library before the tree-sync columns existed. A truly
            # new receiver has an initialized but empty local catalog.
            literature_creator = True
        with self.conn:
            stale_tree_keys = []
            stale_cache_paths = []
            if vault_changed:
                stale_tree_keys = [
                    row["key"]
                    for row in self.conn.execute("SELECT key,data FROM folder_sync_shadow")
                    if json.loads(row["data"]).get("kind") == "literature_file"
                ]
                for row in self.conn.execute("SELECT path FROM folder_sync_file_cache"):
                    try:
                        if Path(row["path"]).resolve(strict=False).is_relative_to(old_vault):
                            stale_cache_paths.append(row["path"])
                    except (OSError, ValueError):
                        continue
            self.conn.execute(
                """
                INSERT INTO folder_sync_config(
                    id,user_id,device_id,folder,library_id,enabled,
                    literature_files_enabled,literature_vault_path,literature_creator)
                VALUES (1,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                folder=excluded.folder,enabled=excluded.enabled,
                literature_files_enabled=excluded.literature_files_enabled,
                literature_creator=CASE
                    WHEN folder_sync_config.literature_vault_path
                         = excluded.literature_vault_path
                         AND folder_sync_config.literature_creator=1 THEN 1
                    ELSE excluded.literature_creator END,
                literature_initialized=CASE
                    WHEN folder_sync_config.literature_vault_path
                         = excluded.literature_vault_path
                    THEN folder_sync_config.literature_initialized ELSE 0 END,
                literature_vault_path=excluded.literature_vault_path,last_error=NULL
            """,
                (
                    user_id,
                    old["device_id"] if old else str(uuid4()),
                    str(root),
                    library_id,
                    int(enabled),
                    int(tree_enabled),
                    str(vault),
                    int(literature_creator),
                ),
            )
            self.conn.executemany(
                "DELETE FROM folder_sync_shadow WHERE key=?",
                ((key,) for key in stale_tree_keys),
            )
            self.conn.executemany(
                "DELETE FROM folder_sync_file_cache WHERE path=?",
                ((path,) for path in stale_cache_paths),
            )

    def events(self) -> list[dict]:
        return [
            json.loads(row[0]) for row in self.conn.execute("SELECT data FROM folder_sync_events")
        ]

    def _literature_root(self, user_id: int, config: dict | None = None) -> Path:
        from on1y.papers.settings_store import resolve_literature_vault

        config = config or self.config() or {}
        current = resolve_literature_vault(user_id).resolve(strict=False)
        configured = str(config.get("literature_vault_path") or "").strip()
        if configured and current != Path(configured).expanduser().resolve(strict=False):
            raise ValueError(
                "Literature Vault 路径已改变，请先重新保存 iCloud 资料库同步设置"
            )
        if not current.is_dir():
            raise ValueError("Literature Vault 不可用，已暂停文件树同步")
        self._validate_literature_marker(current)
        return current

    @staticmethod
    def _validate_literature_marker(root: Path) -> None:
        """Refuse an empty remount or redirected database as the live Vault."""
        marker = root / "_system" / "papers.db"
        try:
            info = marker.lstat()
        except OSError as exc:
            raise ValueError(
                "Literature Vault 尚未初始化或暂时不可用，已暂停文件树同步"
            ) from exc
        attributes = int(getattr(info, "st_file_attributes", 0))
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or attributes & 0x400
        ):
            raise ValueError("Literature Vault 标识不是安全的本机文件，已暂停同步")

    @staticmethod
    def _vault_has_catalog_data(root: Path) -> bool:
        marker = root / "_system" / "papers.db"
        try:
            uri = marker.resolve(strict=True).as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=2) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if not {"papers", "batches"} <= tables:
                    return False
                papers = conn.execute("SELECT 1 FROM papers LIMIT 1").fetchone()
                batches = conn.execute("SELECT 1 FROM batches LIMIT 1").fetchone()
                return bool(papers or batches)
        except (OSError, sqlite3.Error) as exc:
            raise ValueError("无法读取 Literature 本机目录，已暂停文件树同步") from exc

    def _tree_shadows(self) -> dict[str, dict]:
        result = {}
        for row in self.conn.execute("SELECT key,data FROM folder_sync_shadow"):
            record = json.loads(row["data"])
            if record.get("kind") == "literature_file":
                result[row["key"]] = record
        return result

    def _scan_tree(self, user_id: int, previous: dict[str, dict] | None = None):
        config = self.config() or {}
        if not config.get("literature_files_enabled"):
            return None
        from on1y.folder_sync.literature_tree import scan_literature_tree

        return scan_literature_tree(
            self.conn,
            self._literature_root(user_id, config),
            self.staging,
            previous=previous,
        )

    def _store_tree_cache(self, scan) -> None:
        if scan is None:
            return
        for update in scan.cache_updates:
            self.conn.execute(
                "INSERT OR REPLACE INTO folder_sync_file_cache VALUES (?,?,?)",
                (update.path, update.signature, encode(update.data)),
            )

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
        literature_remote_files = 0
        for key, record in state.items():
            file_version = record["fields"].get("file")
            title = (
                (file_version or {}).get("path")
                or record["fields"].get("library/title")
                or record["fields"].get("raw_title")
                or record["identity"]
            )
            conflicts.extend({"key": key, "title": title, **c} for c in record["conflicts"])
            tree_deleted = record["kind"] == "literature_file" and bool(
                file_version and file_version.get("deleted")
            )
            if record["kind"] == "literature_file" and file_version and not tree_deleted:
                literature_remote_files += 1
            if record["fields"].get("_deleted") or tree_deleted:
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
            "literature_files_enabled": bool(config.get("literature_files_enabled")),
            "literature_vault": config.get("literature_vault_path", ""),
            # This is the last successful local Vault scan, not a claim that
            # iCloud delivered every protocol object to this device.
            "literature_files": config.get("literature_files", 0),
            "literature_remote_files": literature_remote_files,
            "literature_excluded": config.get("literature_excluded", 0),
            "literature_last_scan": config.get("literature_last_scan"),
            "conflicts": conflicts,
            "deleted": deleted,
        }

    def add_event(self, record: dict, patch: dict, heads: dict) -> str:
        config = self.config()
        if self._last_clock is None:
            self._last_clock = max((e["clock"] for e in self.events()), default=0)
        self._last_clock += 1
        event = Event(
            library_id=config["library_id"],
            id=uuid4(),
            device_id=config["device_id"],
            clock=self._last_clock,
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

    def _publish_literature_seed(self, root: Path, config: dict) -> bool:
        """Publish one immutable completeness barrier after all creator data exists."""
        seeds_dir = safe_child(root, "literature-seeds")
        seeds_dir.mkdir(exist_ok=True)
        target = safe_child(seeds_dir, config["device_id"] + ".json")
        if target.exists():
            if not available(target):
                return False
            seed = LiteratureSeed.model_validate(read_json(target))
            if (
                str(seed.library_id) != config["library_id"]
                or str(seed.device_id) != config["device_id"]
            ):
                raise ValueError("Literature 初始快照标记被改写，已停止同步")
            return True

        events = [
            event
            for event in self.events()
            if event["kind"] == "literature_file"
            and event["device_id"] == config["device_id"]
        ]
        if not events:
            return False
        objects: dict[str, dict] = {}
        for event in events:
            event_path = safe_child(root, "literature-events", event["id"] + ".json")
            if not available(event_path) or read_json(event_path) != event:
                return False
            blob = event["patch"]["file"]["blob"]
            object_path = safe_child(root, "objects", blob["sha256"])
            if not available(object_path) or object_path.stat().st_size != blob["size"]:
                return False
            objects[blob["sha256"]] = blob
        seed = LiteratureSeed(
            library_id=config["library_id"],
            device_id=config["device_id"],
            event_ids=sorted(event["id"] for event in events),
            objects=[objects[sha] for sha in sorted(objects)],
        ).model_dump(mode="json")
        atomic_write(target, encode(seed).encode())
        return True

    @staticmethod
    def _literature_seed_ready(root: Path, library_id: str) -> tuple[bool, int]:
        """Return true only when a complete creator snapshot is locally hydrated."""
        seeds_dir = safe_child(root, "literature-seeds")
        seeds_dir.mkdir(exist_ok=True)
        waiting = 0
        for path in seeds_dir.iterdir():
            if path.name.endswith(".json.icloud"):
                waiting += 1
                continue
            if path.name.startswith(".") or path.suffix != ".json":
                continue
            safe_child(seeds_dir, path.name)
            if not available(path):
                waiting += 1
                continue
            try:
                seed = LiteratureSeed.model_validate(read_json(path))
            except (FileNotFoundError, json.JSONDecodeError):
                waiting += 1
                continue
            if str(seed.library_id) != library_id:
                raise ValueError("文件夹中混入其他资料库的 Literature 快照，已停止")
            if path.name != f"{seed.device_id}.json":
                raise ValueError("Literature 初始快照标记名称不正确，已停止")

            complete = True
            for event_id in seed.event_ids:
                event_path = safe_child(root, "literature-events", f"{event_id}.json")
                legacy_path = safe_child(root, "events", f"{event_id}.json")
                selected = event_path if available(event_path) else legacy_path
                if not available(selected):
                    complete = False
                    break
                event = Event.model_validate(read_json(selected))
                if (
                    event.id != event_id
                    or event.kind != "literature_file"
                    or event.library_id != seed.library_id
                    or event.device_id != seed.device_id
                ):
                    raise ValueError("Literature 初始快照引用了无效记录，已停止")
            if not complete:
                continue
            for blob in seed.objects:
                object_path = safe_child(root, "objects", blob.sha256)
                if not available(object_path) or object_path.stat().st_size != blob.size:
                    complete = False
                    break
            if complete:
                return True, waiting
        return False, waiting

    def capture(self, user_id: int) -> dict:
        # Compute the existing maximum once, then allocate clocks in memory.
        # Re-reading and decoding every prior event for every new record makes
        # a first full-library capture quadratic on several thousand items.
        self._last_clock = None
        config = self.config() or {}
        if config.get("literature_files_enabled") and config.get("literature_creator"):
            from on1y.papers.literature import LiteratureVault
            from on1y.papers.literature_catalog import export_catalog_sidecars

            vault_root = self._literature_root(user_id, config)
            export_catalog_sidecars(
                LiteratureVault(user_id, vault_root),
                library_id=config["library_id"],
                authoritative=True,
            )
        # Hashing a multi-gigabyte Vault must not hold SQLite's write lock.
        self._joining_pristine_tree = False
        tree_scan = self._scan_tree(
            user_id,
            previous=self._tree_shadows(),
        )
        self._captured_tree_scan = tree_scan
        if (
            tree_scan is not None
            and not config.get("literature_initialized")
            and not config.get("literature_creator")
        ):
            from on1y.folder_sync.literature_tree import is_join_baseline

            known_state, _pending = self.state()
            self._joining_pristine_tree = is_join_baseline(tree_scan, known_state)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            local = records.snapshot(self.conn, user_id, self.staging)
            if tree_scan is not None and not self._joining_pristine_tree:
                local.update(tree_scan.records)
            if tree_scan is not None:
                self._store_tree_cache(tree_scan)
            previous = {
                r[0]: json.loads(r[1])
                for r in self.conn.execute("SELECT * FROM folder_sync_shadow")
            }
            for key, old in previous.items():
                if key not in local:
                    # Disabled tree sync is a pause, never a request to delete
                    # every remote Literature file. The tree scanner produces
                    # explicit tombstones only after this device is initialized.
                    if old.get("kind") == "literature_file":
                        continue
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
        events_dir = safe_child(root, "events")
        literature_events_dir = safe_child(root, "literature-events")
        events_dir.mkdir(exist_ok=True)
        literature_events_dir.mkdir(exist_ok=True)
        captured = self.capture(user_id)
        checked_blobs = set()
        for event in self.events():
            blob = event["patch"].get("attachment")
            if event["kind"] == "literature_file" and event["patch"].get("file"):
                blob = event["patch"]["file"]["blob"]
            if blob:
                sha = blob["sha256"]
                if sha not in checked_blobs:
                    object_path = safe_child(root, "objects", sha)
                    cached = self.conn.execute(
                        "SELECT signature FROM folder_sync_file_cache WHERE path=?",
                        (str(object_path),),
                    ).fetchone()
                    if not (
                        available(object_path) and cached and cached[0] == signature(object_path)
                    ) and publish_blob(self.staging, root, blob):
                        with self.conn:
                            self.conn.execute(
                                "INSERT OR REPLACE INTO folder_sync_file_cache VALUES (?,?,?)",
                                (str(object_path), signature(object_path), encode(blob)),
                            )
                    checked_blobs.add(sha)
            directory = "literature-events" if event["kind"] == "literature_file" else "events"
            target = safe_child(root, directory, event["id"] + ".json")
            payload = encode(event).encode()
            if target.exists():
                if read_json(target) != event:
                    raise ValueError("同步记录被改写，已停止")
            else:
                atomic_write(target, payload)
        tree_enabled = bool(config.get("literature_files_enabled"))
        creator_seed_published = True
        if tree_enabled:
            if config.get("literature_creator"):
                creator_seed_published = self._publish_literature_seed(root, config)
            if not config.get("literature_initialized") and not config.get(
                "literature_creator"
            ):
                seed_ready, seed_waiting = self._literature_seed_ready(
                    root, config["library_id"]
                )
            else:
                seed_ready, seed_waiting = True, 0
        else:
            seed_ready, seed_waiting = False, 0
        incoming_by_id: dict[str, dict] = {}
        waiting = seed_waiting
        literature_waiting = seed_waiting
        for directory, directory_path in (
            ("events", events_dir),
            ("literature-events", literature_events_dir),
        ):
            for path in directory_path.iterdir():
                if path.name.endswith(".json.icloud"):
                    waiting += 1
                    literature_waiting += int(directory == "literature-events")
                    continue
                if path.name.startswith(".") or path.suffix != ".json":
                    continue
                safe_child(root, directory, path.name)
                if not available(path):
                    waiting += 1
                    literature_waiting += int(directory == "literature-events")
                    continue
                try:
                    event = Event.model_validate(read_json(path)).model_dump(mode="json")
                except (FileNotFoundError, json.JSONDecodeError):
                    waiting += 1
                    literature_waiting += int(directory == "literature-events")
                    continue
                if event["library_id"] != config["library_id"]:
                    raise ValueError("文件夹中混入其他资料库的记录，已停止")
                duplicate = incoming_by_id.get(event["id"])
                if duplicate is not None and duplicate != event:
                    raise ValueError("同一同步记录出现不同内容，已停止")
                old = self.conn.execute(
                    "SELECT data FROM folder_sync_events WHERE id=?", (event["id"],)
                ).fetchone()
                if old and json.loads(old[0]) != event:
                    raise ValueError("同一同步记录出现不同内容，已停止")
                incoming_by_id[event["id"]] = event
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            for event in incoming_by_id.values():
                self.conn.execute(
                    "INSERT OR IGNORE INTO folder_sync_events VALUES (?,?)",
                    (event["id"], encode(event)),
                )
        # Incoming devices may have advanced the Lamport clock. Any later
        # resolve/restore operation must recompute from the combined event set.
        self._last_clock = None
        state, pending_events = self.state()
        paths = {}
        pending_files = 0
        tree_pending_keys: set[str] = set()
        for key, record in state.items():
            if record["fields"].get("_deleted"):
                continue
            if record["kind"] == "literature_file" and not tree_enabled:
                # Tree files are explicitly opt-in. Devices that only want
                # metadata and linked attachments must not download the Vault.
                continue
            attachment = record["fields"].get("attachment")
            if record["kind"] == "literature_file":
                version = record["fields"].get("file") or {}
                attachment = None if version.get("deleted") else version.get("blob")
            if attachment:
                if record["kind"] == "literature_file":
                    path = safe_child(root, "objects", attachment["sha256"])
                    if not available(path):
                        path = None
                        tree_pending_keys.add(key)
                    elif path.stat().st_size != attachment["size"]:
                        raise ValueError("Literature 对象尚未完整下载，请等待 iCloud")
                else:
                    path = receive_blob(root, self.cache, key, attachment, self.conn)
                if path:
                    paths[key] = path
                else:
                    pending_files += 1

        tree_current = None
        tree_normalized = None
        tree_protected: dict[str, dict] = {}
        tree_commit: set[str] = set()
        tree_retry: set[str] = set()
        tree_conflicts: set[str] = set()
        join_blocked = False
        if tree_enabled:
            from on1y.folder_sync.literature_tree import apply_literature_version

            captured_tree = {
                key: record
                for key, record in captured.items()
                if record["kind"] == "literature_file"
            }
            tree_current = self._scan_tree(user_id, previous=captured_tree)
            with self.conn:
                self._store_tree_cache(tree_current)
            tree_shadows = self._tree_shadows()
            vault = self._literature_root(user_id, config)
            apply_cache = []
            remote_tree = [
                (key, record)
                for key, record in state.items()
                if record["kind"] == "literature_file"
            ]
            join_blocked = self._joining_pristine_tree and (
                bool(tree_pending_keys)
                or bool(pending_events)
                or bool(literature_waiting)
                or any(
                    any(conflict["field"] == "file" for conflict in record["conflicts"])
                    for _key, record in remote_tree
                )
            )
            if (
                not config.get("literature_initialized")
                and not config.get("literature_creator")
                and not seed_ready
            ):
                join_blocked = True
            if join_blocked:
                tree_retry.update(key for key, _record in remote_tree)
            for key, record in remote_tree:
                before = (
                    self._captured_tree_scan.records.get(key, {}).get("fields", {})
                    if self._captured_tree_scan is not None
                    else {}
                )
                live_record = tree_current.records.get(key)
                live = live_record.get("fields", {}) if live_record else {}
                changes = {
                    field: live.get(field)
                    for field in set(before) | set(live)
                    if live.get(field) != before.get(field)
                }
                tree_protected[key] = changes
                if join_blocked:
                    if any(conflict["field"] == "file" for conflict in record["conflicts"]):
                        tree_conflicts.add(key)
                    continue
                if changes:
                    # A write after the initial scan becomes a new event on the
                    # next pass; never overwrite it with an incoming winner.
                    tree_commit.add(key)
                    continue
                if any(conflict["field"] == "file" for conflict in record["conflicts"]):
                    # Do not materialize an arbitrary winner. Both immutable
                    # blobs remain available until the user resolves the head.
                    tree_conflicts.add(key)
                    tree_commit.add(key)
                    continue
                if record["heads"] == tree_shadows.get(key, {}).get("applied_heads"):
                    tree_commit.add(key)
                    continue
                desired = record["fields"].get("file")
                if not desired:
                    tree_retry.add(key)
                    continue
                if live.get("file") == desired:
                    tree_commit.add(key)
                    continue
                expected = tree_current.observations.get(record["identity"])
                source = None if desired.get("deleted") else paths.get(key)
                result = apply_literature_version(vault, desired, source, expected)
                if result.applied:
                    tree_commit.add(key)
                    if result.cache_update is not None:
                        apply_cache.append(result.cache_update)
                else:
                    tree_retry.add(key)
            if apply_cache:
                with self.conn:
                    for update in apply_cache:
                        self.conn.execute(
                            "INSERT OR REPLACE INTO folder_sync_file_cache VALUES (?,?,?)",
                            (update.path, update.signature, encode(update.data)),
                        )
            # A second stat/cache scan describes what actually reached disk.
            tree_state = {
                key: record
                for key, record in state.items()
                if record["kind"] == "literature_file"
            }
            tree_normalized = self._scan_tree(user_id, previous=tree_state)
            for key, record in tree_state.items():
                if key not in tree_commit or key in tree_conflicts:
                    continue
                actual = tree_normalized.records.get(key, {}).get("fields", {}).get("file")
                if actual != record["fields"].get("file"):
                    # A local edit landed after apply but before the final
                    # scan. Keep the remote head unapplied so the next capture
                    # publishes the local edit instead of absorbing it.
                    tree_retry.add(key)
            if not tree_retry and not tree_conflicts and not join_blocked:
                from on1y.papers.literature import LiteratureVault
                from on1y.papers.literature_catalog import reconcile_catalog_sidecars

                reconcile_catalog_sidecars(
                    LiteratureVault(user_id, vault),
                    library_id=config["library_id"],
                )
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current = records.snapshot(self.conn, user_id, self.staging)
            if tree_current is not None:
                current.update(tree_current.records)
                self._store_tree_cache(tree_normalized)
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
                if record["kind"] == "literature_file":
                    protected[key] = tree_protected.get(key, {})
                    continue
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
            if tree_normalized is not None:
                normalized.update(tree_normalized.records)
            for key, record in state.items():
                if record["kind"] == "literature_file" and (
                    not tree_enabled or key not in tree_commit or key in tree_retry
                ):
                    continue
                if record["kind"] == "literature_file" and key not in tree_conflicts:
                    # The shadow describes the cloud head actually accepted,
                    # not a third-scan edit made immediately after apply. Such
                    # an edit must differ on the next capture and become its
                    # own event instead of being silently absorbed.
                    baseline = dict(record["fields"])
                else:
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
            if tree_normalized is None:
                self.conn.execute(
                    """UPDATE folder_sync_config SET last_sync=?,last_error=NULL,
                    pending_files=?,pending_events=? WHERE id=1""",
                    (now(), pending_files, pending_events + waiting),
                )
            else:
                ready = (
                    not tree_retry
                    and not tree_conflicts
                    and not join_blocked
                    and creator_seed_published
                )
                self.conn.execute(
                    """UPDATE folder_sync_config SET last_sync=?,last_error=NULL,
                    pending_files=?,pending_events=?,literature_files=?,
                    literature_excluded=?,literature_last_scan=?,
                    literature_initialized=CASE WHEN literature_initialized=1 OR ? THEN 1 ELSE 0 END
                    WHERE id=1""",
                    (
                        now(),
                        pending_files,
                        pending_events + waiting,
                        tree_normalized.stats.files,
                        tree_normalized.stats.excluded,
                        now(),
                        int(ready),
                    ),
                )
        records.drain_literature_outbox(self.conn, user_id)
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
        tree_version = record["fields"].get("file") if record else None
        tree_deleted = bool(
            record
            and record["kind"] == "literature_file"
            and tree_version
            and tree_version.get("deleted")
        )
        if not record or not (record["fields"].get("_deleted") or tree_deleted):
            raise ValueError("该资料没有同步删除记录")
        with self.conn:
            if tree_deleted:
                self.add_event(
                    record,
                    {"file": {**tree_version, "deleted": False}},
                    record["heads"],
                )
            else:
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
