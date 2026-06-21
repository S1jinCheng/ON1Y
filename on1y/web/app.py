"""Local web dashboard for RSS subscriptions, queue, and raw_items."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from on1y.adapters.sqlite_storage import get_storage
from on1y.config import get_settings
from on1y.ingestion.enqueue import enqueue_url
from on1y.ingestion.rss import list_feed_status, load_feeds, poll_rss_feeds
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.pipeline.processor import process_url
from on1y.pipeline.worker import run_worker_batch
from on1y.utils.platform import PLATFORM_ZHIHU

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class IngestRequest(BaseModel):
    url: str
    queue: bool = False


class WorkerRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=50)


class LlmSettingsRequest(BaseModel):
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    api_key: str = ""
    clear_api_key: bool = False


class NetworkSettingsRequest(BaseModel):
    proxy_mode: str | None = None  # auto | manual | off
    manual_proxy: str | None = None
    test_proxy: str | None = None


class SmtpSettingsRequest(BaseModel):
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = None
    password: str = ""
    from_addr: str | None = None
    use_tls: bool | None = None
    clear_password: bool = False


class SyncSettingsRequest(BaseModel):
    zhihu_api_poll_max_followees: int | None = None
    zhihu_api_poll_max_pages: int | None = None
    zhihu_api_poll_backfill_pages: int | None = None
    zhihu_follow_sync_mode: str | None = None
    zhihu_rsshub_base: str | None = None
    youtube_auto_refresh_channels: bool | None = None
    zhihu_auto_refresh_follows: bool | None = None
    auto_sync_enabled: bool | None = None
    auto_sync_interval_minutes: int | None = None
    auto_sync_pipeline_batch_size: int | None = None
    collections_sync_enabled: bool | None = None
    collections_sync_interval_seconds: int | None = None
    bilibili_up_poll_mode: str | None = None
    bilibili_up_poll_max_ups_per_run: int | None = None
    bilibili_dynamic_poll_max_pages: int | None = None
    bilibili_dynamic_poll_backfill_max_pages: int | None = None
    bilibili_up_poll_rate_limit_backoff_seconds: float | None = None
    bilibili_up_poll_rate_limit_cooldown_seconds: float | None = None
    rss_backfill_max_items_per_feed: int | None = None
    cold_start_bilibili_dynamic_days: int | None = None
    cold_start_bilibili_dynamic_max_pages: int | None = None
    economist_auto_sync_enabled: bool | None = None
    economist_auto_sync_interval_minutes: int | None = None
    economist_github_raw_base: str | None = None
    alert_enabled: bool | None = None
    alert_cooldown_seconds: float | None = None
    alert_webhook_url: str | None = None


class SubscriptionSettingsRequest(BaseModel):
    bilibili_sync_since: str | None = None
    youtube_sync_since: str | None = None
    zhihu_sync_since: str | None = None
    enabled_platforms: list[str] | None = None


class SubscriptionSyncRequest(BaseModel):
    platform: str = "all"
    platforms: list[str] | None = None
    backfill: bool = False
    ingest: bool = True
    use_ai_summary: bool = True
    ingest_limit: int = Field(default=30, ge=1, le=200)
    subtitle_limit: int = Field(default=30, ge=0, le=200)
    distill_limit: int = Field(default=50, ge=0, le=500)
    pipeline_batch_size: int | None = Field(default=None, ge=5, le=100)
    refresh_feeds: bool = False
    sync_hotlist: bool = False


class DistillBackfillRequest(BaseModel):
    platform: str | None = "bilibili"
    batch_size: int = Field(default=10, ge=1, le=20)
    max_items: int = Field(default=500, ge=1, le=1000)


class HotlistSyncRequest(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["zhihu"])
    auto_distill: bool = False
    auto_tag: bool = True
    snapshot_date: str | None = None


class UserProfilePatchRequest(BaseModel):
    kindle_enabled: bool | None = None
    kindle_send_to: str | None = None
    economist_auto_ingest: bool | None = None
    economist_auto_kindle: bool | None = None
    locale: str | None = Field(default=None, pattern="^(zh|en)$")
    appearance: str | None = Field(default=None, pattern="^(light|dark|system)$")
    open_browser_on_start: bool | None = None
    cold_start_onboarding_dismissed: bool | None = None


class AutostartRequest(BaseModel):
    enabled: bool


class DesktopPrefsPatchRequest(BaseModel):
    close_window_action: str | None = Field(default=None, pattern="^(hide|quit)$")
    data_dir_override: str | None = None


class CookieJsonImportRequest(BaseModel):
    payload: dict[str, Any] | list[dict[str, Any]]


class DistillRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)
    raw_id: int | None = None
    force: bool = False
    platform: str | None = None


class ManualItemRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body_text: str = Field(min_length=1)
    url: str | None = None
    platform: str = "manual"
    source: SourceType = SourceType.MANUAL
    author: str | None = None
    theme_slug: str | None = None
    theme_slugs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    auto_distill: bool = True


class ClassificationUpdate(BaseModel):
    theme_slug: str | None = None
    theme_slugs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ThemeCreateRequest(BaseModel):
    slug: str = ""
    name_zh: str = Field(min_length=1, max_length=100)
    name_en: str = ""
    description_zh: str = ""
    description_en: str = ""
    sort_order: int | None = None
    absorb_from_other: bool = True


class ThemeUpdateRequest(BaseModel):
    name_zh: str | None = None
    name_en: str | None = None
    description_zh: str | None = None
    description_en: str | None = None
    sort_order: int | None = None


class ThemeReorderRequest(BaseModel):
    theme_ids: list[int] = Field(min_length=1)


class ThemeMoveRequest(BaseModel):
    theme_id: int | None = None
    theme_slug: str | None = None


class ItemNoteUpdate(BaseModel):
    html: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)


class ItemAnnotationUpdate(BaseModel):
    html: str = ""


class FavoriteUpdate(BaseModel):
    starred: bool = False


class ReadStateUpdate(BaseModel):
    read: bool = True


class ImportanceUpdate(BaseModel):
    importance: int | None = Field(default=None, ge=1, le=5)


class BatchDeleteRequest(BaseModel):
    raw_ids: list[int] = Field(min_length=1, max_length=200)


class BatchRestoreRequest(BaseModel):
    raw_ids: list[int] = Field(min_length=1, max_length=200)


class NewThemeSpec(BaseModel):
    slug: str = ""
    name_zh: str = Field(min_length=1)
    name_en: str = ""
    description_zh: str = ""
    description_en: str = ""


class ThemeSplitRequest(BaseModel):
    source_theme_id: int
    new_themes: list[NewThemeSpec] = Field(min_length=1)
    archive_source: bool = True
    locale: str | None = None


def _theme_rows_for_api(rows: list[dict[str, Any]], locale: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": int(row["id"]),
                "slug": str(row["slug"]),
                "name_zh": str(row["name_zh"]),
                "name_en": str(row["name_en"]),
                "description_zh": str(row.get("description_zh") or ""),
                "description_en": str(row.get("description_en") or ""),
                "label": (
                    str(row["name_en"])
                    if locale.lower().startswith("en")
                    else str(row["name_zh"])
                ),
                "item_count": int(row["item_count"]),
                "is_builtin": bool(int(row.get("is_builtin") or 0)),
                "archived_at": row.get("archived_at"),
            }
        )
    return out


def _multipart_installed() -> bool:
    return importlib.util.find_spec("python_multipart") is not None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="On1y", version="0.1.0", description="Phase 1 dashboard")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins(),
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from on1y.web.auth_http import install_auth_middleware, register_auth_routes

    register_auth_routes(app)
    install_auth_middleware(app)

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        storage = get_storage()
        try:
            pending = storage.count_pending_by_status()
            feeds = load_feeds()
            enabled = sum(1 for f in feeds if f.enabled)
            subtitles = storage.count_subtitles_by_status()
            return {
                "pending": pending,
                "subtitles": subtitles,
                "zhihu_pending": storage.count_pending_for_platform(PLATFORM_ZHIHU),
                "raw_count": storage.count_raw_items(),
                "distilled_count": storage.count_distilled_items(),
                "feeds_total": len(feeds),
                "feeds_enabled": enabled,
            }
        finally:
            storage.close()

    @app.get("/api/alerts")
    def alerts_list(active: bool = Query(default=True)) -> list[dict[str, Any]]:
        from on1y.alerts import list_alerts

        return list_alerts(limit=20, active_only=active)

    @app.post("/api/alerts/ack")
    def alerts_ack(clear_all: bool = Query(default=True)) -> dict[str, int]:
        from on1y.alerts import acknowledge_alerts

        return {"cleared": acknowledge_alerts(clear_all=clear_all)}

    @app.get("/api/feeds")
    def feeds() -> list[dict[str, Any]]:
        storage = get_storage()
        try:
            return list_feed_status(storage)
        finally:
            storage.close()

    @app.post("/api/rss/poll")
    def rss_poll() -> dict[str, int]:
        storage = get_storage()
        try:
            count = poll_rss_feeds(storage)
            return {"enqueued": count}
        finally:
            storage.close()

    @app.get("/api/queue")
    def queue(
        status: str | None = Query(default=None),
        limit: int = Query(default=80, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        storage = get_storage()
        try:
            rows = storage.list_pending_urls(status=status, limit=limit)
            return [
                {
                    "id": p.id,
                    "url": p.url,
                    "source": p.source.value,
                    "status": p.status.value,
                    "attempts": p.attempts,
                    "error": p.error,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "feed_label": (p.source_meta or {}).get("feed_label"),
                    "entry_title": (p.source_meta or {}).get("entry_title"),
                }
                for p in rows
            ]
        finally:
            storage.close()

    @app.get("/api/items")
    def items(
        platform: str | None = Query(default=None),
        source: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        storage = get_storage()
        try:
            rows = storage.list_raw_items(
                platform=platform,
                source=source,
                limit=limit,
                offset=offset,
            )
            return [
                {
                    "id": r.id,
                    "url": r.url,
                    "platform": r.platform,
                    "source": r.source.value,
                    "title": r.raw_title,
                    "extract_status": r.extract_status.value,
                    "word_count": r.word_count,
                    "ingested_at": r.ingested_at.isoformat() if r.ingested_at else None,
                }
                for r in rows
            ]
        finally:
            storage.close()

    @app.get("/api/items/{item_id}")
    def item_detail(item_id: int) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(item_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="Not found")
            return {
                "id": raw.id,
                "url": raw.url,
                "platform": raw.platform,
                "source": raw.source.value,
                "title": raw.raw_title,
                "extract_status": raw.extract_status.value,
                "extract_error": raw.extract_error,
                "word_count": raw.word_count,
                "body_text": raw.body_text,
                "ingested_at": raw.ingested_at.isoformat() if raw.ingested_at else None,
            }
        finally:
            storage.close()

    @app.post("/api/ingest")
    def ingest(body: IngestRequest) -> dict[str, Any]:
        storage = get_storage()
        try:
            if body.queue:
                pending_id = enqueue_url(storage, body.url, source=SourceType.MANUAL)
                return {"queued": True, "pending_id": pending_id, "url": body.url}
            raw = process_url(storage, body.url, source=SourceType.MANUAL)
            return {
                "queued": False,
                "id": raw.id,
                "url": raw.url,
                "platform": raw.platform,
                "extract_status": raw.extract_status.value,
                "word_count": raw.word_count,
                "title": raw.raw_title,
            }
        finally:
            storage.close()

    @app.post("/api/subtitles/run")
    def subtitles_run(body: WorkerRequest) -> dict[str, int]:
        storage = get_storage()
        try:
            from on1y.pipeline.subtitle_worker import run_subtitle_batch

            return run_subtitle_batch(storage, body.limit)
        finally:
            storage.close()

    @app.post("/api/worker/run")
    def worker_run(body: WorkerRequest) -> dict[str, int]:
        storage = get_storage()
        try:
            return run_worker_batch(storage, body.limit)
        finally:
            storage.close()

    @app.post("/api/pipeline/zhihu/run")
    def zhihu_pipeline_run(body: WorkerRequest) -> dict[str, object]:
        from on1y.pipeline.run_zhihu import run_zhihu_pipeline

        storage = get_storage()
        try:
            return run_zhihu_pipeline(
                storage,
                ingest_limit=body.limit,
                distill_limit=min(body.limit, 5),
            )
        finally:
            storage.close()

    @app.get("/api/llm/settings")
    def llm_settings_get() -> dict[str, Any]:
        from on1y.llm.settings import public_settings_view

        return public_settings_view()

    @app.post("/api/llm/settings")
    def llm_settings_save(body: LlmSettingsRequest) -> dict[str, Any]:
        from on1y.llm.settings import public_settings_view, save_file_settings

        save_file_settings(
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key if body.api_key.strip() else None,
            clear_api_key=body.clear_api_key,
        )
        return {"saved": True, **public_settings_view()}

    @app.get("/api/smtp/settings")
    def smtp_settings_get() -> dict[str, Any]:
        from on1y.delivery.smtp_settings import public_settings_view

        return public_settings_view()

    @app.post("/api/smtp/settings")
    def smtp_settings_save(body: SmtpSettingsRequest) -> dict[str, Any]:
        from on1y.delivery.smtp_settings import public_settings_view, save_file_settings

        save_file_settings(
            host=body.host,
            port=body.port,
            user=body.user,
            password=body.password if body.password.strip() else None,
            from_addr=body.from_addr,
            use_tls=body.use_tls,
            clear_password=body.clear_password,
        )
        return {"saved": True, **public_settings_view()}

    @app.post("/api/smtp/test")
    def smtp_settings_test(body: SmtpSettingsRequest | None = None) -> dict[str, Any]:
        from on1y.delivery.smtp_settings import test_smtp_connection

        if body is None:
            return test_smtp_connection()
        return test_smtp_connection(
            host=body.host,
            port=body.port,
            user=body.user,
            password=body.password.strip() or None,
            from_addr=body.from_addr,
            use_tls=body.use_tls,
        )

    @app.get("/api/network/settings")
    def network_settings_get() -> dict[str, Any]:
        from on1y.network.settings import public_settings_view

        return public_settings_view()

    @app.post("/api/network/settings")
    def network_settings_save(body: NetworkSettingsRequest) -> dict[str, Any]:
        from on1y.network.proxy import test_proxy_reachability
        from on1y.network.settings import public_settings_view, save_file_settings

        if body.test_proxy is not None:
            return test_proxy_reachability(body.test_proxy)
        mode = body.proxy_mode.strip().lower() if body.proxy_mode else None
        if mode is not None and mode not in {"auto", "manual", "off"}:
            raise HTTPException(status_code=400, detail="proxy_mode must be auto, manual, or off")
        save_file_settings(
            proxy_mode=mode,  # type: ignore[arg-type]
            manual_proxy=body.manual_proxy,
        )
        return {"saved": True, **public_settings_view()}

    @app.get("/api/sync/settings")
    def sync_settings_get() -> dict[str, Any]:
        from on1y.sync_settings.settings import public_settings_view

        return public_settings_view()

    @app.post("/api/sync/settings")
    def sync_settings_save(body: SyncSettingsRequest) -> dict[str, Any]:
        from on1y.sync_settings.settings import public_settings_view, save_sync_settings

        payload = body.model_dump(exclude_none=True)
        if body.zhihu_follow_sync_mode is not None:
            mode = body.zhihu_follow_sync_mode.strip().lower()
            if mode not in {"api", "rss"}:
                raise HTTPException(status_code=400, detail="zhihu_follow_sync_mode must be api or rss")
        if body.bilibili_up_poll_mode is not None:
            mode = body.bilibili_up_poll_mode.strip().lower()
            if mode not in {"dynamic", "space"}:
                raise HTTPException(status_code=400, detail="bilibili_up_poll_mode must be dynamic or space")
        save_sync_settings(**payload)
        return {"saved": True, **public_settings_view()}

    @app.get("/api/subscriptions/settings")
    def subscription_settings_get() -> dict[str, Any]:
        from on1y.subscriptions.settings import public_settings_view

        return public_settings_view()

    @app.post("/api/subscriptions/settings")
    def subscription_settings_save(body: SubscriptionSettingsRequest) -> dict[str, Any]:
        from on1y.subscriptions.settings import public_settings_view, save_subscription_settings

        try:
            save_subscription_settings(
                bilibili_sync_since=body.bilibili_sync_since,
                youtube_sync_since=body.youtube_sync_since,
                zhihu_sync_since=body.zhihu_sync_since,
                enabled_platforms=body.enabled_platforms,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": True, **public_settings_view()}

    @app.post("/api/sync/full")
    def full_sync() -> dict[str, Any]:
        from on1y.auth.context import get_current_user_id, get_effective_user_id
        from on1y.sync.full_sync import start_full_sync_job

        uid = get_current_user_id()
        if uid is None:
            uid = get_effective_user_id()
        return start_full_sync_job(user_id=uid)

    @app.get("/api/sync/full/status")
    def full_sync_status_route() -> dict[str, Any]:
        from on1y.sync.full_sync import full_sync_status

        return full_sync_status()

    @app.get("/api/sync/full/timing")
    def full_sync_timing_route(limit: int = 20) -> dict[str, Any]:
        from on1y.sync.full_sync import full_sync_status, full_sync_timing_history

        status = full_sync_status()
        return {
            "last_timing": status.get("last_timing"),
            "current_phase": status.get("current_phase"),
            "phases_ms": status.get("phases_ms"),
            "history": full_sync_timing_history(limit=min(max(limit, 1), 50)),
        }

    @app.post("/api/subscriptions/sync")
    def subscription_sync(body: SubscriptionSyncRequest) -> dict[str, Any]:
        from on1y.config import get_settings
        from on1y.subscriptions.sync_job import start_subscription_sync_job

        from on1y.subscriptions.sync_job import normalize_sync_platforms

        try:
            targets = normalize_sync_platforms(
                platform=body.platform,
                platforms=body.platforms,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        settings = get_settings()
        if "bilibili" in targets and not settings.bilibili_up_sync_enabled:
            raise HTTPException(
                status_code=400,
                detail="Bilibili UP sync disabled (set ON1Y_BILIBILI_UP_SYNC_ENABLED=true)",
            )

        distill_limit = body.distill_limit if body.use_ai_summary else 0

        from on1y.auth.context import get_current_user_id, get_effective_user_id
        from on1y.sync_settings.settings import resolve_settings

        uid = get_current_user_id()
        if uid is None:
            uid = get_effective_user_id()
        pipeline_batch = (
            body.pipeline_batch_size
            if body.pipeline_batch_size is not None
            else resolve_settings(user_id=uid).auto_sync_pipeline_batch_size
        )

        return start_subscription_sync_job(
            platforms=targets,
            backfill=body.backfill,
            ingest=body.ingest,
            ingest_limit=body.ingest_limit,
            subtitle_limit=body.subtitle_limit,
            distill_limit=distill_limit,
            use_ai_summary=body.use_ai_summary,
            sync_hotlist=body.sync_hotlist,
            refresh_feeds=body.refresh_feeds or None,
            user_id=uid,
            pipeline_batch_size=pipeline_batch,
        )

    @app.post("/api/hotlist/sync")
    def hotlist_sync(body: HotlistSyncRequest) -> dict[str, Any]:
        from datetime import date as date_type

        from on1y.hotlist import sync_hotlists

        snap = (body.snapshot_date or "").strip() or date_type.today().isoformat()
        try:
            parsed = date_type.fromisoformat(snap)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid snapshot_date") from exc
        if parsed.isoformat() > date_type.today().isoformat():
            raise HTTPException(status_code=400, detail="snapshot_date cannot be in the future")

        sources = body.sources or ["zhihu"]
        zhihu_only = "zhihu" in sources and "economist" not in sources
        if zhihu_only and parsed.isoformat() < date_type.today().isoformat():
            raise HTTPException(
                status_code=400,
                detail="only today's live hot list can be synced; pick a past date to browse",
            )

        storage = get_storage()
        try:
            return sync_hotlists(
                storage,
                sources=sources,
                auto_distill=body.auto_distill,
                auto_tag=body.auto_tag,
                snapshot_date=parsed.isoformat(),
            )
        finally:
            storage.close()

    @app.get("/api/hotlist/economist/weeks")
    def hotlist_economist_weeks(
        year: int | None = Query(default=None),
        locale: str = Query(default="zh"),
    ) -> dict[str, Any]:
        from on1y.hotlist.economist_preview_store import list_synced_edition_dates
        from on1y.hotlist.economist_weeks import current_iso_week, list_economist_editions

        y = year if year is not None else current_iso_week()[0]
        storage = get_storage()
        try:
            synced = list_synced_edition_dates(storage)
            weeks = list_economist_editions(year=y, locale=locale)
            for row in weeks:
                row["synced"] = str(row.get("edition_date") or "") in synced
        finally:
            storage.close()
        iso_year, iso_week = current_iso_week()
        return {
            "year": y,
            "weeks": weeks,
            "synced_dates": sorted(synced, reverse=True),
            "current_iso_year": iso_year,
            "current_iso_week": iso_week,
        }

    @app.get("/api/user/profile")
    def get_user_profile() -> dict[str, Any]:
        from on1y.user.profile import public_profile_view

        return public_profile_view()

    @app.post("/api/system/pick-folder")
    def system_pick_folder() -> dict[str, Any]:
        from on1y.system.folder_picker import pick_folder_dialog

        path = pick_folder_dialog()
        if path is None:
            return {"path": None}
        return {"path": path}

    @app.post("/api/system/open-path")
    def system_open_path(body: dict[str, Any]) -> dict[str, Any]:
        import os
        import sys
        from pathlib import Path

        from on1y.auth.context import get_effective_user_id
        from on1y.books.settings_store import load_book_settings
        from on1y.user.paths import resolve_books_cache_dir

        raw = str(body.get("path") or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="path is required")
        target = Path(raw).expanduser()
        try:
            resolved = target.resolve(strict=False)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not resolved.is_file():
            raise HTTPException(status_code=400, detail="not a file")
        uid = get_effective_user_id()
        cache_root = resolve_books_cache_dir(uid, load_book_settings(uid).cache_dir).resolve()
        try:
            resolved.relative_to(cache_root)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="path not allowed") from exc
        try:
            if sys.platform == "win32":
                os.startfile(resolved)  # noqa: S606
            elif sys.platform == "darwin":
                import subprocess

                subprocess.run(["open", str(resolved)], check=False)
            else:
                import subprocess

                subprocess.run(["xdg-open", str(resolved)], check=False)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True}

    @app.get("/api/app/desktop")
    def app_desktop_status() -> dict[str, Any]:
        from on1y import __version__
        from on1y.app_update import is_bundled_release
        from on1y.config import PROJECT_ROOT, get_settings
        from on1y.desktop.windows_autostart import autostart_installed, is_windows

        from on1y.desktop.launch_prefs import read_launch_prefs

        settings = get_settings()
        prefs = read_launch_prefs(settings)
        return {
            "platform": "windows" if is_windows() else sys.platform,
            "autostart_supported": is_windows(),
            "autostart_enabled": autostart_installed() if is_windows() else False,
            "version": __version__,
            "project_root": str(PROJECT_ROOT),
            "data_dir": str(settings.data_dir),
            "data_dir_override": prefs.get("data_dir_override"),
            "close_window_action": prefs.get("close_window_action") or "quit",
            "is_desktop_shell": bool(os.environ.get("ON1Y_DESKTOP_SHELL")),
            "is_bundled_release": is_bundled_release(),
            "web_url": f"http://{settings.web_host}:{settings.web_port}",
        }

    @app.get("/api/app/update")
    def app_update_status(
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        from on1y.app_update import check_app_update

        return check_app_update(force=force)

    @app.patch("/api/app/desktop-prefs")
    def patch_desktop_prefs(body: DesktopPrefsPatchRequest) -> dict[str, Any]:
        from on1y.desktop.launch_prefs import read_launch_prefs, write_launch_prefs

        write_launch_prefs(
            close_window_action=body.close_window_action,  # type: ignore[arg-type]
            data_dir_override=body.data_dir_override,
        )
        prefs = read_launch_prefs()
        return {
            "close_window_action": prefs.get("close_window_action") or "quit",
            "data_dir_override": prefs.get("data_dir_override"),
            "restart_required": body.data_dir_override is not None,
        }

    @app.post("/api/app/autostart")
    def app_set_autostart(body: AutostartRequest) -> dict[str, Any]:
        from on1y.desktop.windows_autostart import autostart_installed, is_windows, set_autostart

        if not is_windows():
            raise HTTPException(status_code=501, detail="autostart only supported on Windows")
        try:
            set_autostart(body.enabled)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"autostart_enabled": autostart_installed()}

    def _user_cookie_rows(
        *,
        verify: bool = True,
        force_verify: bool = False,
        quick_verify: bool = True,
    ) -> list[dict[str, Any]]:
        from concurrent.futures import ThreadPoolExecutor

        from on1y.auth.context import get_effective_user_id
        from on1y.cookies.loader import resolve_cookie_path
        from on1y.cookies.verify import verify_cookie_account
        from on1y.user.paths import COOKIE_PLATFORMS

        uid = get_effective_user_id()

        def _one_row(platform: str) -> dict[str, Any]:
            path = resolve_cookie_path(platform, user_id=uid)
            count = 0
            updated_at: str | None = None
            exists = path.is_file()
            if exists:
                try:
                    import json as _json

                    blob = _json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(blob, dict):
                        count = len(blob.get("cookies") or [])
                    elif isinstance(blob, list):
                        count = len(blob)
                    import datetime as _dt

                    updated_at = _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                        timespec="seconds"
                    )
                except Exception:
                    count = 0
            account: dict[str, Any] | None = None
            if exists and verify and platform in {"bilibili", "youtube", "zhihu", "zlibrary"}:
                account = verify_cookie_account(
                    platform,
                    user_id=uid,
                    force=force_verify,
                    quick=quick_verify and not force_verify,
                )
            return {
                "platform": platform,
                "exists": exists,
                "count": count,
                "updated_at": updated_at,
                "path": str(path) if exists else None,
                "account": account,
            }

        platforms = list(COOKIE_PLATFORMS)
        if not verify or len(platforms) <= 1:
            return [_one_row(p) for p in platforms]

        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(3, len(platforms))) as pool:
            rows = list(pool.map(_one_row, platforms))
        return rows

    @app.get("/api/user/cookies")
    def user_cookies_list(
        verify: bool = Query(default=True),
        quick: bool = Query(default=True),
    ) -> dict[str, Any]:
        return {"platforms": _user_cookie_rows(verify=verify, quick_verify=quick)}

    @app.get("/api/user/cookies/status")
    def user_cookies_status(
        verify: bool = Query(default=True),
        quick: bool = Query(default=True),
    ) -> dict[str, Any]:
        return {"platforms": _user_cookie_rows(verify=verify, quick_verify=quick)}

    @app.post("/api/user/cookies/{platform}/verify")
    def verify_user_cookies(platform: str) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.user.paths import COOKIE_PLATFORMS
        from on1y.cookies.verify import verify_cookie_account

        if platform not in COOKIE_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")
        uid = get_effective_user_id()
        account = verify_cookie_account(platform, user_id=uid, force=True)
        return {"platform": platform, "account": account}

    @app.delete("/api/user/cookies/{platform}")
    def delete_user_cookies(platform: str) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.user.paths import COOKIE_PLATFORMS
        from on1y.user.paths import user_cookie_path

        if platform not in COOKIE_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")
        uid = get_effective_user_id()
        path = user_cookie_path(uid, platform)
        removed = False
        if path.is_file():
            path.unlink()
            removed = True
        netscape = path.with_suffix(path.suffix + ".netscape.txt")
        if netscape.is_file():
            netscape.unlink()
        return {"platform": platform, "removed": removed}

    @app.post("/api/user/cookies/{platform}")
    async def upload_user_cookies(platform: str, file: UploadFile = File(...)) -> dict[str, Any]:
        import json

        from on1y.cookies.import_user import persist_user_cookie_payload
        from on1y.user.paths import COOKIE_PLATFORMS

        if platform not in COOKIE_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")
        raw = await file.read()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid JSON cookie file") from exc
        if not isinstance(data, (dict, list)):
            raise HTTPException(status_code=400, detail="cookie JSON must be an object or array")
        try:
            return persist_user_cookie_payload(platform, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/user/cookies/{platform}/import")
    def import_user_cookies_json(platform: str, body: CookieJsonImportRequest) -> dict[str, Any]:
        from on1y.cookies.import_user import persist_user_cookie_payload
        from on1y.user.paths import COOKIE_PLATFORMS

        if platform not in COOKIE_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")
        try:
            return persist_user_cookie_payload(platform, body.payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/user/cookies/{platform}/qr/start")
    def start_cookie_qr_login(platform: str) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.user.paths import COOKIE_PLATFORMS
        from on1y.cookies.qr_login import QR_LOGIN_PLATFORMS, start_qr_login

        if platform not in COOKIE_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")
        if platform not in QR_LOGIN_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"QR login not available for {platform}")
        uid = get_effective_user_id()
        try:
            return start_qr_login(platform, user_id=uid)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/user/cookies/{platform}/qr/{session_id}")
    def poll_cookie_qr_login(platform: str, session_id: str) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.user.paths import COOKIE_PLATFORMS
        from on1y.cookies.qr_login import poll_qr_login

        if platform not in COOKIE_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")
        uid = get_effective_user_id()
        result = poll_qr_login(session_id, user_id=uid)
        if result.get("platform") and result["platform"] != platform:
            raise HTTPException(status_code=400, detail="platform mismatch")
        return result

    @app.delete("/api/user/cookies/{platform}/qr/{session_id}")
    def cancel_cookie_qr_login(platform: str, session_id: str) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.user.paths import COOKIE_PLATFORMS
        from on1y.cookies.qr_login import cancel_qr_login

        if platform not in COOKIE_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"unknown platform: {platform}")
        uid = get_effective_user_id()
        return cancel_qr_login(session_id, user_id=uid)

    @app.patch("/api/user/profile")
    def patch_user_profile_api(body: UserProfilePatchRequest) -> dict[str, Any]:
        from on1y.user.profile import patch_user_profile, public_profile_view

        sections: dict[str, Any] = {}
        kindle_patch: dict[str, Any] = {}
        if body.kindle_enabled is not None:
            kindle_patch["enabled"] = body.kindle_enabled
        if body.kindle_send_to is not None:
            kindle_patch["send_to"] = body.kindle_send_to.strip()
        if kindle_patch:
            sections["kindle"] = kindle_patch
        econ_patch: dict[str, Any] = {}
        if body.economist_auto_ingest is not None:
            econ_patch["auto_ingest_enabled"] = body.economist_auto_ingest
        if body.economist_auto_kindle is not None:
            econ_patch["auto_kindle_enabled"] = body.economist_auto_kindle
        if econ_patch:
            sections["economist"] = econ_patch
        app_patch: dict[str, Any] = {}
        if body.locale is not None:
            app_patch["locale"] = body.locale
        if body.appearance is not None:
            app_patch["appearance"] = body.appearance
        if body.open_browser_on_start is not None:
            app_patch["open_browser_on_start"] = body.open_browser_on_start
        if app_patch:
            sections["app"] = app_patch
        if body.cold_start_onboarding_dismissed is not None:
            sections["cold_start"] = {
                "onboarding_dismissed": body.cold_start_onboarding_dismissed,
            }
        if sections:
            patch_user_profile(**sections)
        return public_profile_view()

    @app.get("/api/user/archive/export")
    def export_user_archive_api(
        include_trash: bool = Query(default=False),
        include_settings: bool = Query(default=False),
    ) -> Response:
        from on1y.auth.context import get_effective_user_id
        from on1y.user.accounts import UserStore
        from on1y.user.archive import default_export_filename, export_user_archive

        storage = get_storage()
        try:
            uid = get_effective_user_id()
            data = export_user_archive(
                storage,
                uid,
                include_trash=include_trash,
                include_settings=include_settings,
            )
            username = "library"
            user = UserStore(storage).get_user_by_id(uid)
            if user is not None:
                username = user.username
            filename = default_export_filename(username)
            return Response(
                content=data,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        finally:
            storage.close()

    @app.post("/api/user/archive/import")
    async def import_user_archive_api(
        file: UploadFile = File(...),
        on_conflict: str = Query(default="overwrite"),
    ) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.user.archive import import_user_archive

        if on_conflict not in ("skip", "overwrite"):
            raise HTTPException(status_code=400, detail="on_conflict must be skip or overwrite")
        raw = await file.read()
        storage = get_storage()
        try:
            uid = get_effective_user_id()
            return import_user_archive(
                storage,
                uid,
                raw,
                on_conflict=on_conflict,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.post("/api/cold-start")
    def cold_start() -> dict[str, Any]:
        from on1y.auth.context import get_current_user_id, get_effective_user_id
        from on1y.sync.full_sync import start_full_sync_job

        uid = get_current_user_id()
        if uid is None:
            uid = get_effective_user_id()
        return start_full_sync_job(user_id=uid)

    @app.get("/api/cold-start/status")
    def cold_start_status_route() -> dict[str, Any]:
        from on1y.sync.full_sync import full_sync_status

        return full_sync_status()

    @app.get("/api/cold-start/timing")
    def cold_start_timing_route(limit: int = 20) -> dict[str, Any]:
        from on1y.sync.full_sync import full_sync_status, full_sync_timing_history

        status = full_sync_status()
        return {
            "last_timing": status.get("last_timing"),
            "current_phase": status.get("current_phase"),
            "phases_ms": status.get("phases_ms"),
            "progress": status.get("progress"),
            "history": full_sync_timing_history(limit=min(max(limit, 1), 50)),
        }

    @app.post("/api/hotlist/economist/auto")
    def hotlist_economist_auto(
        edition_date: str | None = Query(default=None),
    ) -> dict[str, Any]:
        from on1y.hotlist.economist_auto import run_economist_auto_tick

        return run_economist_auto_tick(
            force_edition=(edition_date or "").strip() or None,
        )

    @app.get("/api/hotlist/dates")
    def hotlist_dates(
        source: str = Query(default="zhihu"),
        limit: int = Query(default=120, ge=1, le=366),
    ) -> dict[str, Any]:
        from datetime import date as date_cls

        storage = get_storage()
        try:
            dates = storage.list_hotlist_dates(hotlist_source=source.strip() or "zhihu", limit=limit)
            today = date_cls.today().isoformat()
            if today not in dates:
                dates = [today, *dates]
            return {"source": source, "dates": dates, "today": today}
        finally:
            storage.close()

    @app.get("/api/collections/sync/status")
    def collections_sync_status() -> dict[str, Any]:
        from on1y.subscriptions.collections_auto_sync import collections_sync_status as get_status

        return get_status()

    @app.get("/api/subscriptions/sync/status")
    def subscription_sync_status() -> dict[str, Any]:
        from on1y.subscriptions.sync_job import subscription_sync_status as get_status

        return get_status()

    @app.post("/api/llm/test")
    def llm_settings_test(body: LlmSettingsRequest | None = None) -> dict[str, Any]:
        """Ping LLM with a minimal completion (uses saved settings if body omitted)."""
        from on1y.llm.client import LlmClient, resolve_chat_completions_url
        from on1y.llm.settings import get_resolved_llm_settings

        cfg = get_resolved_llm_settings()
        if body is not None:
            base_url = body.base_url.strip() or cfg.base_url
            model = body.model.strip() or cfg.model
            api_key = body.api_key.strip() or cfg.api_key
        else:
            base_url, model, api_key = cfg.base_url, cfg.model, cfg.api_key

        if not api_key.strip():
            raise HTTPException(status_code=400, detail="请先填写并保存 API Key")

        client = LlmClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=min(cfg.timeout_seconds, 60.0),
        )
        try:
            reply = client.chat(
                "You are a test assistant.",
                "Reply with exactly: ok",
            )
            return {
                "ok": True,
                "endpoint": resolve_chat_completions_url(base_url),
                "model": model,
                "reply_preview": (reply or "")[:200],
            }
        except Exception as exc:
            return {
                "ok": False,
                "endpoint": resolve_chat_completions_url(base_url),
                "model": model,
                "error": str(exc),
            }

    @app.get("/api/distill/list")
    def distill_list(limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
        storage = get_storage()
        try:
            return storage.list_distilled_summary(limit=limit)
        finally:
            storage.close()

    @app.get("/api/distill/{raw_id}")
    def distill_detail(raw_id: int) -> dict[str, Any]:
        storage = get_storage()
        try:
            detail = storage.get_distilled_detail(raw_id)
            if detail is None:
                raise HTTPException(status_code=404, detail="Not distilled")
            return detail
        finally:
            storage.close()

    @app.post("/api/distill/run")
    def distill_run(body: DistillRequest) -> dict[str, Any]:
        from on1y.distill.processor import distill_raw_item, list_distill_candidate_ids

        storage = get_storage()
        try:
            if body.raw_id is not None:
                ids = [body.raw_id]
            else:
                ids = list_distill_candidate_ids(
                    storage,
                    limit=body.limit,
                    force=body.force,
                    platform=body.platform,
                )
            if not ids:
                return {"distilled": 0, "failed": 0, "items": [], "message": "无待蒸馏条目"}
            ok, failed = 0, 0
            items: list[dict[str, Any]] = []
            for raw_id in ids:
                try:
                    did = distill_raw_item(storage, raw_id, force=body.force)
                    ok += 1
                    items.append({"raw_id": raw_id, "distilled_id": did, "status": "ok"})
                except Exception as exc:
                    failed += 1
                    items.append({"raw_id": raw_id, "status": "failed", "error": str(exc)})
            return {"distilled": ok, "failed": failed, "items": items}
        finally:
            storage.close()

    @app.post("/api/distill/backfill")
    def distill_backfill(body: DistillBackfillRequest) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.distill.batch_job import start_distill_batch_job

        return start_distill_batch_job(
            user_id=get_effective_user_id(),
            platform=body.platform,
            batch_size=body.batch_size,
            max_items=body.max_items,
        )

    @app.get("/api/distill/backfill/status")
    def distill_backfill_status() -> dict[str, Any]:
        from on1y.distill.batch_job import distill_batch_status

        return distill_batch_status()

    @app.get("/api/knowledge/themes")
    def knowledge_themes_list(locale: str = Query(default="zh")) -> dict[str, Any]:
        storage = get_storage()
        try:
            themes = _theme_rows_for_api(storage.list_themes_with_counts(), locale)
            return {"themes": themes, "locale": locale}
        finally:
            storage.close()

    @app.post("/api/knowledge/themes")
    def knowledge_themes_create(
        body: ThemeCreateRequest,
        locale: str = Query(default="zh"),
    ) -> dict[str, Any]:
        storage = get_storage()
        try:
            row = storage.create_theme(
                slug=body.slug,
                name_zh=body.name_zh,
                name_en=body.name_en or body.name_zh,
                description_zh=body.description_zh,
                description_en=body.description_en,
                sort_order=body.sort_order,
            )
            absorb: dict[str, Any] = {"started": False}
            theme_id = row.get("id")
            if body.absorb_from_other and theme_id is not None:
                from on1y.taxonomy.absorb import schedule_absorb_from_other

                absorb = schedule_absorb_from_other(
                    theme_id=int(theme_id),
                    locale=locale,
                )
            return {"theme": row, "absorb": absorb}
        finally:
            storage.close()

    @app.post("/api/knowledge/themes/{theme_id}/absorb-from-other")
    def knowledge_themes_absorb_from_other(
        theme_id: int,
        locale: str = Query(default="zh"),
    ) -> dict[str, Any]:
        storage = get_storage()
        try:
            theme = storage.get_theme_by_id(theme_id)
            if theme is None:
                raise HTTPException(status_code=404, detail="theme not found")
            if theme.get("archived_at"):
                raise HTTPException(status_code=400, detail="theme archived")
            from on1y.taxonomy.absorb import schedule_absorb_from_other

            return schedule_absorb_from_other(theme_id=theme_id, locale=locale)
        finally:
            storage.close()

    @app.post("/api/knowledge/themes/reorder")
    def knowledge_themes_reorder(
        body: ThemeReorderRequest,
        locale: str = Query(default="zh"),
    ) -> dict[str, Any]:
        from on1y.exceptions import StorageError

        storage = get_storage()
        try:
            storage.reorder_themes(body.theme_ids)
            themes = _theme_rows_for_api(storage.list_themes_with_counts(), locale)
            return {"ok": True, "themes": themes}
        except StorageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.delete("/api/knowledge/themes/{theme_id}")
    def knowledge_themes_delete(theme_id: int) -> dict[str, Any]:
        from on1y.exceptions import StorageError

        storage = get_storage()
        try:
            remapped = storage.archive_theme(theme_id, reassign_to_other=True)
            return {"ok": True, "theme_id": theme_id, "remapped": remapped}
        except StorageError as exc:
            msg = str(exc)
            status = 404 if "not found" in msg else 400
            raise HTTPException(status_code=status, detail=msg) from exc
        finally:
            storage.close()

    @app.patch("/api/knowledge/themes/{theme_id}")
    def knowledge_themes_update(theme_id: int, body: ThemeUpdateRequest) -> dict[str, Any]:
        storage = get_storage()
        try:
            row = storage.update_theme(
                theme_id,
                name_zh=body.name_zh,
                name_en=body.name_en,
                description_zh=body.description_zh,
                description_en=body.description_en,
                sort_order=body.sort_order,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="theme not found")
            return {"theme": row}
        finally:
            storage.close()

    @app.post("/api/knowledge/themes/split")
    def knowledge_themes_split(body: ThemeSplitRequest) -> dict[str, Any]:
        from on1y.taxonomy.remap import split_theme_one_shot

        storage = get_storage()
        try:
            specs = [t.model_dump() for t in body.new_themes]
            return split_theme_one_shot(
                storage,
                source_theme_id=body.source_theme_id,
                new_themes=specs,
                locale=body.locale,
                archive_source=body.archive_source,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.get("/api/knowledge/taxonomy")
    def knowledge_taxonomy(locale: str = Query(default="zh")) -> dict[str, Any]:
        storage = get_storage()
        try:
            themes = _theme_rows_for_api(storage.list_themes_with_counts(), locale)
            tags = storage.list_dynamic_tags_with_counts(limit=200)
            return {"themes": themes, "tags": tags, "locale": locale}
        finally:
            storage.close()

    @app.get("/api/knowledge/tags/tree")
    def knowledge_tags_tree(locale: str = Query(default="zh")) -> dict[str, Any]:
        """Backward-compatible alias → flat taxonomy."""
        storage = get_storage()
        try:
            themes = _theme_rows_for_api(storage.list_themes_with_counts(), locale)
            tags = storage.list_dynamic_tags_with_counts(limit=200)
            return {"themes": themes, "tags": tags, "tree": [], "flat": tags}
        finally:
            storage.close()

    @app.get("/api/stats/weekly")
    def stats_weekly(week_offset: int = Query(default=0, ge=-52, le=0)) -> dict[str, Any]:
        import logging

        from on1y.stats.weekly import build_weekly_review

        logger = logging.getLogger(__name__)
        storage = get_storage()
        try:
            try:
                return build_weekly_review(storage, week_offset=week_offset)
            except Exception as exc:
                logger.exception("stats weekly failed")
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.get("/api/knowledge/collections")
    def knowledge_collections(
        hotlist_date: str | None = Query(default=None),
        hotlist_source: str = Query(default="zhihu"),
    ) -> dict[str, Any]:
        from datetime import date as date_cls

        from on1y.hotlist.constants import SUPPORTED_HOTLIST_SOURCES

        src = hotlist_source.strip().lower()
        if src not in SUPPORTED_HOTLIST_SOURCES:
            raise HTTPException(status_code=400, detail=f"unsupported hotlist_source: {src}")

        from on1y.auth.context import get_effective_user_id
        from on1y.books.shelf import count_shelf_items

        storage = get_storage()
        try:
            hot_day = (hotlist_date or "").strip() or date_cls.today().isoformat()
            uid = get_effective_user_id()
            return {
                "favorites": storage.count_collection_items("favorites"),
                "trash": storage.count_collection_items("trash"),
                "hotlist": storage.count_collection_items(
                    "hotlist", hotlist_date=hot_day, hotlist_source=src
                ),
                "unread": storage.count_collection_items("unread"),
                "notes": storage.count_collection_items("notes"),
                "books": count_shelf_items(storage, uid),
            }
        finally:
            storage.close()

    @app.get("/api/books/sources")
    def books_sources_get() -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.sources_store import load_book_sources

        payload = load_book_sources(get_effective_user_id())
        return payload.model_dump()

    @app.put("/api/books/sources")
    def books_sources_put(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.models import BookSourcesFile
        from on1y.books.sources_store import save_book_sources

        try:
            payload = BookSourcesFile.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uid = get_effective_user_id()
        save_book_sources(uid, payload)
        return payload.model_dump()

    @app.post("/api/books/search")
    def books_search(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.search import search_books

        query = str(body.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query is required")
        source_ids = body.get("source_ids")
        ids = [str(x) for x in source_ids] if isinstance(source_ids, list) else None
        editions, links = search_books(get_effective_user_id(), query, source_ids=ids)
        return {
            "query": query,
            "editions": [e.model_dump() for e in editions],
            "links": [h.model_dump() for h in links],
        }

    @app.post("/api/books/detail")
    def books_detail(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.detail import load_book_detail

        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        detail = load_book_detail(get_effective_user_id(), url)
        if detail is None:
            raise HTTPException(status_code=404, detail="book detail not found")
        return detail.model_dump()

    @app.get("/api/books/cover")
    def books_cover_proxy(url: str = Query(..., min_length=8)) -> Any:
        import httpx
        from fastapi.responses import Response

        from on1y.books.cover import cover_fetch_headers, cover_proxy_allowed, normalize_cover_url

        target = normalize_cover_url(url)
        if not target or not cover_proxy_allowed(target):
            raise HTTPException(status_code=400, detail="cover url not allowed")
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(target, headers=cover_fetch_headers(target))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"cover fetch failed: {exc}") from exc
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"cover fetch failed: HTTP {resp.status_code}")
        media = resp.headers.get("content-type") or "image/jpeg"
        if not str(media).startswith("image/"):
            media = "image/jpeg"
        return Response(
            content=resp.content,
            media_type=str(media).split(";", 1)[0],
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/books/shelf")
    def books_shelf_list(
        status: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.shelf import list_shelf_items

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            items = list_shelf_items(storage, uid, status=status, limit=limit, offset=offset)
            return {
                "items": [item.model_dump() for item in items],
                "total": len(items),
            }
        finally:
            storage.close()

    @app.get("/api/books/shelf/{item_id}")
    def books_shelf_get(item_id: int) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.knowledge_sync import prepare_shelf_item
        from on1y.books.shelf import get_shelf_item

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = get_shelf_item(storage, uid, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="book not found")
            item = prepare_shelf_item(storage, uid, item)
            return item.model_dump()
        finally:
            storage.close()

    @app.get("/api/books/shelf/{item_id}/related")
    def books_shelf_related(
        item_id: int,
        limit: int = Query(default=6, ge=1, le=12),
    ) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.knowledge_sync import prepare_shelf_item
        from on1y.books.shelf import get_shelf_item
        from on1y.recommend.similar import find_related_items

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = get_shelf_item(storage, uid, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="book not found")
            try:
                item = prepare_shelf_item(storage, uid, item, auto_tag=False)
            except Exception as exc:
                logger.warning("books_shelf_related prepare failed item_id=%s: %s", item_id, exc)
            if item.raw_id is None:
                return {"items": [], "scope": "library", "from_raw_id": None}
            items = find_related_items(
                storage,
                from_raw_id=item.raw_id,
                limit=limit,
                scope="library",
            )
            return {"items": items, "scope": "library", "from_raw_id": item.raw_id}
        except Exception as exc:
            logger.exception("books_shelf_related failed item_id=%s", item_id)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.post("/api/books/shelf")
    def books_shelf_create(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.models import BookShelfCreate
        from on1y.books.shelf import create_shelf_item

        try:
            payload = BookShelfCreate.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = create_shelf_item(storage, uid, payload)
            from on1y.books.knowledge_sync import prepare_shelf_item

            item = prepare_shelf_item(storage, uid, item)
            return item.model_dump()
        finally:
            storage.close()

    @app.patch("/api/books/shelf/{item_id}")
    def books_shelf_update(item_id: int, body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.knowledge_sync import prepare_shelf_item, sync_shelf_tags_manual
        from on1y.books.models import BookShelfUpdate
        from on1y.books.shelf import get_shelf_item, update_shelf_item

        try:
            payload = BookShelfUpdate.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = update_shelf_item(storage, uid, item_id, payload)
            if item is None:
                raise HTTPException(status_code=404, detail="book not found")
            if payload.tags is not None:
                sync_shelf_tags_manual(storage, uid, item_id, payload.tags)
                item = get_shelf_item(storage, uid, item_id) or item
            elif any(
                getattr(payload, field) is not None
                for field in ("title", "author", "translator", "summary", "cover_url")
            ):
                item = prepare_shelf_item(storage, uid, item, auto_tag=False)
            else:
                item = get_shelf_item(storage, uid, item_id) or item
            return item.model_dump()
        finally:
            storage.close()

    @app.delete("/api/books/shelf/{item_id}")
    def books_shelf_delete(item_id: int) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.shelf import delete_shelf_item

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            ok = delete_shelf_item(storage, uid, item_id)
            if not ok:
                raise HTTPException(status_code=404, detail="book not found")
            return {"ok": True}
        finally:
            storage.close()

    @app.post("/api/books/shelf/{item_id}/kindle")
    def books_shelf_send_kindle(item_id: int) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.acquire import send_shelf_book_to_kindle
        from on1y.exceptions import ConfigurationError

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            return send_shelf_book_to_kindle(uid, storage, item_id)
        except ConfigurationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("books_shelf_send_kindle failed item_id=%s", item_id)
            raise HTTPException(status_code=502, detail=f"Kindle 推送失败：{exc}") from exc
        finally:
            storage.close()

    @app.get("/api/books/shelf/{item_id}/cached")
    def books_shelf_cached(item_id: int) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.cache_files import list_cached_ebooks
        from on1y.books.shelf import get_shelf_item

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = get_shelf_item(storage, uid, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="book not found")
            files = list_cached_ebooks(uid, item.title, notes=item.notes)
            return {"files": files}
        finally:
            storage.close()

    @app.get("/api/books/settings")
    def books_settings_get() -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.settings_store import load_book_settings
        from on1y.user.paths import resolve_books_cache_dir

        uid = get_effective_user_id()
        settings = load_book_settings(uid)
        try:
            resolved = resolve_books_cache_dir(uid, settings.cache_dir)
        except (PermissionError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = settings.model_dump()
        payload["resolved_cache_dir"] = str(resolved)
        return payload

    @app.put("/api/books/settings")
    def books_settings_put(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.settings_store import BookSettings, load_book_settings, save_book_settings
        from on1y.user.paths import resolve_books_cache_dir

        uid = get_effective_user_id()
        current = load_book_settings(uid)
        try:
            merged = current.model_copy(
                update={
                    k: body[k]
                    for k in (
                        "cache_dir",
                        "zlib_base_url",
                        "acquire_strategy",
                        "preferred_format",
                        "allowed_formats",
                        "format_filter",
                        "format_filters",
                        "default_format",
                        "annas_secret_key",
                    )
                    if k in body
                }
            )
            payload = BookSettings.model_validate(merged.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_book_settings(uid, payload)
        out = payload.model_dump()
        try:
            out["resolved_cache_dir"] = str(resolve_books_cache_dir(uid, payload.cache_dir))
        except (PermissionError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return out

    @app.post("/api/books/acquire/preview")
    def books_acquire_preview(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.acquire import preview_acquire_book
        from on1y.exceptions import ConfigurationError

        title = str(body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        author = str(body.get("author") or "").strip() or None
        translator = str(body.get("translator") or "").strip() or None
        publisher = str(body.get("publisher") or "").strip() or None
        isbn = str(body.get("isbn") or "").strip() or None
        douban_url = str(body.get("douban_url") or "").strip() or None
        douban_cover_url = str(body.get("cover_url") or "").strip() or None
        fmt = str(body.get("format") or "").strip().lower() or None
        uid = get_effective_user_id()
        try:
            return preview_acquire_book(
                uid,
                title=title,
                author=author,
                translator=translator,
                publisher=publisher,
                isbn=isbn,
                douban_url=douban_url,
                douban_cover_url=douban_cover_url,
                fmt=fmt,
            )
        except ConfigurationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/books/acquire")
    def books_acquire(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.books.acquire import acquire_book
        from on1y.exceptions import ConfigurationError

        title = str(body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        author = str(body.get("author") or "").strip() or None
        translator = str(body.get("translator") or "").strip() or None
        publisher = str(body.get("publisher") or "").strip() or None
        isbn = str(body.get("isbn") or "").strip() or None
        douban_url = str(body.get("douban_url") or "").strip() or None
        fmt = str(body.get("format") or "").strip().lower() or None
        add_to_shelf = bool(body.get("add_to_shelf", True))
        shelf_item_id = body.get("shelf_item_id")
        if shelf_item_id is not None:
            try:
                shelf_item_id = int(shelf_item_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="shelf_item_id must be an integer") from exc
        candidate = body.get("candidate")
        if candidate is not None and not isinstance(candidate, dict):
            raise HTTPException(status_code=400, detail="candidate must be an object")
        uid = get_effective_user_id()
        storage = get_storage()
        try:
            return acquire_book(
                uid,
                storage,
                title=title,
                author=author,
                translator=translator,
                publisher=publisher,
                isbn=isbn,
                douban_url=douban_url,
                fmt=fmt,
                add_to_shelf=add_to_shelf,
                candidate=candidate,
                shelf_item_id=shelf_item_id,
            )
        except ConfigurationError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("books_acquire failed for %r", title)
            raise HTTPException(status_code=502, detail=f"下载失败：{exc}") from exc
        finally:
            storage.close()

    @app.get("/api/digest/evening/status")
    def evening_digest_status_api() -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.digest.evening import evening_digest_status

        return evening_digest_status(get_effective_user_id())

    @app.get("/api/digest/evening/archive")
    def evening_digest_archive() -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.digest.evening import list_evening_digest_dates, today_digest_date

        uid = get_effective_user_id()
        dates = list_evening_digest_dates(uid, limit=60)
        return {"today": today_digest_date(), "dates": dates}

    @app.get("/api/digest/evening")
    def evening_digest_get(
        day: str | None = Query(default=None, min_length=10, max_length=10),
    ) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.digest.evening import (
            digest_hour_reached,
            load_evening_digest,
            public_evening_digest_view,
            today_digest_date,
        )

        uid = get_effective_user_id()
        digest_day = day or today_digest_date()
        today = today_digest_date()

        if digest_day == today and not digest_hour_reached():
            return {
                "pending": True,
                "digest_date": today,
                "reason": "before_digest_hour",
                "timezone": "Asia/Shanghai",
            }

        doc = load_evening_digest(uid, digest_day)
        if doc is None:
            if digest_day == today:
                return {
                    "pending": True,
                    "digest_date": today,
                    "reason": "not_generated_yet",
                    "timezone": "Asia/Shanghai",
                }
            raise HTTPException(status_code=404, detail=f"evening digest not found: {digest_day}")
        return public_evening_digest_view(doc)

    @app.post("/api/digest/evening/read")
    def evening_digest_mark_read(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.auth.context import get_effective_user_id
        from on1y.digest.evening import mark_evening_digest_read, public_evening_digest_view

        day = str(body.get("day") or "").strip()
        if len(day) != 10:
            raise HTTPException(status_code=400, detail="day required (YYYY-MM-DD)")
        doc = mark_evening_digest_read(get_effective_user_id(), day)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"evening digest not found: {day}")
        return public_evening_digest_view(doc)

    @app.post("/api/digest/evening/generate")
    def evening_digest_generate(
        day: str | None = Query(default=None, min_length=10, max_length=10),
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        import logging

        from on1y.adapters.sqlite_storage import get_storage
        from on1y.digest.evening import build_evening_digest, public_evening_digest_view

        logger = logging.getLogger(__name__)
        storage = get_storage()
        try:
            try:
                doc = build_evening_digest(storage, day=day, force=force)
                return public_evening_digest_view(doc)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                logger.exception("evening digest generate failed")
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.get("/api/stats/overview")
    def stats_overview(days: int = Query(default=90, ge=7, le=366)) -> dict[str, Any]:
        import logging

        from on1y.stats.overview import build_stats_overview

        logger = logging.getLogger(__name__)
        storage = get_storage()
        try:
            try:
                return build_stats_overview(storage, days=days)
            except Exception as exc:
                logger.exception("stats overview failed")
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.get("/api/stats/daily")
    def stats_daily(day: str = Query(..., min_length=10, max_length=10)) -> dict[str, Any]:
        import logging

        from on1y.stats.overview import build_daily_digest

        logger = logging.getLogger(__name__)
        storage = get_storage()
        try:
            try:
                return build_daily_digest(storage, day=day)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                logger.exception("stats daily failed")
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.get("/api/knowledge/creators")
    def knowledge_creators(
        enrich_avatars: bool = Query(default=False),
    ) -> dict[str, Any]:
        storage = get_storage()
        try:
            creators = storage.list_subscribed_creators(enrich_avatars=enrich_avatars)
            return {"creators": creators, "count": len(creators)}
        finally:
            storage.close()

    @app.get("/api/knowledge/items")
    def knowledge_items(
        limit: int = Query(default=40, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        platform: str | None = Query(default=None),
        source: str | None = Query(default=None),
        query: str | None = Query(default=None),
        theme_id: int | None = Query(default=None),
        tag_id: int | None = Query(default=None),
        creator_key: str | None = Query(default=None),
        include_descendants: bool = Query(default=False),
        collection: str = Query(default="feed"),
        hotlist_date: str | None = Query(default=None),
        hotlist_source: str = Query(default="zhihu"),
        feed_date: str | None = Query(default=None),
        unread_only: bool = Query(default=False),
        min_importance: int | None = Query(default=None, ge=1, le=5),
    ) -> dict[str, Any]:
        from on1y.hotlist.constants import SUPPORTED_HOTLIST_SOURCES

        storage = get_storage()
        try:
            coll = collection.strip().lower()
            if coll not in {
                "feed",
                "favorites",
                "trash",
                "hotlist",
                "unread",
                "notes",
                "continue",
            }:
                raise HTTPException(status_code=400, detail=f"unsupported collection: {collection}")
            hot_day: str | None = None
            hot_src: str | None = None
            feed_day: str | None = None
            if coll == "hotlist":
                from datetime import date as date_cls

                hot_src = hotlist_source.strip().lower()
                if hot_src not in SUPPORTED_HOTLIST_SOURCES:
                    raise HTTPException(
                        status_code=400, detail=f"unsupported hotlist_source: {hot_src}"
                    )
                hot_day = (hotlist_date or "").strip() or date_cls.today().isoformat()
                try:
                    date_cls.fromisoformat(hot_day)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail="invalid hotlist_date") from exc
            if feed_date and feed_date.strip() and coll == "feed":
                from datetime import date as date_cls

                from on1y.knowledge.feed_dates import parse_feed_date

                try:
                    feed_day = parse_feed_date(feed_date.strip()).isoformat()
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail="invalid feed_date") from exc
            tag_ids = [tag_id] if tag_id is not None else None
            if include_descendants and tag_id is not None:
                tag_ids = [tag_id]
            if query and query.strip():
                result = storage.search_knowledge_items(
                    query=query.strip(),
                    limit=limit,
                    offset=offset,
                    platform=platform,
                    source=source,
                    tag_ids=tag_ids,
                    theme_id=theme_id,
                    creator_key=creator_key,
                    collection=coll,
                    hotlist_date=hot_day,
                    hotlist_source=hot_src,
                    feed_date=feed_day,
                    unread_only=unread_only and coll == "feed",
                    min_importance=min_importance if coll == "feed" else None,
                )
                return {
                    "items": result["items"],
                    "count": len(result["items"]),
                    "total": result["total"],
                    "engine": result.get("engine", "fts5"),
                    "collection": coll,
                    "hotlist_date": hot_day,
                    "hotlist_source": hot_src,
                    "feed_date": feed_day,
                    "unread_only": unread_only and coll == "feed",
                    "min_importance": min_importance if coll == "feed" else None,
                }
            rows = storage.list_knowledge_items(
                limit=limit,
                offset=offset,
                platform=platform,
                source=source,
                tag_ids=tag_ids,
                theme_id=theme_id,
                creator_key=creator_key,
                collection=coll,
                hotlist_date=hot_day,
                hotlist_source=hot_src,
                feed_date=feed_day,
                unread_only=unread_only and coll == "feed",
                min_importance=min_importance if coll == "feed" else None,
            )
            total = storage.count_knowledge_items(
                platform=platform,
                source=source,
                tag_ids=tag_ids,
                theme_id=theme_id,
                creator_key=creator_key,
                collection=coll,
                hotlist_date=hot_day,
                hotlist_source=hot_src,
                feed_date=feed_day,
                unread_only=unread_only and coll == "feed",
                min_importance=min_importance if coll == "feed" else None,
            )
            return {
                "items": rows,
                "count": len(rows),
                "total": total,
                "collection": coll,
                "hotlist_date": hot_day,
                "hotlist_source": hot_src,
                "feed_date": feed_day,
                "unread_only": unread_only and coll == "feed",
                "min_importance": min_importance if coll == "feed" else None,
            }
        finally:
            storage.close()

    @app.post("/api/knowledge/search/rebuild")
    def rebuild_search_index() -> dict[str, Any]:
        from on1y.search.fts import rebuild_knowledge_fts

        storage = get_storage()
        try:
            conn = storage._connect()
            count = rebuild_knowledge_fts(conn)
            conn.commit()
            return {"rebuilt": count, "engine": "fts5-trigram"}
        finally:
            storage.close()

    @app.post("/api/knowledge/items/manual")
    def create_manual_item(body: ManualItemRequest) -> dict[str, Any]:
        from on1y.distill.processor import distill_raw_item

        storage = get_storage()
        try:
            raw = storage.upsert_raw_item(
                RawItemCreate(
                    url=(body.url or f"on1y://manual/{body.title[:48]}"),
                    platform=body.platform.strip() or "manual",
                    source=body.source,
                    raw_title=body.title.strip(),
                    body_text=body.body_text.strip(),
                    content_type=ContentType.ARTICLE,
                    extract_status=ExtractStatus.OK,
                    source_meta={"author": body.author or "", "manual": True},
                )
            )
            storage.set_item_classification(
                raw.id,
                theme_slug=body.theme_slug or (body.theme_slugs[0] if body.theme_slugs else None),
                tags=body.tags,
                source="manual",
            )
            distilled_id = None
            if body.auto_distill:
                distilled_id = distill_raw_item(storage, raw.id, force=True)
            return {
                "raw_id": raw.id,
                "url": raw.url,
                "distilled_id": distilled_id,
            }
        finally:
            storage.close()

    @app.post("/api/knowledge/items/{raw_id}/classification")
    def patch_item_classification(raw_id: int, body: ClassificationUpdate) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            storage.set_item_classification(
                raw_id,
                theme_slug=body.theme_slug or (body.theme_slugs[0] if body.theme_slugs else None),
                tags=body.tags,
                source="manual",
            )
            return {
                "raw_id": raw_id,
                "theme": body.theme_slug or (body.theme_slugs[0] if body.theme_slugs else None),
                "tags": len(body.tags),
            }
        finally:
            storage.close()

    @app.patch("/api/knowledge/items/{raw_id}/theme")
    def move_item_theme(raw_id: int, body: ThemeMoveRequest) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            theme_id = body.theme_id
            if theme_id is None and body.theme_slug:
                theme_id = storage.get_theme_id_by_slug(body.theme_slug.strip().lower())
            if theme_id is None:
                raise HTTPException(status_code=400, detail="theme_id or theme_slug required")
            storage.set_item_theme(raw_id, theme_id, source="user")
            theme = storage.get_theme_by_id(theme_id)
            return {"raw_id": raw_id, "theme": theme}
        finally:
            storage.close()

    @app.get(
        "/api/knowledge/items/{raw_id}/economist-epub",
        response_model=None,
        responses={404: {"description": "Item not found"}, 502: {"description": "Download failed"}},
    )
    def economist_epub_download(raw_id: int) -> Response:
        from on1y.hotlist.economist_urls import resolve_economist_epub_url
        from on1y.hotlist.epub_preview import (
            cache_epub,
            download_epub,
            load_cached_epub,
            resolve_economist_epub_cache_path,
        )

        import logging

        log = logging.getLogger(__name__)
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            if str(raw.platform) != "economist":
                raise HTTPException(status_code=404, detail="not an Economist item")
            meta = dict(raw.source_meta or {})
            epub_url = resolve_economist_epub_url(str(raw.url), meta)
            if not epub_url:
                raise HTTPException(status_code=404, detail="epub url missing")
            edition_date = str(meta.get("edition_date") or meta.get("heat_text") or "").strip()
            settings = get_settings()
            filename = Path(epub_url).name or "TheEconomist.epub"

            if edition_date:
                cached = resolve_economist_epub_cache_path(settings, edition_date)
                if cached is not None:
                    return FileResponse(
                        path=cached,
                        media_type="application/epub+zip",
                        filename=filename,
                    )

            blob = load_cached_epub(settings, edition_date) if edition_date else None
            if blob is None:
                try:
                    blob = download_epub(epub_url, settings=settings)
                except Exception as exc:
                    log.warning("EPUB download failed raw_id=%s url=%s: %s", raw_id, epub_url, exc)
                    raise HTTPException(
                        status_code=502,
                        detail=f"cannot download EPUB (check ON1Y_YTDLP_PROXY): {exc}",
                    ) from exc
                if edition_date and blob:
                    try:
                        cache_epub(blob, settings=settings, edition_date=edition_date)
                    except OSError as exc:
                        log.warning("EPUB cache write failed: %s", exc)

            if not blob:
                raise HTTPException(status_code=502, detail="empty EPUB response")

            return Response(
                content=blob,
                media_type="application/epub+zip",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except HTTPException:
            raise
        except Exception as exc:
            log.exception("economist-epub download failed raw_id=%s", raw_id)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            storage.close()

    @app.get("/api/knowledge/items/{raw_id}/related")
    def knowledge_item_related(
        raw_id: int,
        limit: int = Query(default=6, ge=1, le=12),
        scope: str = Query(default="library"),
    ) -> dict[str, Any]:
        from on1y.recommend.similar import find_related_items

        scope_key = (scope or "library").strip().lower()
        if scope_key not in {"library", "books"}:
            raise HTTPException(status_code=400, detail=f"unsupported scope: {scope}")

        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="not found")
            items = find_related_items(storage, from_raw_id=raw_id, limit=limit, scope=scope_key)
            return {"items": items, "scope": scope_key}
        finally:
            storage.close()

    @app.post("/api/knowledge/items/{from_raw_id}/related/{to_raw_id}/feedback")
    def knowledge_item_related_feedback(from_raw_id: int, to_raw_id: int) -> dict[str, Any]:
        from on1y.recommend.feedback import record_less_relevant

        storage = get_storage()
        try:
            for rid in (from_raw_id, to_raw_id):
                raw = storage.get_raw_by_id_for_user(rid)
                if raw is None:
                    raise HTTPException(status_code=404, detail="not found")
            conn = storage._connect()
            record_less_relevant(conn, from_raw_id=from_raw_id, to_raw_id=to_raw_id)
            conn.commit()
            return {"ok": True}
        finally:
            storage.close()

    @app.get("/api/knowledge/items/{raw_id}/reader")
    def knowledge_item_reader(raw_id: int) -> dict[str, Any]:
        from on1y.hotlist.economist_preview_store import ensure_economist_preview

        storage = get_storage()
        try:
            content = storage.get_reader_content(raw_id)
            if content is None:
                raise HTTPException(status_code=404, detail="not found")
            if str(content.get("platform") or "") == "economist":
                ensure_economist_preview(storage, raw_id)
                content = storage.get_reader_content(raw_id)
            if content is None:
                raise HTTPException(status_code=404, detail="not found")
            return content
        finally:
            storage.close()

    @app.post("/api/knowledge/items/{raw_id}/translate")
    def translate_item_transcript(raw_id: int) -> dict[str, Any]:
        from on1y.exceptions import ConfigurationError
        from on1y.translate.transcript import translate_body_to_zh
        from on1y.utils.transcript_meta import classify_transcript

        storage = get_storage()
        try:
            content = storage.get_reader_content(raw_id)
            if content is None:
                raise HTTPException(status_code=404, detail="not found")
            body_text = str(content.get("body_text") or "").strip()
            if not body_text:
                raise HTTPException(status_code=400, detail="no body text to translate")
            kind = classify_transcript(body_text)
            if kind == "none":
                raise HTTPException(status_code=400, detail="item has no subtitle transcript")
            if kind == "zh":
                raise HTTPException(status_code=400, detail="transcript is already Chinese")
            existing = str(content.get("translated_body_text") or "").strip()
            if existing:
                return {
                    "raw_id": raw_id,
                    "translated_body_text": existing,
                    "cached": True,
                }
            try:
                translated = translate_body_to_zh(body_text, title=content.get("title"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except ConfigurationError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            storage.merge_source_meta(raw_id, {"translated_body_text": translated})
            return {
                "raw_id": raw_id,
                "translated_body_text": translated,
                "cached": False,
            }
        finally:
            storage.close()

    @app.patch("/api/knowledge/items/{raw_id}/note")
    def patch_item_note(raw_id: int, body: ItemNoteUpdate) -> dict[str, Any]:
        from on1y.knowledge.importance import importance_from_meta, normalize_importance

        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            patch: dict[str, Any] = {}
            if "html" in body.model_fields_set:
                patch["user_note_html"] = body.html or ""
            if "importance" in body.model_fields_set:
                patch["importance"] = normalize_importance(body.importance)
            if not patch:
                raise HTTPException(status_code=400, detail="no fields to update")
            storage.merge_source_meta(raw_id, patch)
            meta = storage.get_raw_by_id(raw_id).source_meta or {}
            result: dict[str, Any] = {"raw_id": raw_id}
            if "html" in body.model_fields_set:
                result["user_note_html"] = patch.get("user_note_html", "")
            if "importance" in body.model_fields_set:
                result["importance"] = importance_from_meta(meta)
            return result
        finally:
            storage.close()

    @app.patch("/api/knowledge/items/{raw_id}/annotation")
    def patch_item_annotation(raw_id: int, body: ItemAnnotationUpdate) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            storage.merge_source_meta(raw_id, {"annotated_body_html": body.html})
            return {"raw_id": raw_id, "annotated_body_html": body.html}
        finally:
            storage.close()

    @app.patch("/api/knowledge/items/{raw_id}/favorite")
    def patch_item_favorite(raw_id: int, body: FavoriteUpdate) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            storage.merge_source_meta(raw_id, {"starred": body.starred})
            return {"raw_id": raw_id, "starred": body.starred}
        finally:
            storage.close()

    @app.patch("/api/knowledge/items/{raw_id}/importance")
    def patch_item_importance(raw_id: int, body: ImportanceUpdate) -> dict[str, Any]:
        from on1y.knowledge.importance import normalize_importance

        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            stars = normalize_importance(body.importance)
            storage.merge_source_meta(raw_id, {"importance": stars})
            return {"raw_id": raw_id, "importance": stars}
        finally:
            storage.close()

    @app.post("/api/knowledge/items/{raw_id}/importance")
    def post_item_importance(raw_id: int, body: ImportanceUpdate) -> dict[str, Any]:
        return patch_item_importance(raw_id, body)

    @app.patch("/api/knowledge/items/{raw_id}/read")
    def patch_item_read(raw_id: int, body: ReadStateUpdate) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            return storage.set_item_read_state(raw_id, read=body.read)
        finally:
            storage.close()

    @app.post("/api/knowledge/items/{raw_id}/read")
    def post_item_read(raw_id: int) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            return storage.touch_item_reading(raw_id)
        finally:
            storage.close()

    @app.post("/api/knowledge/items/batch-delete")
    def batch_delete_knowledge_items(body: BatchDeleteRequest) -> dict[str, Any]:
        storage = get_storage()
        try:
            counts = storage.delete_raw_items(body.raw_ids)
            return {"raw_ids": body.raw_ids, **counts}
        finally:
            storage.close()

    @app.post("/api/knowledge/items/batch-restore")
    def batch_restore_knowledge_items(body: BatchRestoreRequest) -> dict[str, Any]:
        storage = get_storage()
        try:
            counts = storage.restore_raw_items(body.raw_ids)
            return {"raw_ids": body.raw_ids, **counts}
        finally:
            storage.close()

    @app.post("/api/knowledge/items/{raw_id}/restore")
    def restore_knowledge_item(raw_id: int) -> dict[str, Any]:
        storage = get_storage()
        try:
            if not storage.restore_raw_item(raw_id):
                raise HTTPException(status_code=404, detail="item not in trash")
            return {"raw_id": raw_id, "restored": True}
        finally:
            storage.close()

    @app.delete("/api/knowledge/items/{raw_id}")
    def delete_knowledge_item(raw_id: int) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id_for_user(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            storage.delete_raw_item(raw_id)
            return {"raw_id": raw_id, "deleted": True}
        finally:
            storage.close()

    @app.post("/api/knowledge/items/{raw_id}/tags")
    def patch_item_tags(raw_id: int, body: ClassificationUpdate) -> dict[str, Any]:
        """Backward-compatible alias."""
        return patch_item_classification(raw_id, body)

    if _multipart_installed():

        @app.post("/api/knowledge/upload")
        async def upload_document(
            file: UploadFile = File(...),
            auto_distill: bool = Query(default=True),
        ) -> dict[str, Any]:
            from on1y.distill.processor import distill_raw_item

            settings = get_settings()
            settings.ensure_data_dir()
            uploads_dir = settings.data_dir / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            if not file.filename:
                raise HTTPException(status_code=400, detail="missing filename")
            data = await file.read()
            safe_name = Path(file.filename).name
            target = uploads_dir / safe_name
            target.write_bytes(data)

            decoded_body = ""
            if (file.content_type and file.content_type.startswith("text/")) or safe_name.endswith(
                (".md", ".txt", ".csv")
            ):
                decoded_body = data.decode("utf-8", errors="ignore")
            else:
                decoded_body = (
                    f"Uploaded file: {file.filename}\n"
                    f"content_type={file.content_type or 'application/octet-stream'}\n"
                    "Text extraction for this format can be plugged in later."
                )

            storage = get_storage()
            try:
                raw = storage.upsert_raw_item(
                    RawItemCreate(
                        url=f"on1y://upload/{target.name}",
                        platform="upload",
                        source=SourceType.MANUAL,
                        raw_title=safe_name,
                        body_text=decoded_body,
                        content_type=ContentType.ARTICLE,
                        extract_status=ExtractStatus.OK,
                        source_meta={"file_path": str(target), "file_name": safe_name},
                    )
                )
                distilled_id = None
                if auto_distill:
                    distilled_id = distill_raw_item(storage, raw.id, force=True)
                return {
                    "raw_id": raw.id,
                    "distilled_id": distilled_id,
                    "file_name": safe_name,
                    "saved_to": str(target),
                }
            finally:
                storage.close()

    else:

        @app.post("/api/knowledge/upload")
        async def upload_document_unavailable() -> dict[str, Any]:
            raise HTTPException(
                status_code=501,
                detail=(
                    'Upload requires dependency "python-multipart". '
                    "Run: pip install python-multipart"
                ),
            )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    from on1y.web.frontend_static import frontend_out_available, register_frontend_routes

    register_frontend_routes(app)
    if frontend_out_available():
        logger.info("Serving Next.js workbench from frontend/out")
    if not frontend_out_available() and STATIC_DIR.is_dir():
        legacy_index = STATIC_DIR / "legacy-dashboard.html"
        if legacy_index.is_file():

            @app.get("/")
            def legacy_dashboard() -> FileResponse:
                return FileResponse(legacy_index)

    return app


def run_server(*, host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    from on1y.digest.evening_auto import start_evening_digest_loop
    from on1y.hotlist.economist_auto import start_economist_auto_loop
    from on1y.subscriptions.auto_sync import start_auto_sync_loop
    from on1y.subscriptions.collections_auto_sync import start_collections_sync_loop

    settings = get_settings()
    settings.ensure_data_dir()
    get_storage().close()
    start_auto_sync_loop()
    start_collections_sync_loop()
    start_economist_auto_loop()
    start_evening_digest_loop()
    uvicorn.run(
        create_app(),
        host=host or settings.web_host,
        port=port or settings.web_port,
        log_level=settings.log_level.lower(),
    )
