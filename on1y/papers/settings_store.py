"""Per-user Paper settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)


class PaperSettings(BaseModel):
    version: int = 1
    cache_dir: str | None = None
    folder_sync_enabled: bool = False
    zotero_enabled: bool = False
    zotero_mode: Literal["local", "web"] = "local"
    zotero_base_url: str = "http://localhost:23119/api"
    zotero_library_type: Literal["users", "groups"] = "users"
    zotero_library_id: str = "0"
    zotero_api_key: str | None = Field(default=None, max_length=500)
    zotero_collection_key: str | None = Field(default=None, max_length=100)
    zotero_download_pdfs: bool = True
    pdf_open_mode: Literal["zotero", "system", "custom"] = "zotero"
    pdf_application_path: str | None = Field(default=None, max_length=4096)


def paper_settings_path(user_id: int) -> Path:
    path = user_dir(user_id) / "papers" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_paper_settings(user_id: int) -> PaperSettings:
    path = paper_settings_path(user_id)
    if not path.is_file():
        settings = PaperSettings()
        save_paper_settings(user_id, settings)
        return settings
    try:
        return PaperSettings.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.warning("Invalid paper settings %s; resetting defaults", path)
        settings = PaperSettings()
        save_paper_settings(user_id, settings)
        return settings


def save_paper_settings(user_id: int, settings: PaperSettings) -> None:
    path = paper_settings_path(user_id)
    path.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_paper_cache_dir(user_id: int, override: str | None = None) -> Path:
    path = (
        Path(override).expanduser()
        if override and override.strip()
        else user_dir(user_id) / "papers" / "cache"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path
