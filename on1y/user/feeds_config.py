"""Per-user RSS feeds.yaml path resolution."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from on1y.auth.context import get_effective_user_id
from on1y.config import Settings, get_settings
from on1y.user.paths import user_feeds_path

logger = logging.getLogger(__name__)


def resolve_feeds_config_path(
    settings: Settings | None = None,
    *,
    user_id: int | None = None,
) -> Path:
    """Per-user feeds at data/users/<id>/feeds.yaml; legacy config/feeds.yaml only for user 1."""
    settings = settings or get_settings()
    uid = user_id if user_id is not None else get_effective_user_id()
    per_user = user_feeds_path(uid)
    if per_user.is_file():
        return per_user
    if uid == 1 and settings.rss_config_path.is_file():
        return settings.rss_config_path
    return per_user


def ensure_user_feeds_config(
    settings: Settings | None = None,
    *,
    user_id: int | None = None,
) -> Path:
    """
    Ensure data/users/<id>/feeds.yaml exists.

    For user 1, copy legacy config/feeds.yaml once so subscription refresh does not keep
    writing into the shared repo config file.
    """
    settings = settings or get_settings()
    uid = user_id if user_id is not None else get_effective_user_id()
    per_user = user_feeds_path(uid)
    if per_user.is_file():
        return per_user
    if uid == 1 and settings.rss_config_path.is_file():
        per_user.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(settings.rss_config_path, per_user)
        logger.info("Seeded per-user feeds from %s -> %s", settings.rss_config_path, per_user)
    return per_user
