"""Authenticated desktop controls and an opt-in background worker."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import get_effective_user_id
from on1y.config import get_settings
from on1y.device_sync.client import DeviceSync, run_sync, sync_lock


class SyncConfig(BaseModel):
    server_url: str = Field(default="", max_length=2048)
    key: str = Field(default="", max_length=512)
    enabled: bool = False


class ResolveConflict(BaseModel):
    choice: Literal["current", "incoming"]


@asynccontextmanager
async def sync_lifespan(app: FastAPI):
    path = get_settings().db_path
    stop = threading.Event()

    def worker() -> None:
        # No database creation or network work until the user has opened the app.
        while not stop.wait(30):
            if not path.is_file():
                continue
            try:
                run_sync(path)
            except Exception:
                # run_sync persists a sanitized error for the settings UI.
                continue

    thread = threading.Thread(target=worker, name="on1y-device-sync", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()


def register_device_sync_routes(app: FastAPI) -> None:
    @app.get("/api/device-sync")
    def status():
        storage = get_storage()
        try:
            with sync_lock(storage.db_path):
                return DeviceSync(storage).status(get_effective_user_id())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            storage.close()

    @app.post("/api/device-sync")
    def configure(body: SyncConfig):
        storage = get_storage()
        try:
            with sync_lock(storage.db_path):
                sync = DeviceSync(storage)
                uid = get_effective_user_id()
                sync.configure(uid, body.server_url, body.key, body.enabled)
                return sync.status(uid)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            storage.close()

    @app.post("/api/device-sync/run")
    def run():
        try:
            result = run_sync(get_settings().db_path, get_effective_user_id())
            if result is None:
                raise ValueError("请先开启跨设备同步")
            return result
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/device-sync/conflicts/{conflict_id}/resolve")
    def resolve(conflict_id: str, body: ResolveConflict):
        from uuid import UUID

        try:
            UUID(conflict_id)
            result = run_sync(
                get_settings().db_path,
                get_effective_user_id(),
                resolution=(conflict_id, body.choice),
            )
            if result is None:
                raise ValueError("请先开启跨设备同步")
            return result
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
