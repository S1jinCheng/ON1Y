"""FastAPI routes for the Paper module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile


def register_paper_routes(app: FastAPI) -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.auth.context import get_effective_user_id

    @app.get("/api/papers")
    def papers_list(
        status: str | None = Query(default=None),
        query: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        from on1y.papers.models import paper_dump
        from on1y.papers.shelf import count_papers, list_papers

        uid = get_effective_user_id()
        storage = get_storage()
        try:
            items = list_papers(
                storage, uid, status=status, query=query, limit=limit, offset=offset
            )
            return {
                "items": [paper_dump(item) for item in items],
                "total": count_papers(storage, uid),
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
        from on1y.papers.knowledge_sync import prepare_paper, sync_paper_tags
        from on1y.papers.models import PaperUpdate, paper_dump
        from on1y.papers.shelf import get_paper, update_paper

        try:
            payload = PaperUpdate.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uid = get_effective_user_id()
        storage = get_storage()
        try:
            item = update_paper(storage, uid, item_id, payload)
            if item is None:
                raise HTTPException(status_code=404, detail="paper not found")
            if payload.tags is not None:
                item = sync_paper_tags(storage, uid, item_id, payload.tags) or item
            elif payload.model_fields_set.intersection(
                {"title", "authors", "abstract", "doi", "url", "venue", "year"}
            ):
                item = prepare_paper(storage, uid, item)
            else:
                item = get_paper(storage, uid, item_id) or item
            return paper_dump(item)
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
        if status not in {"to_read", "reading", "read"}:
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
        from on1y.papers.settings_store import load_paper_settings, resolve_paper_cache_dir

        uid = get_effective_user_id()
        settings = load_paper_settings(uid)
        payload = settings.model_dump()
        payload["resolved_cache_dir"] = str(resolve_paper_cache_dir(uid, settings.cache_dir))
        return payload

    @app.put("/api/papers/settings")
    def papers_settings_put(body: dict[str, Any]) -> dict[str, Any]:
        from on1y.papers.settings_store import (
            PaperSettings,
            load_paper_settings,
            resolve_paper_cache_dir,
            save_paper_settings,
        )

        uid = get_effective_user_id()
        current = load_paper_settings(uid)
        allowed = set(PaperSettings.model_fields) - {"version"}
        try:
            settings = PaperSettings.model_validate(
                current.model_copy(
                    update={key: value for key, value in body.items() if key in allowed}
                ).model_dump()
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_paper_settings(uid, settings)
        payload = settings.model_dump()
        payload["resolved_cache_dir"] = str(resolve_paper_cache_dir(uid, settings.cache_dir))
        return payload

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
