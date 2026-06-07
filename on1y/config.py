"""Application settings loaded from environment and optional .env file."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Keep in sync with on1y.extract.subtitles.DEFAULT_SUBTITLE_LANGS (no import — avoids cycle)
_DEFAULT_YTDLP_SUB_LANGS = (
    "zh-Hans,zh-CN,zh-Hant,zh-TW,zh,ai-zh,cmn,chi,en-orig,en-US,en-GB,en,ai-en"
)

def resolve_project_root() -> Path:
    """App install root (sources, frontend/out, sql). Set ON1Y_ROOT in packaged desktop builds."""
    raw = os.environ.get("ON1Y_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = resolve_project_root()


def _settings_env_files() -> tuple[str, ...]:
    paths: list[str] = []
    explicit = os.environ.get("ON1Y_ENV_FILE", "").strip()
    if explicit:
        paths.append(explicit)
    paths.append(str(PROJECT_ROOT / ".env"))
    data_parent = os.environ.get("ON1Y_DATA_DIR", "").strip()
    if data_parent:
        parent_env = Path(data_parent).expanduser().resolve().parent / ".env"
        paths.append(str(parent_env))
    return tuple(dict.fromkeys(paths))


class Settings(BaseSettings):
    """Central configuration; all paths are resolved to absolute paths."""

    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        env_file_encoding="utf-8",
        env_prefix="ON1Y_",
        extra="ignore",
    )

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    db_path: Path = Field(default=PROJECT_ROOT / "data" / "on1y.db")

    worker_poll_seconds: float = Field(default=2.0, ge=0.5)
    worker_max_retries: int = Field(default=3, ge=1, le=10)
    subtitle_max_retries: int = Field(default=3, ge=1, le=10)
    subtitle_fetch_delay_seconds: float = Field(default=2.5, ge=0.0, le=30.0)
    subtitle_rate_limit_backoff_seconds: float = Field(default=60.0, ge=5.0, le=600.0)
    subtitle_rotate_clash_on_429: bool = Field(default=True)
    # Clash external-controller (enable in Clash: external-controller 0.0.0.0:9090)
    clash_api_base: str | None = Field(default=None)
    clash_api_secret: str | None = Field(default=None)
    clash_proxy_group: str | None = Field(default=None)
    clash_api_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    # After YouTube/Bilibili subtitles are ready, run LLM distill if API key is configured
    auto_distill_after_subtitles: bool = Field(default=True)

    max_body_chars: int = Field(default=500_000, ge=1_000)
    jina_reader_base: str = Field(default="https://r.jina.ai/")
    http_timeout_seconds: float = Field(default=60.0, ge=5.0)
    # Comma-separated yt-dlp subtitle languages (Chinese variants + English)
    ytdlp_sub_langs: str = Field(default=_DEFAULT_YTDLP_SUB_LANGS)
    # Preferred transcript language when both zh/en subtitles exist: zh | en
    content_locale: str = Field(default="zh")
    # When only English subtitles exist but content_locale is zh, auto LLM translate
    auto_translate_en_subtitles: bool = Field(default=True)
    # HTTP/SOCKS proxy for yt-dlp (YouTube/Bilibili). Example: http://127.0.0.1:7890
    ytdlp_proxy: str | None = Field(default=None)
    ytdlp_socket_timeout: int = Field(default=30, ge=5, le=300)
    ytdlp_retries: int = Field(default=3, ge=1, le=10)

    playwright_headless: bool = Field(default=True)
    playwright_timeout_ms: int = Field(default=60_000, ge=5_000)
    playwright_settle_ms: int = Field(default=2_000, ge=0)

    # Zhihu pipeline: spacing between Playwright fetches (anti-bot)
    zhihu_min_interval_seconds: float = Field(default=45.0, ge=0.0)
    # Stop the batch when anti-bot is detected (seconds to log as recommended wait)
    zhihu_antibot_pause_seconds: float = Field(default=300.0, ge=60.0)
    # Base URL for scripts/sync_zhihu_feeds.py (self-hosted RSSHub recommended)
    zhihu_rsshub_base: str = Field(default="http://127.0.0.1:1200")
    # RSSHub base for Bilibili UP feeds (scripts/sync_bilibili_feeds.py)
    bilibili_rsshub_base: str = Field(default="https://rsshub.app")
    # Bilibili UP subscription sync (API poll + feeds.yaml merge).
    bilibili_up_sync_enabled: bool = Field(default=True)
    # Poll strategy: dynamic = 关注动态(type=video); space = per-UP /x/space/arc/search
    bilibili_up_poll_mode: str = Field(default="dynamic", pattern="^(dynamic|space)$")
    # Max recent videos to scan per UP during daily poll
    bilibili_up_poll_page_size: int = Field(default=30, ge=1, le=50)
    bilibili_up_poll_max_pages: int = Field(default=1, ge=1, le=5)
    # Pages per UP when user runs explicit --backfill
    bilibili_up_poll_backfill_max_pages: int = Field(default=10, ge=1, le=50)
    # Pages per UP on first poll with sync-since (not full backfill)
    bilibili_up_poll_since_max_pages: int = Field(default=3, ge=1, le=20)
    bilibili_up_poll_interval_seconds: float = Field(default=12.0, ge=0.0, le=120.0)
    bilibili_up_poll_page_interval_seconds: float = Field(default=2.0, ge=0.0, le=30.0)
    bilibili_up_poll_rate_limit_retries: int = Field(default=6, ge=1, le=12)
    bilibili_up_poll_rate_limit_backoff_seconds: float = Field(default=45.0, ge=5.0, le=600.0)
    bilibili_up_poll_rate_limit_max_backoff_seconds: float = Field(default=120.0, ge=10.0, le=600.0)
    bilibili_up_poll_rate_limit_cooldown_seconds: float = Field(default=90.0, ge=0.0, le=600.0)
    bilibili_up_poll_rate_limit_stop_after: int = Field(default=5, ge=1, le=20)
    # 0 = poll all followed UPs in one run; otherwise cap per run to reduce 过于频繁
    bilibili_up_poll_max_ups_per_run: int = Field(default=10, ge=0, le=200)
    # Following dynamics feed (/x/polymer/web-dynamic/v1/feed/all?type=video)
    bilibili_dynamic_poll_max_pages: int = Field(default=5, ge=1, le=50)
    bilibili_dynamic_poll_backfill_max_pages: int = Field(default=20, ge=1, le=100)
    bilibili_dynamic_poll_page_interval_seconds: float = Field(default=1.0, ge=0.0, le=30.0)
    # Cold start: pull Bilibili following dynamics instead of per-UP space API
    cold_start_bilibili_dynamic_days: int = Field(default=3, ge=1, le=30)
    cold_start_bilibili_dynamic_max_pages: int = Field(default=50, ge=1, le=200)
    # Feed type written when syncing Zhihu follow list (activities | answers)
    zhihu_follow_feed_type: str = Field(default="activities")
    # Zhihu daily hot list (questions + excerpt + link)
    zhihu_hotlist_enabled: bool = Field(default=True)
    zhihu_hotlist_limit: int = Field(default=50, ge=1, le=100)
    zhihu_hotlist_auto_tag: bool = Field(default=True)
    # The Economist daily digest (RSS → hot-list column)
    economist_hotlist_enabled: bool = Field(default=True)
    economist_hotlist_limit: int = Field(default=40, ge=1, le=100)
    economist_hotlist_auto_tag: bool = Field(default=True)
    # Official feed works in many regions; use RSSHub if blocked, e.g.
    # http://127.0.0.1:1200/economist/latest or /economist/espresso
    economist_hotlist_rss_url: str = Field(
        default=(
            "https://github.com/hehonghui/awesome-english-ebooks/"
            "commits/master/01_economist.atom"
        )
    )
    # Optional mirror for raw PDF URLs when raw.githubusercontent.com is slow/blocked.
    # Example: https://ghfast.top/https://raw.githubusercontent.com/hehonghui/awesome-english-ebooks/master
    economist_github_raw_base: str = Field(default="")
    economist_epub_preview_max_chars: int = Field(default=40_000, ge=2_000, le=200_000)
    economist_auto_sync_enabled: bool = Field(default=True)
    economist_auto_sync_interval_minutes: int = Field(default=60, ge=15, le=24 * 60)
    economist_auto_kindle: bool = Field(default=True)
    kindle_send_to: str | None = Field(default=None)

    # SMTP for Send to Kindle (FROM must be approved in Amazon account settings)
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_from: str | None = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    # Max RSS entries to enqueue per feed during cold-start backfill
    rss_backfill_max_items_per_feed: int = Field(default=100, ge=1, le=500)

    # Pipeline alerts (429 / 风控)
    alert_enabled: bool = Field(default=True)
    alert_cooldown_seconds: float = Field(default=300.0, ge=60.0)
    alert_terminal_bell: bool = Field(default=True)
    alert_notify_send: bool = Field(default=True)
    alert_webhook_url: str | None = Field(default=None)

    zhihu_cookies_path: Path = Field(default=PROJECT_ROOT / "data" / "cookies" / "zhihu.json")
    xiaohongshu_cookies_path: Path = Field(
        default=PROJECT_ROOT / "data" / "cookies" / "xiaohongshu.json"
    )
    twitter_cookies_path: Path = Field(default=PROJECT_ROOT / "data" / "cookies" / "twitter.json")
    youtube_cookies_path: Path = Field(default=PROJECT_ROOT / "data" / "cookies" / "youtube.json")
    bilibili_cookies_path: Path = Field(default=PROJECT_ROOT / "data" / "cookies" / "bilibili.json")

    # If true, video extractors fail fast when cookie file is missing
    require_login_cookies: bool = Field(default=True)

    rss_config_path: Path = Field(default=PROJECT_ROOT / "config" / "feeds.yaml")
    # Used by serve background auto-sync when auto_sync_enabled=true
    rss_poll_interval_minutes: int = Field(default=30, ge=1)
    auto_sync_enabled: bool = Field(default=False)
    auto_sync_interval_minutes: int = Field(default=30, ge=5, le=24 * 60)
    auto_sync_platform: str = Field(default="all", pattern="^(bilibili|youtube|zhihu|all)$")
    auto_sync_ingest: bool = Field(default=True)
    auto_sync_ingest_limit: int = Field(default=10, ge=1, le=50)
    auto_sync_subtitle_limit: int = Field(default=10, ge=0, le=50)
    auto_sync_distill_limit: int = Field(default=50, ge=0, le=50)
    # Wait before the first auto-sync tick so serve/UI can start responsive.
    auto_sync_startup_delay_seconds: int = Field(default=120, ge=0, le=3600)
    # First tick after delay: poll subscriptions only (no ingest/subtitles/distill).
    auto_sync_startup_poll_only: bool = Field(default=True)
    # Favorites / playlists polling while serve is running (B站/知乎收藏夹, YouTube WL/Liked)
    collections_sync_enabled: bool = Field(default=True)
    collections_sync_interval_seconds: int = Field(default=120, ge=30, le=3600)
    collections_sync_platforms: str = Field(default="bilibili,zhihu,youtube")
    collections_sync_ingest: bool = Field(default=True)
    collections_sync_ingest_limit: int = Field(default=3, ge=0, le=20)
    collections_sync_startup_delay_seconds: int = Field(default=90, ge=0, le=3600)
    collections_sync_startup_poll_only: bool = Field(default=True)
    collections_max_items_per_source: int = Field(default=80, ge=10, le=500)
    collections_early_stop_existing_streak: int = Field(default=20, ge=5, le=200)
    youtube_collections_watch_later: bool = Field(
        default=False,
        description="Watch Later (WL) is often blocked by YouTube/yt-dlp; Liked (LL) still syncs.",
    )
    youtube_collections_liked: bool = Field(default=True)
    # Optional: refresh feeds.yaml from platform lists before RSS poll
    youtube_auto_refresh_channels: bool = Field(default=False)
    youtube_refresh_max_channels: int = Field(default=50, ge=1, le=500)
    # Skip YouTube live / upcoming streams and live replays during ingest
    youtube_skip_live: bool = Field(default=True)
    youtube_skip_live_replays: bool = Field(default=True)
    # Skip /shorts/ URLs and videos <= 60s when true
    youtube_skip_shorts: bool = Field(default=True)
    # Minimum duration for YouTube ingest (0 = disabled). Default 2 minutes.
    youtube_min_duration_sec: int = Field(default=120, ge=0, le=86_400)
    zhihu_auto_refresh_follows: bool = Field(default=False)
    # Zhihu follow sync: api = cookie API poll (no RSSHub); rss = feeds.yaml + RSSHub
    zhihu_follow_sync_mode: str = Field(default="api", pattern="^(api|rss)$")
    zhihu_api_poll_max_followees: int = Field(default=25, ge=1, le=200)
    zhihu_api_poll_max_pages: int = Field(default=2, ge=1, le=20)
    zhihu_api_poll_backfill_pages: int = Field(default=5, ge=1, le=50)

    log_level: str = Field(default="INFO")

    web_host: str = Field(default="127.0.0.1")
    web_port: int = Field(default=8765, ge=1, le=65535)

    # Multi-user auth (web UI + per-user cookies/profile)
    auth_secret_key: str = Field(default="change-me-in-production")
    auth_token_ttl_hours: int = Field(default=168, ge=1, le=24 * 30)
    # Local single-user desktop: False skips login UI; user profile/settings still use user id=1.
    auth_required: bool = Field(default=True)
    auth_allow_registration: bool = Field(default=True)
    bootstrap_username: str = Field(default="admin")
    bootstrap_password: str | None = Field(default=None)
    bootstrap_email: str | None = Field(default=None)
    # Comma-separated extra CORS origins for the Next.js dev server (e.g. http://localhost:3001)
    cors_origins: str = Field(default="")

    llm_base_url: str = Field(default="https://api.deepseek.com")
    llm_api_key: str | None = Field(default=None)
    llm_model: str = Field(default="deepseek-v4-flash")
    llm_timeout_seconds: float = Field(default=120.0, ge=10.0)
    llm_max_input_chars: int = Field(default=24_000, ge=2_000)
    # Distill: smaller input + capped output = faster classification passes
    llm_distill_max_input_chars: int = Field(default=4_000, ge=500, le=24_000)
    llm_max_output_tokens: int = Field(default=384, ge=64, le=1024)
    llm_locale: str = Field(default="zh", pattern="^(zh|en)$")

    @field_validator(
        "data_dir",
        "db_path",
        "rss_config_path",
        "zhihu_cookies_path",
        "xiaohongshu_cookies_path",
        "twitter_cookies_path",
        "youtube_cookies_path",
        "bilibili_cookies_path",
        mode="before",
    )
    @classmethod
    def _expand_path(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @field_validator("jina_reader_base")
    @classmethod
    def _normalize_jina_base(cls, value: str) -> str:
        return value if value.endswith("/") else f"{value}/"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "cookies").mkdir(parents=True, exist_ok=True)

    def cors_allow_origins(self) -> list[str]:
        defaults = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:3045",
            "http://127.0.0.1:3045",
            "http://localhost:8765",
            "http://127.0.0.1:8765",
        ]
        extra = [part.strip() for part in self.cors_origins.split(",") if part.strip()]
        seen: set[str] = set()
        merged: list[str] = []
        for origin in defaults + extra:
            if origin not in seen:
                seen.add(origin)
                merged.append(origin)
        return merged


@lru_cache
def get_settings() -> Settings:
    return Settings()
