"""Per-user RSS feeds.yaml path resolution."""

from __future__ import annotations

from pathlib import Path

from on1y.auth.context import get_effective_user_id
from on1y.config import Settings, get_settings
from on1y.user.paths import user_feeds_path


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
