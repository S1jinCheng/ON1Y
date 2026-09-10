"""PDF extraction and concise Chinese AI summaries for Paper items."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.config import get_settings
from on1y.llm.client import get_llm_client
from on1y.llm.settings import resolve_llm_settings
from on1y.papers.knowledge_sync import prepare_paper, sync_paper_tags
from on1y.papers.models import PaperAiSummary, PaperFigure, PaperItem
from on1y.papers.shelf import get_paper
from on1y.user.paths import user_dir
from on1y.utils.json_util import dumps_json, dumps_meta

_CAPTION_RE = re.compile(
    r"^\s*(?P<label>fig(?:ure)?|table|图|表)\.?\s*(?:S?\d+[A-Za-z]?|[IVX]+)(?:\s*[.:：-])?",
    re.IGNORECASE,
)


def paper_figure_dir(user_id: int, item_id: int) -> Path:
    return user_dir(user_id) / "papers" / "figures" / str(item_id)


def _clean_text(value: object, *, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _string_list(value: object, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for row in value:
        text = _clean_text(row)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _summary_from_payload(payload: dict[str, Any]) -> PaperAiSummary:
    return PaperAiSummary(
        overview=_clean_text(payload.get("overview"), limit=900),
        research_question=_clean_text(payload.get("research_question"), limit=600),
        method=_clean_text(payload.get("method"), limit=900),
        key_findings=_string_list(payload.get("key_findings")),
        effects=_string_list(payload.get("effects")),
        limitations=_string_list(payload.get("limitations"), limit=6),
        keywords=_string_list(payload.get("keywords"), limit=12),
    )


def _sample_text(text: str, limit: int) -> str:
    """Keep beginning, middle, and ending evidence instead of truncating conclusions."""
    text = text.strip()
    if len(text) <= limit:
        return text
    chunk = max(1, limit // 3)
    middle = max(0, len(text) // 2 - chunk // 2)
    return (
        text[:chunk]
        + "\n\n[中段摘录]\n"
        + text[middle : middle + chunk]
        + "\n\n[结论附近]\n"
        + text[-chunk:]
    )


def extract_paper_pdf(
    pdf_path: Path,
    output_dir: Path,
    *,
    max_figures: int = 8,
) -> tuple[str, list[PaperFigure]]:
    """Extract text and tightly cropped figures/tables from a PDF."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise RuntimeError("PDF 解析组件未安装，请重新安装桌面版") from exc

    if not pdf_path.is_file():
        raise FileNotFoundError(f"找不到本地 PDF：{pdf_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_figure in output_dir.glob("figure-*.png"):
        old_figure.unlink(missing_ok=True)

    document = pymupdf.open(pdf_path)
    page_texts: list[str] = []
    figures: list[PaperFigure] = []
    used: list[tuple[int, Any]] = []

    def area(rect: Any) -> float:
        return max(0.0, float(rect.width)) * max(0.0, float(rect.height))

    def union(first: Any, second: Any) -> Any:
        return pymupdf.Rect(
            min(float(first.x0), float(second.x0)),
            min(float(first.y0), float(second.y0)),
            max(float(first.x1), float(second.x1)),
            max(float(first.y1), float(second.y1)),
        )

    def expand(rect: Any, amount: float) -> Any:
        return pymupdf.Rect(
            float(rect.x0) - amount,
            float(rect.y0) - amount,
            float(rect.x1) + amount,
            float(rect.y1) + amount,
        )

    def intersection(first: Any, second: Any) -> Any:
        return pymupdf.Rect(
            max(float(first.x0), float(second.x0)),
            max(float(first.y0), float(second.y0)),
            min(float(first.x1), float(second.x1)),
            min(float(first.y1), float(second.y1)),
        )

    def overlap_ratio(first: Any, second: Any) -> float:
        overlap = max(
            0.0,
            min(float(first.x1), float(second.x1))
            - max(float(first.x0), float(second.x0)),
        )
        return overlap / max(1.0, min(float(first.width), float(second.width)))

    def iou(first: Any, second: Any) -> float:
        overlap = area(intersection(first, second))
        return overlap / max(1.0, area(first) + area(second) - overlap)

    def cluster_rects(rectangles: list[Any]) -> list[Any]:
        clusters: list[Any] = []
        for rectangle in rectangles:
            current = pymupdf.Rect(rectangle)
            changed = True
            while changed:
                changed = False
                remaining: list[Any] = []
                for cluster in clusters:
                    if expand(current, 18).intersects(expand(cluster, 6)):
                        current = union(current, cluster)
                        changed = True
                    else:
                        remaining.append(cluster)
                clusters = remaining
            clusters.append(current)
        return clusters

    def save_clip(page: Any, clip: Any, caption: str, kind: str = "figure") -> None:
        if len(figures) >= max_figures:
            return
        clip = intersection(clip, page.rect)
        if clip.width < 80 or clip.height < 55:
            return
        if any(page.number == used_page and iou(clip, saved) > 0.72 for used_page, saved in used):
            return
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(2.2, 2.2),
            clip=clip,
            alpha=False,
        )
        filename = f"figure-{len(figures) + 1:02d}.png"
        pixmap.save(output_dir / filename)
        figures.append(
            PaperFigure(
                filename=filename,
                page=page.number + 1,
                caption=_clean_text(caption),
                kind="table" if kind == "table" else "figure",
                width=pixmap.width,
                height=pixmap.height,
            )
        )
        used.append((page.number, clip))

    try:
        for page in document:
            page_text = page.get_text("text").strip()
            if page_text:
                page_texts.append(f"[第 {page.number + 1} 页]\n{page_text}")

            page_dict = page.get_text("dict")
            text_lines: list[tuple[Any, str]] = []
            image_rects: list[Any] = []
            captions: list[tuple[Any, Any, str, str]] = []
            for block in page_dict.get("blocks") or []:
                block_type = int(block.get("type", 0))
                block_rect = pymupdf.Rect(block.get("bbox") or (0, 0, 0, 0))
                if block_type == 1:
                    if block_rect.width >= 60 and block_rect.height >= 45:
                        image_rects.append(block_rect)
                    continue
                lines = block.get("lines") or []
                line_values: list[tuple[Any, str]] = []
                for line in lines:
                    text = _clean_text(
                        "".join(str(span.get("text") or "") for span in line.get("spans") or [])
                    )
                    if not text:
                        continue
                    line_rect = pymupdf.Rect(line.get("bbox") or block_rect)
                    text_lines.append((line_rect, text))
                    line_values.append((line_rect, text))
                for index, (line_rect, text) in enumerate(line_values):
                    match = _CAPTION_RE.match(text)
                    if not match:
                        continue
                    caption = " ".join(value for _rect, value in line_values[index : index + 3])
                    label = match.group("label").casefold()
                    kind = "table" if label in {"table", "表"} else "figure"
                    captions.append((line_rect, block_rect, _clean_text(caption), kind))
                    break

            drawing_rects: list[Any] = []
            for drawing in page.get_drawings():
                rect = pymupdf.Rect(drawing.get("rect") or (0, 0, 0, 0))
                if (
                    (rect.width >= 8 and rect.height >= 8)
                    or (rect.width >= 45 and rect.height >= 1)
                    or (rect.height >= 45 and rect.width >= 1)
                ):
                    drawing_rects.append(rect)

            table_rects: list[Any] = []
            if any(kind == "table" for _line, _block, _text, kind in captions):
                try:
                    finder = page.find_tables()
                    table_rects = [pymupdf.Rect(table.bbox) for table in finder.tables]
                except Exception:
                    table_rects = []

            visual_clusters = cluster_rects([*image_rects, *drawing_rects])
            ordered_captions = sorted(captions, key=lambda row: float(row[0].y0))
            for caption_index, (caption_rect, block_rect, caption, kind) in enumerate(
                ordered_captions
            ):
                page_mid = (float(page.rect.x0) + float(page.rect.x1)) / 2
                caption_mid = (float(block_rect.x0) + float(block_rect.x1)) / 2
                if block_rect.width <= page.rect.width * 0.62:
                    if caption_mid <= page_mid:
                        column = pymupdf.Rect(
                            float(page.rect.x0) + 14,
                            float(page.rect.y0),
                            page_mid - 5,
                            float(page.rect.y1),
                        )
                    else:
                        column = pymupdf.Rect(
                            page_mid + 5,
                            float(page.rect.y0),
                            float(page.rect.x1) - 14,
                            float(page.rect.y1),
                        )
                else:
                    column = pymupdf.Rect(
                        float(page.rect.x0) + 14,
                        float(page.rect.y0),
                        float(page.rect.x1) - 14,
                        float(page.rect.y1),
                    )
                fallback_column = column
                # Real visual objects define their own horizontal extent. Search the full
                # body width so a short full-width caption is not mistaken for one column.
                column = pymupdf.Rect(
                    float(page.rect.x0) + 14,
                    float(page.rect.y0),
                    float(page.rect.x1) - 14,
                    float(page.rect.y1),
                )

                previous_bottom = (
                    float(ordered_captions[caption_index - 1][1].y1) + 4
                    if caption_index > 0
                    else float(page.rect.y0) + 14
                )
                next_top = (
                    float(ordered_captions[caption_index + 1][1].y0) - 4
                    if caption_index + 1 < len(ordered_captions)
                    else float(page.rect.y1) - 14
                )
                direction = "below" if kind == "table" else "above"
                source_rects = (
                    [*table_rects, *visual_clusters]
                    if kind == "table"
                    else visual_clusters
                )

                def candidates_for(
                    side: str,
                    sources: list[Any] = source_rects,
                    body_column: Any = column,
                    previous_y: float = previous_bottom,
                    caption_box: Any = caption_rect,
                    next_y: float = next_top,
                    page_box: Any = page.rect,
                    caption_center: float = caption_mid,
                    detected_tables: list[Any] = table_rects,
                ) -> list[tuple[float, Any]]:
                    candidates: list[tuple[float, Any]] = []
                    for source in sources:
                        clipped = intersection(source, body_column)
                        if clipped.width < 55 or clipped.height < 28:
                            continue
                        if overlap_ratio(clipped, body_column) <= 0.08:
                            continue
                        if side == "above":
                            if clipped.y0 < previous_y or clipped.y1 > caption_box.y0 + 8:
                                continue
                            gap = max(0.0, float(caption_box.y0) - float(clipped.y1))
                        else:
                            if clipped.y0 < caption_box.y1 - 8 or clipped.y1 > next_y:
                                continue
                            gap = max(0.0, float(clipped.y0) - float(caption_box.y1))
                        if gap > page_box.height * 0.38:
                            continue
                        center_gap = abs(
                            (float(clipped.x0) + float(clipped.x1)) / 2
                            - caption_center
                        )
                        area_bonus = min(
                            area(clipped) / max(1.0, area(page_box)),
                            0.35,
                        ) * 900
                        exact_table_bonus = (
                            250
                            if any(iou(clipped, table) > 0.6 for table in detected_tables)
                            else 0
                        )
                        score = gap * 3 + center_gap * 0.12 - area_bonus - exact_table_bonus
                        candidates.append((score, clipped))
                    return sorted(candidates, key=lambda row: row[0])

                ranked = candidates_for(direction)
                if not ranked:
                    direction = "above" if direction == "below" else "below"
                    ranked = candidates_for(direction)

                if ranked:
                    clip = ranked[0][1]
                    for _score, nearby in ranked[1:]:
                        if (
                            expand(clip, 22).intersects(nearby)
                            and overlap_ratio(clip, nearby) > 0.15
                        ):
                            clip = union(clip, nearby)

                    for _iteration in range(2):
                        probe = expand(clip, 13)
                        for line_rect, line_text in text_lines:
                            if _CAPTION_RE.match(line_text) or len(line_text) > 100:
                                continue
                            if direction == "above" and not (
                                previous_bottom <= line_rect.y0 < caption_rect.y0 - 2
                            ):
                                continue
                            if direction == "below" and not (
                                caption_rect.y1 + 2 < line_rect.y1 <= next_top
                            ):
                                continue
                            if (
                                probe.intersects(line_rect)
                                and overlap_ratio(line_rect, column) > 0.1
                            ):
                                clip = union(clip, intersection(line_rect, column))
                    clip = expand(clip, 8)
                    if direction == "above":
                        clip.y0 = max(float(clip.y0), previous_bottom)
                        clip.y1 = min(float(clip.y1), float(caption_rect.y0) - 3)
                    else:
                        clip.y0 = max(float(clip.y0), float(caption_rect.y1) + 3)
                        clip.y1 = min(float(clip.y1), next_top)
                    clip = intersection(clip, column)
                elif direction == "above":
                    height = min(float(page.rect.height) * 0.42, 330.0)
                    clip = pymupdf.Rect(
                        float(fallback_column.x0),
                        max(previous_bottom, float(caption_rect.y0) - height),
                        float(fallback_column.x1),
                        float(caption_rect.y0) - 4,
                    )
                else:
                    height = min(float(page.rect.height) * 0.42, 330.0)
                    clip = pymupdf.Rect(
                        float(fallback_column.x0),
                        float(caption_rect.y1) + 4,
                        float(fallback_column.x1),
                        min(next_top, float(caption_rect.y1) + height),
                    )
                save_clip(page, clip, caption, kind)

        # For image-only or unusually captioned papers, keep the largest embedded images.
        if len(figures) < min(2, max_figures):
            candidates: list[tuple[float, Any, Any]] = []
            for page in document:
                for image in page.get_images(full=True):
                    xref = int(image[0])
                    for rect in page.get_image_rects(xref):
                        image_area = area(rect)
                        if image_area >= area(page.rect) * 0.04:
                            candidates.append((image_area, page, rect))
            for _image_area, page, rect in sorted(
                candidates,
                key=lambda row: row[0],
                reverse=True,
            ):
                if len(figures) >= max_figures:
                    break
                save_clip(
                    page,
                    expand(rect, 8),
                    f"第 {page.number + 1} 页图表",
                )
    finally:
        document.close()

    text = "\n\n".join(page_texts).strip()
    if not text:
        raise ValueError("没有从 PDF 中提取到文字；该文件可能是纯扫描件")
    return text, figures


def generate_paper_summary(
    storage: SqliteStorage, user_id: int, item_id: int
) -> PaperItem:
    item = get_paper(storage, user_id, item_id)
    if item is None:
        raise LookupError("paper not found")
    if not item.pdf_path:
        raise ValueError("请先为这篇 Paper 附加或同步本地 PDF")
    pdf_path = Path(item.pdf_path).expanduser().resolve(strict=False)

    conn = storage._connect()
    conn.execute(
        "UPDATE paper_items SET ai_summary_status = 'running', ai_summary_error = NULL "
        "WHERE user_id = ? AND id = ?",
        (user_id, item_id),
    )
    conn.commit()

    try:
        extracted_text, figures = extract_paper_pdf(
            pdf_path, paper_figure_dir(user_id, item_id)
        )
        settings = get_settings()
        evidence = _sample_text(extracted_text, settings.llm_distill_max_input_chars)
        captions = "\n".join(
            f"- 第 {figure.page} 页：{figure.caption}" for figure in figures if figure.caption
        )
        prompt = f"""论文标题：{item.title}
作者：{", ".join(author.name for author in item.authors) or "未知"}
原摘要：{item.abstract or "无"}

以下是从 PDF 抽取的证据：
{evidence}

图表标题：
{captions or "未识别到图表标题"}

请严格输出 JSON：
{{
  "overview": "2-3 句中文总览，说明研究了什么、得到什么结果",
  "research_question": "研究问题",
  "method": "核心方法与数据/实验设计",
  "key_findings": ["关键发现"],
  "effects": ["定量效果、指标变化或对照结果；没有明确数据就写证据未给出"],
  "limitations": ["局限或适用边界"],
  "keywords": ["3-8 个精简中文或领域通用标签"]
}}
只依据给定证据，不猜测，不编造数值；优先保留论文中的具体指标和效果。"""
        payload = get_llm_client().chat_json(
            "你是严谨的论文阅读助手，负责把学术论文压缩成一眼可读的简体中文速览。",
            prompt,
            max_tokens=1600,
        )
        summary = _summary_from_payload(payload)
        model = resolve_llm_settings(user_id=user_id).model
        merged_tags = list(item.tags)
        known = {tag.casefold() for tag in merged_tags}
        for keyword in summary.keywords:
            if keyword.casefold() not in known:
                known.add(keyword.casefold())
                merged_tags.append(keyword)

        conn.execute(
            """
            UPDATE paper_items
            SET ai_summary_json = ?, ai_summary_status = 'ok', ai_summary_error = NULL,
                ai_summary_model = ?, ai_summary_updated_at = datetime('now'),
                figures_json = ?, tags_json = ?, updated_at = datetime('now')
            WHERE user_id = ? AND id = ?
            """,
            (
                dumps_meta(summary.model_dump()),
                model,
                dumps_json([figure.model_dump() for figure in figures]),
                dumps_json(merged_tags),
                user_id,
                item_id,
            ),
        )
        conn.commit()
        refreshed = get_paper(storage, user_id, item_id)
        assert refreshed is not None
        refreshed = sync_paper_tags(storage, user_id, item_id, merged_tags) or refreshed
        return prepare_paper(storage, user_id, refreshed, extracted_body=extracted_text)
    except Exception as exc:
        conn.execute(
            "UPDATE paper_items SET ai_summary_status = 'error', ai_summary_error = ?, "
            "updated_at = datetime('now') WHERE user_id = ? AND id = ?",
            (str(exc)[:1000], user_id, item_id),
        )
        conn.commit()
        raise