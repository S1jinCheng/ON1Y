"""FastAPI routes for the Paper module."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)


def register_paper_routes(app: FastAPI) -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import get_effective_user_id

    @app.get("/api/papers")
    def papers_list(
        status: str | None = Query(default=None),
        query: str | None = Query(default=None),
        collection_key: str | None = Query(default=None),
        folder_key: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        from on1y.papers.models import paper_dump
        from on1y.papers.literature import sync_published_to_shelf
        from on1y.papers.shelf import (
            count_papers,
            list_paper_collections,
            list_paper_folders,
            list_papers,
        )

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            try:
                sync_published_to_shelf(storage, uid)
            except Exception:
                # A disconnected custom Vault must not make the existing shelf unusable.
                logger.exception("Could not project Literature Vault into Paper shelf")
            items = list_papers(
                storage,
                uid,
                status=status,
                query=query,
                collection_key=collection_key,
                folder_key=folder_key,
                limit=limit,
                offset=offset,
            )
            return {
                "items": [paper_dump(item) for item in items],
                "total": count_papers(storage, uid),
                "collections": list_paper_collections(storage, uid),
                "folders": list_paper_folders(storage, uid),
            }
        finally:
            storage.close()

    @app.get("/api/papers/item/{item_id}")
    def papers_get(item_id: int) -> dict[str, Any]:
        from on1y.papers.knowledge_sync import prepare_paper
        from on1y.papers.models import paper_dump
        from on1y.papers.shelf import get_paper

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = get_paper(storage, uid, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="paper not found")
            return paper_dump(prepare_paper(storage, uid, item))
        finally:
            storage.close()

    @app.post("/api/papers")
    def papers_create(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.knowledge_sync import prepare_paper
        from on1y.papers.models import PaperCreate, paper_dump
        from on1y.papers.shelf import create_paper

        try:
            payload = PaperCreate.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uid = get_effective_user_id()
        storage = get_storage()
        try:
            return paper_dump(prepare_paper(storage, uid, create_paper(storage, uid, payload)))
        finally:
            storage.close()

    @app.patch("/api/papers/{item_id}")
    def papers_update(item_id: int, body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.knowledge_sync import prepare_paper, sync_paper_note, sync_paper_tags
        from on1y.papers.models import PaperUpdate, paper_dump
        from on1y.papers.shelf import get_paper, update_paper

        try:
            payload = PaperUpdate.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uid = get_effective_user_id()
        storage = get_storage()
        try:
            existing = get_paper(storage, uid, item_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="paper not found")
            if payload.status is not None and existing.literature_paper_id:
                from on1y.papers.literature import LiteratureVault

                LiteratureVault(uid).set_paper_statuses(
                    [existing.literature_paper_id], payload.status
                )
            item = update_paper(storage, uid, item_id, payload)
            if item is None:
                raise HTTPException(status_code=404, detail="paper not found")
            if payload.tags is not None:
                item = sync_paper_tags(storage, uid, item_id, payload.tags) or item
            if "user_note_html" in payload.model_fields_set:
                item = sync_paper_note(storage, uid, item) or item
            if payload.model_fields_set.intersection(
                {"title", "authors", "abstract", "doi", "url", "venue", "year"}
            ):
                item = prepare_paper(storage, uid, item)
            elif payload.tags is None and "user_note_html" not in payload.model_fields_set:
                item = get_paper(storage, uid, item_id) or item
            return paper_dump(item)
        finally:
            storage.close()

    @app.post("/api/papers/bulk-status")
    def papers_bulk_status(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault, sync_published_to_shelf
        from on1y.papers.shelf import bulk_update_paper_status, get_paper

        status = str(body.get("status") or "").strip()
        if status not in {"to_read", "reading", "read", "dismissed"}:
            raise HTTPException(status_code=400, detail="invalid paper status")
        raw_item_ids = body.get("item_ids") or []
        raw_literature_ids = body.get("literature_paper_ids") or []
        if not isinstance(raw_item_ids, list) or not isinstance(raw_literature_ids, list):
            raise HTTPException(status_code=400, detail="paper ids must be lists")
        try:
            item_ids = list(dict.fromkeys(int(value) for value in raw_item_ids))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid item id") from exc
        literature_ids = list(
            dict.fromkeys(str(value).strip() for value in raw_literature_ids if str(value).strip())
        )
        if len(item_ids) + len(literature_ids) > 500:
            raise HTTPException(status_code=400, detail="at most 500 papers can be updated")
        uid = get_effective_user_id()
        storage = get_storage()
        try:
            for item_id in item_ids:
                item = get_paper(storage, uid, item_id)
                if item is None:
                    raise HTTPException(status_code=404, detail=f"paper not found: {item_id}")
                if item.literature_paper_id:
                    literature_ids.append(item.literature_paper_id)
            literature_ids = list(dict.fromkeys(literature_ids))
            vault_result = {"updated": 0, "affected_batches": []}
            if literature_ids:
                try:
                    vault_result = LiteratureVault(uid).set_paper_statuses(
                        literature_ids, status
                    )
                except LookupError as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                sync_published_to_shelf(storage, uid)
            updated_items = bulk_update_paper_status(storage, uid, item_ids, status)
            return {
                "status": status,
                "updated": len(set(item_ids)) + len(
                    [value for value in literature_ids if value not in {
                        item.literature_paper_id for item in updated_items
                    }]
                ),
                "item_ids": [item.id for item in updated_items],
                "literature_paper_ids": literature_ids,
                "affected_batches": vault_result.get("affected_batches", []),
            }
        finally:
            storage.close()

    @app.post("/api/papers/{item_id}/figures/extract")
    def papers_extract_figures(item_id: int) -> dict[str, Any]:
        from on1y.papers.figures import extract_figures_for_paper
        from on1y.papers.models import paper_dump

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            try:
                return paper_dump(extract_figures_for_paper(storage, uid, item_id))
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=502, detail="图表识别失败，请稍后重试") from exc
        finally:
            storage.close()

    @app.get("/api/papers/{item_id}/figures/{filename}")
    def papers_figure(
        item_id: int,
        filename: str,
        download: bool = Query(default=False),
    ) -> FileResponse:
        from on1y.papers.figures import paper_figure_dir
        from on1y.papers.shelf import get_paper

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = get_paper(storage, uid, item_id)
            allowed = {figure.filename for figure in item.figures} if item else set()
            if filename not in allowed or Path(filename).name != filename:
                raise HTTPException(status_code=404, detail="figure not found")
            path = paper_figure_dir(uid, item_id) / filename
            if not path.is_file():
                raise HTTPException(status_code=404, detail="figure not found")
            return FileResponse(
                path,
                media_type="image/png",
                filename=filename if download else None,
                content_disposition_type="attachment" if download else "inline",
            )
        finally:
            storage.close()

    @app.delete("/api/papers/{item_id}")
    def papers_delete(item_id: int) -> dict[str, bool]:
        from on1y.papers.shelf import delete_paper

        storage = get_storage()
        try:
            if not delete_paper(storage, get_effective_user_id(), item_id):
                raise HTTPException(status_code=404, detail="paper not found")
            return {"ok": True}
        finally:
            storage.close()

    @app.get("/api/papers/{item_id}/related")
    def papers_related(item_id: int, limit: int = Query(default=6, ge=1, le=12)) -> dict[str, Any]:
        from on1y.papers.knowledge_sync import prepare_paper
        from on1y.papers.shelf import get_paper
        from on1y.recommend.similar import find_related_items

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = get_paper(storage, uid, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="paper not found")
            if item.raw_id is None:
                item = prepare_paper(storage, uid, item)
            if item.raw_id is None:
                return {"items": [], "scope": "library", "from_raw_id": None}
            return {
                "items": find_related_items(
                    storage, from_raw_id=item.raw_id, limit=limit, scope="library"
                ),
                "scope": "library",
                "from_raw_id": item.raw_id,
            }
        finally:
            storage.close()

    @app.post("/api/papers/upload")
    async def papers_upload(
        file: UploadFile = File(...),
        title: str = Form(default=""),
        authors: str = Form(default=""),
        status: str = Form(default="to_read"),
    ) -> dict[str, Any]:
        from on1y.papers.local_sync import import_pdf, safe_pdf_name, validate_pdf
        from on1y.papers.models import paper_dump
        from on1y.papers.settings_store import load_paper_settings, resolve_paper_cache_dir

        filename = str(file.filename or "").strip()
        if Path(filename).suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="仅支持 PDF 文件")
        if status not in {"to_read", "reading", "read", "dismissed"}:
            raise HTTPException(status_code=400, detail="invalid paper status")
        uid = get_effective_user_id()
        settings = load_paper_settings(uid)
        folder = resolve_paper_cache_dir(uid, settings.cache_dir)
        paper_title = title.strip() or Path(filename).stem.strip() or "未命名论文"
        temporary = folder / f".on1y-paper-{uuid4().hex}.uploading"
        destination: Path | None = None
        try:
            total = 0
            with temporary.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > 500 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="PDF 超过 500MB 上传上限")
                    output.write(chunk)
            validate_pdf(temporary)
            destination = folder / safe_pdf_name(paper_title)
            index = 2
            while destination.exists():
                destination = folder / safe_pdf_name(f"{paper_title} ({index})")
                index += 1
            temporary.replace(destination)
            result = import_pdf(
                uid,
                destination,
                title=paper_title,
                authors=[
                    part.strip() for part in authors.replace("；", ";").split(";") if part.strip()
                ],
                status=status,
            )
            return {
                "ok": True,
                "paper": paper_dump(result["paper"]),
                "local_path": result["local_path"],
            }
        except HTTPException:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if destination is not None and destination.is_file():
                destination.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"论文入库失败：{exc}") from exc

    @app.get("/api/papers/settings")
    def papers_settings_get() -> dict[str, Any]:
        from on1y.papers.settings_store import (
            literature_vault_status,
            load_paper_settings,
            paper_settings_public_view,
            resolve_paper_cache_dir,
        )
        from on1y.papers.translation import translation_worker_status

        uid = get_effective_user_id()
        settings = load_paper_settings(uid)
        payload = paper_settings_public_view(settings)
        payload["resolved_cache_dir"] = str(resolve_paper_cache_dir(uid, settings.cache_dir))
        payload["literature_vault"] = literature_vault_status(uid)
        payload["translation_worker"] = translation_worker_status(
            settings.translation_babeldoc_executable
        )
        return payload

    @app.put("/api/papers/settings")
    def papers_settings_put(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.settings_store import (
            PaperSettings,
            literature_vault_status,
            load_paper_settings,
            paper_settings_public_view,
            resolve_paper_cache_dir,
            save_paper_settings,
        )
        from on1y.papers.translation import translation_worker_status

        uid = get_effective_user_id()
        current = load_paper_settings(uid)
        allowed = set(PaperSettings.model_fields) - {"version"}
        updates = {key: value for key, value in body.items() if key in allowed}
        if not str(updates.get("translation_api_key") or "").strip():
            updates.pop("translation_api_key", None)
        if body.get("clear_translation_api_key"):
            updates["translation_api_key"] = None
        try:
            settings = PaperSettings.model_validate(current.model_copy(update=updates).model_dump())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_paper_settings(uid, settings)
        payload = paper_settings_public_view(settings)
        payload["resolved_cache_dir"] = str(resolve_paper_cache_dir(uid, settings.cache_dir))
        payload["literature_vault"] = literature_vault_status(uid)
        payload["translation_worker"] = translation_worker_status(
            settings.translation_babeldoc_executable
        )
        return payload

    @app.post("/api/papers/literature/init")
    def literature_init() -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        try:
            return LiteratureVault(get_effective_user_id()).initialize()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/papers/literature/config")
    def literature_config_get() -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        return LiteratureVault(get_effective_user_id()).config()

    @app.put("/api/papers/literature/config")
    def literature_config_put(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        try:
            return LiteratureVault(get_effective_user_id()).update_config(
                daily_target=int(body.get("daily_target"))
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/papers/literature/daily-plan")
    def literature_daily_plan(
        target_date: str = Query(..., alias="date"),
        field: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        try:
            return LiteratureVault(get_effective_user_id()).daily_plan(
                target_date=target_date,
                field=field,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/papers/literature/validate")
    def literature_validate(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        records = body.get("papers")
        if not isinstance(records, list):
            raise HTTPException(status_code=400, detail="papers must be a list")
        return LiteratureVault(get_effective_user_id()).validate(records)

    @app.get("/api/papers/literature/batches")
    def literature_batches() -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        return {"items": LiteratureVault(get_effective_user_id()).list_batches()}

    @app.post("/api/papers/literature/batches")
    def literature_create_batch(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        records = body.get("papers")
        if not isinstance(records, list):
            raise HTTPException(status_code=400, detail="papers must be a list")
        try:
            return LiteratureVault(get_effective_user_id()).create_batch(
                field=str(body.get("field") or "").strip(),
                field_code=str(body.get("field_code") or "").strip(),
                batch_date=str(body.get("batch_date") or "").strip(),
                records=records,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/papers/literature/batches/{batch_id}")
    def literature_get_batch(batch_id: str) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        result = LiteratureVault(get_effective_user_id()).batch(batch_id)
        if result is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return result

    @app.post("/api/papers/literature/batches/{batch_id}/publish")
    def literature_publish_batch(batch_id: str) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault, sync_published_to_shelf

        uid = get_effective_user_id()
        vault = LiteratureVault(uid)
        try:
            result = vault.publish(batch_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        storage = get_storage()
        try:
            sync_published_to_shelf(storage, uid, vault=vault, batch_id=batch_id)
        finally:
            storage.close()
        return result

    @app.get("/api/papers/literature/batches/{batch_id}/translations")
    def literature_translation_status(batch_id: str) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        try:
            return LiteratureVault(get_effective_user_id()).translation_status(batch_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/papers/literature/batches/{batch_id}/translations")
    def literature_enqueue_translations(
        batch_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        try:
            return LiteratureVault(get_effective_user_id()).enqueue_translations(
                batch_id,
                force=bool((body or {}).get("force")),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/papers/literature/translations/{job_id}/retry")
    def literature_retry_translation(job_id: str) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        try:
            return LiteratureVault(get_effective_user_id()).retry_translation_job(job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/papers/literature/batches/{batch_id}/feedback")
    def literature_feedback(batch_id: str) -> dict[str, Any]:
        from on1y.papers.literature import LiteratureVault

        try:
            return LiteratureVault(get_effective_user_id()).rebuild_feedback(batch_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/papers/folder-sync")
    def papers_folder_sync() -> dict[str, Any]:
        from on1y.papers.local_sync import scan_paper_folder

        return scan_paper_folder(get_effective_user_id())

    @app.post("/api/papers/zotero-sync")
    def papers_zotero_sync() -> dict[str, Any]:
        from on1y.papers.settings_store import load_paper_settings
        from on1y.papers.zotero import sync_zotero

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            try:
                return sync_zotero(storage, uid, load_paper_settings(uid))
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=502, detail=f"Zotero 返回 {exc.response.status_code}"
                ) from exc
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Zotero 同步失败：{exc}") from exc
        finally:
            storage.close()
