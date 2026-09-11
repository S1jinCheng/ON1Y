"""Local PaddleOCR layout detection and atomic Paper figure extraction."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.config import PROJECT_ROOT, get_settings
from on1y.papers.models import PaperFigure, PaperItem
from on1y.papers.shelf import get_paper
from on1y.user.paths import user_dir
from on1y.utils.json_util import dumps_json

logger = logging.getLogger(__name__)

MODEL_NAME = "PP-DocLayout-M"
EXTRACTOR_VERSION = 1
RENDER_SCALE = 2.0
MAX_FIGURES = 24

_CAPTION_RE = re.compile(
    r"^\s*(?:fig(?:ure)?|table|图|表)\.?\s*(?:S?\d+[A-Za-z]?|[IVX]+)",
    re.IGNORECASE,
)
_VISUAL_LABELS = {"image", "figure", "chart", "table"}
_CAPTION_LABELS = {
    "figure_caption",
    "figure_title",
    "figure_table_title",
    "table_caption",
    "table_title",
}

_MODEL: Any | None = None
_MODEL_LOCK = threading.Lock()
_INFERENCE_LOCK = threading.Lock()
_ITEM_LOCKS_GUARD = threading.Lock()
_ITEM_LOCKS: dict[tuple[int, int], threading.Lock] = {}


@dataclass(frozen=True)
class _Region:
    label: str
    score: float
    box: tuple[float, float, float, float]
    caption_index: int | None = None


@dataclass(frozen=True)
class _Caption:
    label: str
    score: float
    box: tuple[float, float, float, float]
    text: str


def paper_figure_dir(user_id: int, item_id: int) -> Path:
    """Return the private per-paper figure directory."""
    return user_dir(user_id) / "papers" / "figures" / str(item_id)


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def _ascii_model_root() -> Path:
    """Paddle's Windows native runtime cannot reliably open non-ASCII model paths."""
    candidates = [
        get_settings().data_dir / "models",
        Path(os.environ.get("PUBLIC") or "C:/Users/Public") / "On1y" / "models",
    ]
    for candidate in candidates:
        if not str(candidate).isascii():
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("无法创建 PaddleOCR 模型目录")


def _valid_model_dir(path: Path) -> bool:
    return (path / "inference.json").is_file() and (path / "inference.pdiparams").is_file()


def _ensure_model_dir() -> Path:
    target = _ascii_model_root() / MODEL_NAME
    if _valid_model_dir(target):
        return target

    staging = target.parent / f".{MODEL_NAME}-{uuid4().hex}.tmp"
    source = PROJECT_ROOT / "models" / MODEL_NAME
    try:
        if _valid_model_dir(source):
            shutil.copytree(source, staging)
        else:
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=f"PaddlePaddle/{MODEL_NAME}", local_dir=str(staging))
        if not _valid_model_dir(staging):
            raise RuntimeError("PaddleOCR 布局模型下载不完整")
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return target


def _layout_model() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import LayoutDetection

        _MODEL = LayoutDetection(
            model_name=MODEL_NAME,
            model_dir=str(_ensure_model_dir()),
            device="cpu",
            enable_mkldnn=True,
            cpu_threads=min(8, max(1, os.cpu_count() or 1)),
        )
        return _MODEL


def _predict_layout(image_path: Path) -> list[dict[str, Any]]:
    with _INFERENCE_LOCK:
        results = list(_layout_model().predict(str(image_path), batch_size=1, layout_nms=True))
    if not results:
        return []
    payload = results[0].json
    if not isinstance(payload, dict):
        return []
    result = payload.get("res")
    boxes = result.get("boxes") if isinstance(result, dict) else None
    return [row for row in boxes or [] if isinstance(row, dict)]


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    return max(0.0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0.0, min(first[3], second[3]) - max(first[1], second[1])
    )


def _iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    overlap = _intersection_area(first, second)
    return overlap / max(1.0, _area(first) + _area(second) - overlap)


def _containment(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    return _intersection_area(first, second) / max(1.0, min(_area(first), _area(second)))


def _union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _horizontal_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    overlap = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    return overlap / max(1.0, min(first[2] - first[0], second[2] - second[0]))


def _clean_caption(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:600]


def _box_from_row(
    row: dict[str, Any], width: int, height: int
) -> tuple[float, float, float, float] | None:
    raw = row.get("coordinate")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    box = (
        max(0.0, min(float(width), x0)),
        max(0.0, min(float(height), y0)),
        max(0.0, min(float(width), x1)),
        max(0.0, min(float(height), y1)),
    )
    return box if box[2] > box[0] and box[3] > box[1] else None


def _native_captions(page: Any, scale: float) -> list[_Caption]:
    captions: list[_Caption] = []
    page_dict = page.get_text("dict")
    for block in page_dict.get("blocks") or []:
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines") or []:
            text = _clean_caption(
                "".join(str(span.get("text") or "") for span in line.get("spans") or [])
            )
            if not text or not _CAPTION_RE.match(text):
                continue
            rect = line.get("bbox") or block.get("bbox") or (0, 0, 0, 0)
            box = tuple(float(value) * scale for value in rect)
            is_table = text.casefold().startswith("table") or text.startswith("表")
            label = "table_caption" if is_table else "figure_caption"
            captions.append(_Caption(label=label, score=1.0, box=box, text=text))
    return captions


def _region_kind(label: str) -> str:
    return "table" if label == "table" else "figure"


def _caption_kind(caption: _Caption) -> str:
    if "table" in caption.label or caption.text.casefold().startswith("table"):
        return "table"
    if caption.text.startswith("表"):
        return "table"
    return "figure"


def _prepare_page_regions(
    page: Any,
    rows: list[dict[str, Any]],
    width: int,
    height: int,
    scale: float,
) -> tuple[list[_Region], list[_Caption]]:
    page_area = float(width * height)
    visuals: list[_Region] = []
    captions: list[_Caption] = _native_captions(page, scale)

    for row in rows:
        label = str(row.get("label") or "").strip().casefold()
        box = _box_from_row(row, width, height)
        if box is None:
            continue
        try:
            score = float(row.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if label in _CAPTION_LABELS and score >= 0.4:
            import pymupdf

            pdf_box = pymupdf.Rect(*(value / scale for value in box))
            text = _clean_caption(page.get_textbox(pdf_box))
            detected = _Caption(label=label, score=score, box=box, text=text)
            if not any(_iou(box, existing.box) > 0.55 for existing in captions):
                captions.append(detected)
            continue
        if label not in _VISUAL_LABELS:
            continue
        threshold = 0.48 if label in {"chart", "figure"} else 0.55
        if score < threshold:
            continue
        box_area = _area(box)
        if box[2] - box[0] < 90 or box[3] - box[1] < 55:
            continue
        if box_area < page_area * 0.006 or box_area > page_area * 0.82:
            continue
        visuals.append(_Region(label=label, score=score, box=box))

    priority = {"table": 4, "chart": 3, "figure": 3, "image": 2}
    selected: list[_Region] = []
    for region in sorted(
        visuals,
        key=lambda value: (priority.get(value.label, 0), value.score),
        reverse=True,
    ):
        duplicate = any(
            _iou(region.box, existing.box) > 0.58 or _containment(region.box, existing.box) > 0.86
            for existing in selected
        )
        if not duplicate:
            selected.append(region)

    assigned: list[_Region] = []
    for region in selected:
        best: tuple[float, int] | None = None
        for index, caption in enumerate(captions):
            overlap = _horizontal_overlap(region.box, caption.box)
            region_center = (region.box[0] + region.box[2]) / 2
            caption_center = (caption.box[0] + caption.box[2]) / 2
            center_gap = abs(region_center - caption_center)
            if overlap < 0.08 and center_gap > width * 0.24:
                continue
            if region.box[3] <= caption.box[1]:
                gap = caption.box[1] - region.box[3]
            elif caption.box[3] <= region.box[1]:
                gap = region.box[1] - caption.box[3]
            else:
                gap = 0.0
            if gap > height * 0.24:
                continue
            mismatch = (
                0.0 if _region_kind(region.label) == _caption_kind(caption) else height * 0.08
            )
            rank = gap + center_gap * 0.16 + mismatch - caption.score * 12
            if best is None or rank < best[0]:
                best = (rank, index)
        assigned.append(
            _Region(
                label=region.label,
                score=region.score,
                box=region.box,
                caption_index=best[1] if best else None,
            )
        )

    grouped: list[_Region] = []
    consumed: set[int] = set()
    for caption_index in range(len(captions)):
        members = [
            (index, region)
            for index, region in enumerate(assigned)
            if region.caption_index == caption_index
        ]
        if len(members) < 2:
            continue
        combined = _union([region.box for _index, region in members])
        fill_ratio = sum(_area(region.box) for _index, region in members) / max(
            1.0, _area(combined)
        )
        if _area(combined) <= page_area * 0.64 and fill_ratio >= 0.30:
            label = (
                "table" if any(region.label == "table" for _index, region in members) else "figure"
            )
            grouped.append(
                _Region(
                    label=label,
                    score=max(region.score for _index, region in members),
                    box=combined,
                    caption_index=caption_index,
                )
            )
            consumed.update(index for index, _region in members)

    grouped.extend(region for index, region in enumerate(assigned) if index not in consumed)
    filtered: list[_Region] = []
    for region in grouped:
        if region.caption_index is None:
            if region.score < 0.66:
                continue
            if region.box[3] < height * 0.20 and _area(region.box) < page_area * 0.10:
                continue
        filtered.append(region)
    return sorted(filtered, key=lambda region: (region.box[1], region.box[0])), captions


def _expand_box(
    box: tuple[float, float, float, float], width: int, height: int, padding: int = 8
) -> tuple[int, int, int, int]:
    return (
        max(0, int(box[0]) - padding),
        max(0, int(box[1]) - padding),
        min(width, int(box[2] + 0.999) + padding),
        min(height, int(box[3] + 0.999) + padding),
    )


def _difference_hash(image: Any) -> str:
    resized = image.convert("L").resize((9, 8))
    flattened = getattr(resized, "get_flattened_data", None)
    pixels = list(flattened() if flattened is not None else resized.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return f"{value:016x}"


def _hash_distance(first: str, second: str) -> int:
    return (int(first, 16) ^ int(second, 16)).bit_count()


def _pdf_fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    stat = path.stat()
    return {"sha256": digest.hexdigest(), "size": stat.st_size}


def _read_manifest(path: Path) -> dict[str, Any] | None:
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _manifest_figures(path: Path, manifest: dict[str, Any]) -> list[PaperFigure] | None:
    rows = manifest.get("figures")
    if not isinstance(rows, list):
        return None
    figures: list[PaperFigure] = []
    try:
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("public"), dict):
                return None
            figure = PaperFigure.model_validate(row["public"])
            if not (path / figure.filename).is_file():
                return None
            figures.append(figure)
    except Exception:
        return None
    return figures


def _extract_to_directory(
    pdf_path: Path,
    output_dir: Path,
    fingerprint: dict[str, Any],
    *,
    max_figures: int = MAX_FIGURES,
) -> tuple[list[PaperFigure], dict[str, Any]]:
    try:
        import pymupdf
        from PIL import Image, ImageStat
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise RuntimeError("本地图表识别组件未安装，请重新安装桌面版") from exc

    if not pdf_path.is_file():
        raise FileNotFoundError(f"找不到本地 PDF：{pdf_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    figures: list[PaperFigure] = []
    internal_rows: list[dict[str, Any]] = []
    seen_hashes: list[tuple[str, str, float]] = []
    document = pymupdf.open(pdf_path)
    try:
        with tempfile.TemporaryDirectory(prefix="pages-", dir=output_dir) as page_temp:
            page_dir = Path(page_temp)
            for page in document:
                if len(figures) >= max_figures:
                    break
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE), alpha=False
                )
                page_path = page_dir / f"page-{page.number + 1:04d}.png"
                pixmap.save(page_path)
                rows = _predict_layout(page_path)
                regions, captions = _prepare_page_regions(
                    page, rows, pixmap.width, pixmap.height, RENDER_SCALE
                )
                with Image.open(page_path) as rendered:
                    rendered.load()
                    for region in regions:
                        if len(figures) >= max_figures:
                            break
                        crop_box = _expand_box(region.box, rendered.width, rendered.height)
                        crop = rendered.crop(crop_box).convert("RGB")
                        grayscale = crop.convert("L")
                        if ImageStat.Stat(grayscale).stddev[0] < 2.5:
                            continue
                        perceptual_hash = _difference_hash(crop)
                        content_hash = hashlib.sha256(crop.tobytes()).hexdigest()
                        aspect = crop.width / max(1, crop.height)
                        duplicate = any(
                            content_hash == saved_content
                            or (
                                abs(aspect - saved_aspect) <= 0.08
                                and _hash_distance(perceptual_hash, saved_visual) <= 3
                            )
                            for saved_content, saved_visual, saved_aspect in seen_hashes
                        )
                        if duplicate:
                            continue
                        filename = f"figure-{len(figures) + 1:02d}.png"
                        crop.save(output_dir / filename, format="PNG")
                        caption = (
                            captions[region.caption_index].text
                            if region.caption_index is not None
                            else ""
                        )
                        figure = PaperFigure(
                            filename=filename,
                            page=page.number + 1,
                            caption=caption or f"第 {page.number + 1} 页图表",
                            kind=_region_kind(region.label),
                            width=crop.width,
                            height=crop.height,
                        )
                        figures.append(figure)
                        seen_hashes.append((content_hash, perceptual_hash, aspect))
                        internal_rows.append(
                            {
                                "public": figure.model_dump(),
                                "label": region.label,
                                "confidence": round(region.score, 6),
                                "bbox_pixels": [round(value, 2) for value in region.box],
                                "caption_bbox_pixels": (
                                    [
                                        round(value, 2)
                                        for value in captions[region.caption_index].box
                                    ]
                                    if region.caption_index is not None
                                    else None
                                ),
                                "content_sha256": content_hash,
                                "difference_hash": perceptual_hash,
                            }
                        )
    finally:
        document.close()

    manifest = {
        "version": EXTRACTOR_VERSION,
        "extractor": "paddleocr-layout",
        "model": MODEL_NAME,
        "packages": {
            "paddleocr": _package_version("paddleocr"),
            "paddlepaddle": _package_version("paddlepaddle"),
        },
        "render_scale": RENDER_SCALE,
        "pdf": fingerprint,
        "figures": internal_rows,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return figures, manifest


def _save_figure_records(
    storage: SqliteStorage, user_id: int, item_id: int, figures: list[PaperFigure]
) -> PaperItem:
    conn = storage._connect()
    conn.execute(
        "UPDATE paper_items SET figures_json = ?, updated_at = datetime('now') "
        "WHERE user_id = ? AND id = ?",
        (dumps_json([figure.model_dump() for figure in figures]), user_id, item_id),
    )
    conn.commit()
    refreshed = get_paper(storage, user_id, item_id)
    if refreshed is None:
        raise LookupError("paper not found")
    return refreshed


def extract_figures_for_paper(
    storage: SqliteStorage,
    user_id: int,
    item_id: int,
    *,
    force: bool = False,
) -> PaperItem:
    """Extract figures independently from AI summarization and persist atomically."""
    key = (user_id, item_id)
    with _ITEM_LOCKS_GUARD:
        item_lock = _ITEM_LOCKS.setdefault(key, threading.Lock())
    with item_lock:
        item = get_paper(storage, user_id, item_id)
        if item is None:
            raise LookupError("paper not found")
        if not item.pdf_path:
            raise ValueError("请先为这篇 Paper 附加或同步本地 PDF")
        pdf_path = Path(item.pdf_path).expanduser().resolve(strict=False)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"找不到本地 PDF：{pdf_path}")
        fingerprint = _pdf_fingerprint(pdf_path)
        target = paper_figure_dir(user_id, item_id)
        manifest = _read_manifest(target)
        if (
            not force
            and manifest is not None
            and manifest.get("version") == EXTRACTOR_VERSION
            and manifest.get("model") == MODEL_NAME
            and manifest.get("pdf") == fingerprint
        ):
            cached = _manifest_figures(target, manifest)
            if cached is not None:
                if [row.model_dump() for row in cached] != [
                    row.model_dump() for row in item.figures
                ]:
                    return _save_figure_records(storage, user_id, item_id, cached)
                return item

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{item_id}-", dir=target.parent))
        backup = target.parent / f".{item_id}-{uuid4().hex}.backup"
        swapped = False
        try:
            figures, _manifest = _extract_to_directory(pdf_path, staging, fingerprint)
            if target.exists():
                target.replace(backup)
            staging.replace(target)
            swapped = True
            try:
                refreshed = _save_figure_records(storage, user_id, item_id, figures)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    backup.replace(target)
                raise
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            return refreshed
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if backup.exists():
                if not swapped and not target.exists():
                    backup.replace(target)
                elif swapped:
                    shutil.rmtree(backup, ignore_errors=True)
