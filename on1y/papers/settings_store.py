"""Per-user Paper settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from on1y.user.paths import user_dir

logger = logging.getLogger(__name__)


class PaperSettings(BaseModel):
    version: int = 3
    literature_vault_path: str = r"E:\Literature"
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
    translation_enabled: bool = False
    translation_provider: Literal["on1y_ai", "deepl"] = "on1y_ai"
    translation_source_lang: str = Field(default="en", min_length=2, max_length=20)
    translation_target_lang: str = Field(default="zh-CN", min_length=2, max_length=20)
    translation_model_override: str | None = Field(default=None, max_length=200)
    translation_api_key: str | None = Field(default=None, max_length=1000)
    translation_deepl_plan: Literal["free", "pro"] = "free"
    translation_babeldoc_executable: str | None = Field(default=None, max_length=4096)
    translation_glossary_path: str | None = Field(default=None, max_length=4096)
    translation_qps: int = Field(default=2, ge=1, le=20)
    translation_auto_enqueue: bool = True
    translation_ocr_workaround: bool = False


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
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["version"] = PaperSettings().version
        return PaperSettings.model_validate(payload)
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


def paper_settings_public_view(settings: PaperSettings) -> dict[str, Any]:
    """Return settings without exposing stored translation credentials."""
    payload = settings.model_dump()
    secret = str(settings.translation_api_key or "")
    payload["translation_api_key"] = None
    payload["translation_api_key_set"] = bool(secret)
    payload["translation_api_key_preview"] = (
        f"{secret[:3]}...{secret[-3:]}" if len(secret) >= 8 else ("configured" if secret else None)
    )
    return payload


def resolve_literature_vault(user_id: int, override: str | None = None) -> Path:
    """Resolve the configured Literature Vault without silently falling back."""
    configured = (
        override if override is not None else load_paper_settings(user_id).literature_vault_path
    )
    raw = str(configured or "").strip()
    if not raw:
        raise ValueError("\u8bf7\u5148\u9009\u62e9 Literature Vault \u6587\u4ef6\u5939")
    return Path(raw).expanduser().resolve(strict=False)


def literature_vault_status(user_id: int, override: str | None = None) -> dict[str, Any]:
    path = resolve_literature_vault(user_id, override)
    drive_available = path.drive == "" or Path(path.anchor).exists()
    return {
        "path": str(path),
        "exists": path.is_dir(),
        "drive_available": drive_available,
        "initialized": (path / "_system" / "papers.db").is_file(),
    }


def resolve_paper_cache_dir(user_id: int, override: str | None = None) -> Path:
    path = (
        Path(override).expanduser()
        if override and override.strip()
        else user_dir(user_id) / "papers" / "cache"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path
