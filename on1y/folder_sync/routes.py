"""Authenticated controls for an iCloud or other locally synchronized folder."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import get_effective_user_id
from on1y.config import get_settings
from on1y.device_sync.client import sync_lock
from on1y.folder_sync.engine import FolderSync, run_folder_sync


class FolderConfig(BaseModel):
    folder: str = Field(max_length=4096)
    enabled: bool = False
    create: bool = False


class Resolution(BaseModel):
    key: str = Field(max_length=100)
    field: str = Field(max_length=300)
    version: str = Field(max_length=100)


class Restoration(BaseModel):
    key: str = Field(max_length=100)


def register_folder_sync_routes(app: FastAPI) -> None:
    @app.get("/api/folder-sync")
    def status():
        storage = get_storage()
        try:
            with sync_lock(storage.db_path):
                return FolderSync(storage).status(get_effective_user_id())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            storage.close()

    @app.post("/api/folder-sync")
    def configure(body: FolderConfig):
        storage = get_storage()
        try:
            with sync_lock(storage.db_path):
                sync = FolderSync(storage)
                uid = get_effective_user_id()
                sync.configure(uid, body.folder, body.enabled, create=body.create)
                return sync.status(uid)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            storage.close()

    def execute(**kwargs):
        try:
            result = run_folder_sync(get_settings().db_path, get_effective_user_id(), **kwargs)
            if result is None:
                raise ValueError("请先开启文件夹同步")
            return result
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/folder-sync/run")
    def run():
        return execute()

    @app.post("/api/folder-sync/resolve")
    def resolve(body: Resolution):
        return execute(resolve=body.model_dump())

    @app.post("/api/folder-sync/restore")
    def restore(body: Restoration):
        return execute(restore=body.key)
