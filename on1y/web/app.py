"""Local web dashboard for RSS subscriptions, queue, and raw_items."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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


class SubscriptionSettingsRequest(BaseModel):
    bilibili_sync_since: str | None = None
    youtube_sync_since: str | None = None
    zhihu_sync_since: str | None = None


class SubscriptionSyncRequest(BaseModel):
    platform: str = "bilibili"
    backfill: bool = False
    ingest: bool = False
    ingest_limit: int = Field(default=10, ge=1, le=50)
    subtitle_limit: int = Field(default=10, ge=0, le=50)
    distill_limit: int = Field(default=10, ge=0, le=50)
    refresh_feeds: bool = False
    sync_hotlist: bool = False


class DistillBackfillRequest(BaseModel):
    platform: str | None = "bilibili"
    batch_size: int = Field(default=10, ge=1, le=20)
    max_items: int = Field(default=500, ge=1, le=1000)


class HotlistSyncRequest(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["zhihu"])
    auto_distill: bool = False


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


class ThemeUpdateRequest(BaseModel):
    name_zh: str | None = None
    name_en: str | None = None
    description_zh: str | None = None
    description_en: str | None = None
    sort_order: int | None = None


class ThemeMoveRequest(BaseModel):
    theme_id: int | None = None
    theme_slug: str | None = None


class ItemNoteUpdate(BaseModel):
    html: str = ""


class ItemAnnotationUpdate(BaseModel):
    html: str = ""


class FavoriteUpdate(BaseModel):
    starred: bool = False


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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

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
            raw = storage.get_raw_by_id(item_id)
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
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": True, **public_settings_view()}

    @app.post("/api/subscriptions/sync")
    def subscription_sync(body: SubscriptionSyncRequest) -> dict[str, Any]:
        from on1y.config import get_settings
        from on1y.subscriptions.sync_job import start_subscription_sync_job

        allowed = {"bilibili", "youtube", "zhihu", "all"}
        if body.platform not in allowed:
            raise HTTPException(status_code=400, detail=f"unsupported platform: {body.platform}")

        settings = get_settings()
        if body.platform in {"bilibili", "all"} and not settings.bilibili_up_sync_enabled:
            raise HTTPException(
                status_code=400,
                detail="Bilibili UP sync disabled (set ON1Y_BILIBILI_UP_SYNC_ENABLED=true)",
            )

        return start_subscription_sync_job(
            platform=body.platform,
            backfill=body.backfill,
            ingest=body.ingest,
            ingest_limit=body.ingest_limit,
            subtitle_limit=body.subtitle_limit,
            distill_limit=body.distill_limit,
            sync_hotlist=body.sync_hotlist,
            refresh_feeds=body.refresh_feeds or None,
        )

    @app.post("/api/hotlist/sync")
    def hotlist_sync(body: HotlistSyncRequest) -> dict[str, Any]:
        from on1y.hotlist import sync_hotlists

        storage = get_storage()
        try:
            return sync_hotlists(
                storage,
                sources=body.sources or ["zhihu"],
                auto_distill=body.auto_distill,
            )
        finally:
            storage.close()

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
        from on1y.distill.batch_job import start_distill_batch_job

        return start_distill_batch_job(
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
    def knowledge_themes_create(body: ThemeCreateRequest) -> dict[str, Any]:
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
            return {"theme": row}
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

    @app.get("/api/knowledge/collections")
    def knowledge_collections() -> dict[str, Any]:
        storage = get_storage()
        try:
            return {
                "favorites": storage.count_collection_items("favorites"),
                "trash": storage.count_collection_items("trash"),
            }
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
        include_descendants: bool = Query(default=False),
        collection: str = Query(default="feed"),
    ) -> dict[str, Any]:
        storage = get_storage()
        try:
            coll = collection.strip().lower()
            if coll not in {"feed", "favorites", "trash"}:
                raise HTTPException(status_code=400, detail=f"unsupported collection: {collection}")
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
                    collection=coll,
                )
                return {
                    "items": result["items"],
                    "count": len(result["items"]),
                    "total": result["total"],
                    "engine": result.get("engine", "fts5"),
                    "collection": coll,
                }
            rows = storage.list_knowledge_items(
                limit=limit,
                offset=offset,
                platform=platform,
                source=source,
                tag_ids=tag_ids,
                theme_id=theme_id,
                collection=coll,
            )
            return {"items": rows, "count": len(rows), "collection": coll}
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
            raw = storage.get_raw_by_id(raw_id)
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
            raw = storage.get_raw_by_id(raw_id)
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

    @app.get("/api/knowledge/items/{raw_id}/reader")
    def knowledge_item_reader(raw_id: int) -> dict[str, Any]:
        storage = get_storage()
        try:
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
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            storage.merge_source_meta(raw_id, {"user_note_html": body.html})
            return {"raw_id": raw_id, "user_note_html": body.html}
        finally:
            storage.close()

    @app.patch("/api/knowledge/items/{raw_id}/annotation")
    def patch_item_annotation(raw_id: int, body: ItemAnnotationUpdate) -> dict[str, Any]:
        storage = get_storage()
        try:
            raw = storage.get_raw_by_id(raw_id)
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
            raw = storage.get_raw_by_id(raw_id)
            if raw is None:
                raise HTTPException(status_code=404, detail="raw item not found")
            storage.merge_source_meta(raw_id, {"starred": body.starred})
            return {"raw_id": raw_id, "starred": body.starred}
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
            raw = storage.get_raw_by_id(raw_id)
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

    return app


def run_server(*, host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    from on1y.subscriptions.auto_sync import start_auto_sync_loop

    settings = get_settings()
    settings.ensure_data_dir()
    start_auto_sync_loop()
    uvicorn.run(
        create_app(),
        host=host or settings.web_host,
        port=port or settings.web_port,
        log_level=settings.log_level.lower(),
    )
