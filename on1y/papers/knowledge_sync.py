"""Connect paper rows to shared tags, notes search, and recommendations."""

from __future__ import annotations

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.papers.models import PaperItem
from on1y.papers.shelf import get_paper
from on1y.utils.json_util import dumps_json

PAPER_DISTILL_PROMPT_VERSION = "paper-library-v2"


def paper_canonical_url(item: PaperItem) -> str:
    if item.doi:
        return f"https://doi.org/{item.doi.removeprefix('https://doi.org/')}"
    return item.url or f"on1y://papers/{item.id}"


def prepare_paper(
    storage: SqliteStorage,
    user_id: int,
    item: PaperItem,
    *,
    extracted_body: str | None = None,
) -> PaperItem:
    author_names = [author.name for author in item.authors]
    body = extracted_body or "\n\n".join(
        part for part in [item.title, ", ".join(author_names), item.abstract or ""] if part
    )
    meta = {
        "paper_library": True,
        "paper_item_id": item.id,
        "authors": author_names,
        "doi": item.doi or "",
        "venue": item.venue or "",
        "year": item.year,
        "zotero_key": item.zotero_key or "",
        # Notes collection and global search read these shared metadata keys.
        "user_note_html": item.user_note_html or "",
        "importance": item.importance,
    }
    raw = storage.upsert_raw_item(
        RawItemCreate(
            url=paper_canonical_url(item),
            platform="paper",
            source=SourceType.MANUAL,
            raw_title=item.title,
            body_text=body,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
            source_meta=meta,
        )
    )
    raw_id = int(raw.id)
    conn = storage._connect()
    conn.execute(
        "UPDATE paper_items SET raw_id = ? WHERE user_id = ? AND id = ?",
        (raw_id, user_id, item.id),
    )
    conn.commit()
    summary = (
        item.ai_summary.overview if item.ai_summary and item.ai_summary.overview
        else item.abstract or item.title
    ).strip()
    if len(summary) > 800:
        summary = summary[:800].rstrip() + "…"
    key_points = item.ai_summary.key_findings if item.ai_summary else []
    topics = item.ai_summary.keywords if item.ai_summary else []
    storage.upsert_distilled(
        raw_id=raw_id,
        summary=summary,
        key_points=key_points,
        topics=topics,
        model=item.ai_summary_model,
        prompt_version=PAPER_DISTILL_PROMPT_VERSION,
        status="ok",
        error=None,
    )
    if item.tags:
        storage.set_item_classification(raw_id, tags=item.tags, source="manual")
    refreshed = get_paper(storage, user_id, item.id)
    assert refreshed is not None
    return refreshed


def sync_paper_note(
    storage: SqliteStorage, user_id: int, item: PaperItem
) -> PaperItem:
    if item.raw_id is None:
        item = prepare_paper(storage, user_id, item)
    assert item.raw_id is not None
    storage.merge_source_meta(item.raw_id, {"user_note_html": item.user_note_html or ""})
    refreshed = get_paper(storage, user_id, item.id)
    assert refreshed is not None
    return refreshed


def sync_paper_tags(
    storage: SqliteStorage, user_id: int, item_id: int, tags: list[str]
) -> PaperItem | None:
    item = get_paper(storage, user_id, item_id)
    if item is None:
        return None
    if item.raw_id is None:
        item = prepare_paper(storage, user_id, item)
    assert item.raw_id is not None
    storage.set_item_classification(item.raw_id, tags=tags, source="manual")
    names = storage.get_item_tag_names(item.raw_id)
    storage._connect().execute(
        "UPDATE paper_items SET tags_json = ?, updated_at = datetime('now') "
        "WHERE id = ? AND user_id = ?",
        (dumps_json(names), item_id, user_id),
    )
    storage._connect().commit()
    return get_paper(storage, user_id, item_id)