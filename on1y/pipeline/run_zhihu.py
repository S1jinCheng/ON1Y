"""End-to-end Zhihu pipeline: RSS ingest → Playwright extract → LLM distill."""

from __future__ import annotations

import logging

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.distill.processor import distill_raw_item, list_undistilled_raw_ids
from on1y.pipeline.zhihu_worker import run_zhihu_worker_batch
from on1y.utils.platform import PLATFORM_ZHIHU

logger = logging.getLogger(__name__)


def run_zhihu_pipeline(
    storage: SqliteStorage,
    *,
    ingest_limit: int = 3,
    distill_limit: int = 5,
) -> dict[str, object]:
    """
    Run Zhihu phases in order (each respects its limit).
    Call after `on1y rss poll` when feeds include RSSHub Zhihu routes.
    """
    ingest = run_zhihu_worker_batch(storage, ingest_limit)
    distilled_ok = 0
    distilled_failed = 0
    if distill_limit > 0:
        ids = list_undistilled_raw_ids(storage, limit=distill_limit, platform=PLATFORM_ZHIHU)
        for raw_id in ids:
            try:
                distill_raw_item(storage, raw_id)
                distilled_ok += 1
            except Exception as exc:
                distilled_failed += 1
                logger.error("Distill failed raw_id=%s: %s", raw_id, exc)
    return {
        "ingest": ingest,
        "distilled": distilled_ok,
        "distill_failed": distilled_failed,
    }
