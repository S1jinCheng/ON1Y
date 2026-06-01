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
) -> dict[str, Any]:
    """Ingest pending URLs, fetch subtitles, then LLM summarize/classify."""
    from on1y.distill.processor import run_distill_batch
    from on1y.pipeline.subtitle_worker import run_subtitle_batch
    from on1y.pipeline.worker import run_worker_batch

    report: dict[str, Any] = {"platform": platform}
    if ingest_limit > 0:
        report["ingest"] = run_worker_batch(storage, ingest_limit, platform=platform)
    if subtitle_limit > 0:
        report["subtitles"] = run_subtitle_batch(storage, subtitle_limit, platform=platform)
    if distill_limit > 0:
        report["distill"] = run_distill_batch(storage, distill_limit, platform=platform)
    return report
