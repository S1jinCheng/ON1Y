"""Post-ingest enrichment: subtitles + LLM distill for video platforms."""

from __future__ import annotations

from typing import Any

from on1y.ports.storage import StoragePort


def run_video_enrich_pipeline(
    storage: StoragePort,
    *,
    platform: str = "bilibili",
    ingest_limit: int = 0,
    subtitle_limit: int = 10,
    distill_limit: int = 10,
    use_ai_summary: bool = True,
) -> dict[str, Any]:
    """Ingest pending URLs, fetch subtitles, then LLM summarize/classify."""
    from on1y.distill.processor import run_distill_batch
    from on1y.pipeline.subtitle_worker import run_subtitle_batch
    from on1y.pipeline.worker import run_worker_batch

    from on1y.config import get_settings

    settings = get_settings()
    report: dict[str, Any] = {"platform": platform}
    if ingest_limit > 0:
        report["ingest"] = run_worker_batch(storage, ingest_limit, platform=platform)
    subtitle_processed = 0
    if subtitle_limit > 0:
        sub = run_subtitle_batch(
            storage,
            subtitle_limit,
            platform=platform,
            auto_distill=use_ai_summary and settings.auto_distill_after_subtitles,
        )
        report["subtitles"] = sub
        subtitle_processed = int(sub.get("processed") or 0)
    if use_ai_summary and (
        distill_limit > 0
        or (settings.auto_distill_after_subtitles and subtitle_processed > 0)
    ):
        batch_limit = max(distill_limit, subtitle_processed, 1)
        report["distill"] = run_distill_batch(storage, batch_limit, platform=platform)
    return report
