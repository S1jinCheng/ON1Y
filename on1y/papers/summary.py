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

_CAPTION_RE = re.compile(r"^\s*(?:fig(?:ure)?\.?|图)\s*\d+[\s.:：-]", re.IGNORECASE)


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
    max_figures: int = 6,
) -> tuple[str, list[PaperFigure]]:
    """Extract searchable text and representative raster/vector figures."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise RuntimeError("PDF 解析组件未安装，请重新安装桌面版") from exc

    if not pdf_path.is_file():
        raise FileNotFoundError(f"找不到本地 PDF：{pdf_path}")
    output_dir.mkdir(parents=True, exist_ok=True)


    document = pymupdf.open(pdf_path)
    page_texts: list[str] = []
    figures: list[PaperFigure] = []
    used: set[tuple[int, int, int]] = set()

    def save_clip(page: Any, clip: Any, caption: str) -> None:
        if len(figures) >= max_figures:
            return
        key = (page.number, round(float(clip.y0)), round(float(clip.y1)))
        if key in used or clip.width < 80 or clip.height < 60:
            return
        used.add(key)
        filename = f"figure-{len(figures) + 1:02d}.png"
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), clip=clip, alpha=False)
        pixmap.save(output_dir / filename)
        figures.append(
            PaperFigure(filename=filename, page=page.number + 1, caption=_clean_text(caption))
        )

    try:
        for page in document:
            page_text = page.get_text("text").strip()
            if page_text:
                page_texts.append(f"[第 {page.number + 1} 页]\n{page_text}")
            blocks = page.get_text("blocks")
            for block in blocks:
                caption = _clean_text(block[4])
                if not _CAPTION_RE.match(caption):
                    continue
                y0 = float(block[1])
                height = min(float(page.rect.height) * 0.48, 360.0)
                clip = pymupdf.Rect(
                    float(page.rect.x0) + 14,
                    max(float(page.rect.y0) + 14, y0 - height),
                    float(page.rect.x1) - 14,
                    min(float(page.rect.y1) - 14, float(block[3]) + 18),
                )
                save_clip(page, clip, caption)

        # Image-only papers may have no detectable caption. Keep the largest image regions.
        if len(figures) < min(2, max_figures):
            candidates: list[tuple[float, Any, Any]] = []
            for page in document:
                for image in page.get_images(full=True):
                    xref = int(image[0])
                    for rect in page.get_image_rects(xref):
                        area = float(rect.width * rect.height)
                        if area >= float(page.rect.width * page.rect.height) * 0.04:
                            candidates.append((area, page, rect))
            for _area, page, rect in sorted(candidates, key=lambda row: row[0], reverse=True):
                if len(figures) >= max_figures:
                    break
                padded = pymupdf.Rect(
                    max(float(page.rect.x0), float(rect.x0) - 10),
                    max(float(page.rect.y0), float(rect.y0) - 10),
                    min(float(page.rect.x1), float(rect.x1) + 10),
                    min(float(page.rect.y1), float(rect.y1) + 10),
                )
                save_clip(page, padded, f"第 {page.number + 1} 页图表")
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