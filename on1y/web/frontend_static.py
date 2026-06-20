"""Serve Next.js static export from frontend/out via FastAPI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from on1y.config import PROJECT_ROOT

FRONTEND_OUT_DIR = PROJECT_ROOT / "frontend" / "out"
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


def _file_response(path: Path) -> FileResponse:
    suffix = path.suffix.lower()
    headers = dict(_NO_CACHE_HEADERS) if suffix in {".html", ""} else {}
    return FileResponse(path, headers=headers or None)


def frontend_out_available() -> bool:
    return (FRONTEND_OUT_DIR / "index.html").is_file()


def register_frontend_routes(app: FastAPI) -> None:
    """Mount exported UI at / (API routes must be registered first)."""
    if not frontend_out_available():
        return

    out_root = FRONTEND_OUT_DIR.resolve()

    def _safe_path(rel: str) -> Path | None:
        rel = (rel or "").strip().lstrip("/")
        if not rel:
            return out_root / "index.html"
        candidate = (out_root / rel).resolve()
        if not str(candidate).startswith(str(out_root)):
            return None
        return candidate

    @app.get("/", include_in_schema=False, name="on1y_workbench_root")
    async def frontend_root() -> FileResponse:
        return _file_response(out_root / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False, name="on1y_workbench_path")
    async def frontend_path(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        target = _safe_path(full_path)
        if target is None:
            raise HTTPException(status_code=404, detail="not found")
        if target.is_file():
            return _file_response(target)
        nested = _safe_path(f"{full_path.rstrip('/')}/index.html")
        if nested is not None and nested.is_file():
            return _file_response(nested)
        html_file = _safe_path(f"{full_path.rstrip('/')}.html")
        if html_file is not None and html_file.is_file():
            return _file_response(html_file)
        return _file_response(out_root / "index.html")
