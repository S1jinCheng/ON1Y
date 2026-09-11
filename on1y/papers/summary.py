"""PDF extraction and concise Chinese AI summaries for Paper items."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.config import get_settings
from on1y.llm.client import get_llm_client
from on1y.llm.settings import resolve_llm_settings
from on1y.papers.figures import extract_figures_for_paper
from on1y.papers.knowledge_sync import prepare_paper, sync_paper_tags
from on1y.papers.models import PaperAiSummary, PaperItem
from on1y.papers.shelf import get_paper
from on1y.utils.json_util import dumps_json, dumps_meta

logger = logging.getLogger(__name__)


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


def extract_paper_text(pdf_path: Path) -> str:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise RuntimeError("PDF 文字提取组件未安装，请重新安装桌面版") from exc

    if not pdf_path.is_file():
        raise FileNotFoundError(f"找不到本地 PDF：{pdf_path}")
    document = pymupdf.open(pdf_path)
    try:
        text = "\n\n".join(page.get_text("text") for page in document).strip()
    finally:
        document.close()
    if not text:
        raise ValueError("没有从 PDF 中提取到文字；该文件可能是纯扫描件")
    return text


def generate_paper_summary(storage: SqliteStorage, user_id: int, item_id: int) -> PaperItem:
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
        try:
            item = extract_figures_for_paper(storage, user_id, item_id)
        except Exception:
            logger.exception("Paper %s figure extraction failed", item_id)
            item = get_paper(storage, user_id, item_id) or item
        extracted_text = extract_paper_text(pdf_path)
        figures = item.figures
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
                tags_json = ?, updated_at = datetime('now')
            WHERE user_id = ? AND id = ?
            """,
            (
                dumps_meta(summary.model_dump()),
                model,
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
