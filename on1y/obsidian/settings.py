"""Per-user Obsidian sync settings stored under data/users/<id>/."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from on1y.auth.context import get_effective_user_id
from on1y.config import get_settings
from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)

ImportMode = Literal["move", "keep", "delete"]


class ObsidianSettings(BaseModel):
    enabled: bool = False
    vault_path: str = ""
    inbox_relpath: str = "Inbox/Clippings"
    archive_relpath: str = "Inbox/Imported"
    interval_seconds: int = Field(default=60, ge=15, le=3600)
    import_mode: ImportMode = "keep"
    auto_distill: bool = True


def settings_file_path(*, user_id: int | None = None) -> Path:
    uid = user_id if user_id is not None else get_effective_user_id()
    return user_dir(uid) / "obsidian_settings.json"


def load_settings(*, user_id: int | None = None) -> ObsidianSettings:
    path = settings_file_path(user_id=user_id)
    if not path.is_file():
        return ObsidianSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Invalid Obsidian settings file: %s", path)
        return ObsidianSettings()
    if not isinstance(payload, dict):
        return ObsidianSettings()
    try:
        return ObsidianSettings.model_validate(payload)
    except Exception:
        logger.warning("Invalid Obsidian settings payload: %s", path)
        return ObsidianSettings()


def save_settings(*, user_id: int | None = None, **fields: Any) -> ObsidianSettings:
    uid = user_id if user_id is not None else get_effective_user_id()
    current = load_settings(user_id=uid)
    update: dict[str, Any] = {}
    if "enabled" in fields and fields["enabled"] is not None:
        update["enabled"] = bool(fields["enabled"])
    if "vault_path" in fields and fields["vault_path"] is not None:
        update["vault_path"] = str(fields["vault_path"]).strip()
    if "inbox_relpath" in fields and fields["inbox_relpath"] is not None:
        update["inbox_relpath"] = str(fields["inbox_relpath"]).strip() or "Inbox/Clippings"
    if "archive_relpath" in fields and fields["archive_relpath"] is not None:
        update["archive_relpath"] = str(fields["archive_relpath"]).strip() or "Inbox/Imported"
    if "interval_seconds" in fields and fields["interval_seconds"] is not None:
        interval = int(fields["interval_seconds"])
        update["interval_seconds"] = max(15, min(3600, interval))
    # Keep import readonly; retain field for backward compatibility.
    update["import_mode"] = "keep"
    if "auto_distill" in fields and fields["auto_distill"] is not None:
        update["auto_distill"] = bool(fields["auto_distill"])

    merged = current.model_copy(update=update)
    path = settings_file_path(user_id=uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return merged


def public_settings_view(*, user_id: int | None = None) -> dict[str, Any]:
    settings = load_settings(user_id=user_id)
    return settings.model_dump()


def resolve_paths(*, user_id: int | None = None) -> tuple[ObsidianSettings, Path | None, Path | None]:
    cfg = load_settings(user_id=user_id)
    if not cfg.vault_path.strip():
        return cfg, None, None
    vault = Path(cfg.vault_path).expanduser()
    inbox = (vault / cfg.inbox_relpath).resolve()
    archive = (vault / cfg.archive_relpath).resolve()
    return cfg, inbox, archive


def any_obsidian_sync_enabled() -> bool:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.user.accounts import list_sync_user_ids

    base = get_settings()
    storage = get_storage()
    try:
        user_ids = list_sync_user_ids(storage, current_user_only=True)
    finally:
        storage.close()
    if not user_ids:
        return False
    for uid in user_ids:
        cfg = load_settings(user_id=uid)
        if cfg.enabled and cfg.vault_path.strip():
            return True
    return bool(getattr(base, "obsidian_sync_enabled", False))
