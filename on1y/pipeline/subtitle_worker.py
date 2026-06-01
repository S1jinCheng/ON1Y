"""Worker for pending_subtitles queue (yt-dlp video platforms, phase B)."""

from __future__ import annotations

import logging
import time

from on1y.alerts import is_rate_limit_error, maybe_alert_from_error
from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.config import get_settings
from on1y.exceptions import ExtractionError
from on1y.extract.subtitles import build_video_body
from on1y.extract.ytdlp_video import get_ytdlp_video_extractor
from on1y.models.enums import ExtractStatus
from on1y.pipeline.video_meta import (
    VIDEO_DESCRIPTION,
    get_stored_description,
    with_subtitle_failed,
    with_subtitle_ready,
)
from on1y.ports.storage import StoragePort
from on1y.utils.platform import YTDLP_VIDEO_PLATFORMS

logger = logging.getLogger(__name__)


def _handle_subtitle_rate_limit(*, attempts: int) -> None:
    settings = get_settings()
    if settings.subtitle_rotate_clash_on_429:
        from on1y.utils.clash import rotate_clash_proxy

        rotated = rotate_clash_proxy(settings)
        if rotated:
            logger.info("Rotated Clash after 429: %s", rotated)
        elif settings.clash_api_base:
            logger.warning(
                "Clash rotate on 429 failed; check external-controller is enabled "
                "and reachable from WSL (%s)",
                settings.clash_api_base,
            )
    backoff = min(
        settings.subtitle_rate_limit_backoff_seconds * (2 ** max(0, attempts - 1)),
        600.0,
    )
    logger.warning("YouTube/subtitle 429 backoff %.0fs before retry (attempt %s)", backoff, attempts)
    time.sleep(backoff)


def _maybe_auto_distill(storage: SqliteStorage, raw_id: int) -> None:
    settings = get_settings()
    if not settings.auto_distill_after_subtitles:
        return
    try:
        from on1y.distill.processor import distill_raw_item
        from on1y.llm.settings import get_resolved_llm_settings

        if not get_resolved_llm_settings().api_key_set:
            logger.debug("Skip auto-distill: no LLM API key")
            return
        distill_raw_item(storage, raw_id)
        logger.info("Auto-distilled raw_id=%s after subtitles", raw_id)
    except Exception as exc:
        logger.warning("Auto-distill failed for raw_id=%s: %s", raw_id, exc)


def run_subtitle_batch(
    storage: StoragePort,
    limit: int,
    *,
    close_storage: bool = False,
    platform: str | None = None,
) -> dict[str, int]:
    """Fetch subtitles for queued video items (optionally one platform only)."""
    settings = get_settings()
    processed = 0
    failed = 0

    for _ in range(max(0, limit)):
        job = storage.claim_next_pending_subtitle(platform)
        if job is None:
            break
        logger.info("Subtitle job id=%s raw_id=%s url=%s", job.id, job.raw_id, job.url)
        raw = storage.get_raw_by_id(job.raw_id)
        if raw is None:
            storage.mark_subtitle_failed(job.id, "raw_item missing", retry=False)
            failed += 1
            continue

        if raw.platform not in YTDLP_VIDEO_PLATFORMS:
            storage.mark_subtitle_failed(
                job.id,
                f"unsupported platform for subtitle queue: {raw.platform}",
                retry=False,
            )
            failed += 1
            continue

        try:
            extractor = get_ytdlp_video_extractor(raw.platform)
            payload = extractor.fetch_subtitles(job.url)
            description = payload.description or get_stored_description(raw.source_meta)
            body, partial_reason = build_video_body(
                title=payload.title or raw.raw_title,
                subtitle_text=payload.subtitle_text,
                description=description or None,
                langs_found=payload.langs_found,
                prefer_lang=settings.content_locale,
            )
            if len(body) > settings.max_body_chars:
                body = body[: settings.max_body_chars]

            status = (
                ExtractStatus.OK
                if payload.subtitle_text and not partial_reason
                else ExtractStatus.PARTIAL
            )
            err = partial_reason or (None if payload.subtitle_text else "no_subtitles")
            meta = with_subtitle_ready(raw.source_meta)
            if description:
                meta[VIDEO_DESCRIPTION] = description[:50_000]

            if (
                settings.content_locale.lower().startswith("zh")
                and settings.auto_translate_en_subtitles
                and payload.langs_found == ["en"]
                and not str(meta.get("translated_body_text") or "").strip()
            ):
                try:
                    from on1y.translate.transcript import translate_body_to_zh

                    translated = translate_body_to_zh(
                        body,
                        title=payload.title or raw.raw_title,
                    )
                    meta["translated_body_text"] = translated
                    logger.info("Auto-translated English subtitles for raw_id=%s", job.raw_id)
                except Exception as exc:
                    logger.warning("Auto-translate skipped raw_id=%s: %s", job.raw_id, exc)

            storage.update_raw_item_content(
                job.raw_id,
                body_text=body,
                raw_title=payload.title or raw.raw_title,
                extract_status=status,
                extract_error=err,
                source_meta=meta,
            )
            storage.mark_subtitle_done(job.id)
            processed += 1
            _maybe_auto_distill(storage, job.raw_id)  # type: ignore[arg-type]
        except ExtractionError as exc:
            msg = str(exc)
            retry = job.attempts < settings.subtitle_max_retries
            if retry and is_rate_limit_error(msg):
                storage.mark_subtitle_failed(job.id, msg, retry=True)
                _handle_subtitle_rate_limit(attempts=job.attempts)
                failed += 1
                logger.error("Subtitle rate-limited raw_id=%s retry=%s: %s", job.raw_id, retry, exc)
                continue
            storage.mark_subtitle_failed(job.id, msg, retry=retry)
            maybe_alert_from_error(
                msg,
                platform=raw.platform,
                worker="subtitles",
                url=job.url,
            )
            if not retry:
                meta = with_subtitle_failed(raw.source_meta, str(exc))
                storage.update_raw_item_content(
                    job.raw_id,
                    body_text=raw.body_text,
                    raw_title=raw.raw_title,
                    extract_status=raw.extract_status,
                    extract_error=raw.extract_error,
                    source_meta=meta,
                )
            failed += 1
            logger.error("Subtitle failed raw_id=%s retry=%s: %s", job.raw_id, retry, exc)
        except Exception as exc:
            msg = f"unexpected: {exc}"
            retry = job.attempts < settings.subtitle_max_retries
            if retry and is_rate_limit_error(msg):
                storage.mark_subtitle_failed(job.id, msg, retry=True)
                _handle_subtitle_rate_limit(attempts=job.attempts)
                failed += 1
                logger.exception("Subtitle rate-limited unexpected error raw_id=%s", job.raw_id)
                continue
            storage.mark_subtitle_failed(job.id, msg, retry=retry)
            maybe_alert_from_error(
                msg,
                platform=raw.platform,
                worker="subtitles",
                url=job.url,
            )
            failed += 1
            logger.exception("Subtitle unexpected error raw_id=%s", job.raw_id)

        if settings.subtitle_fetch_delay_seconds > 0:
            time.sleep(settings.subtitle_fetch_delay_seconds)

    if close_storage:
        storage.close()
    return {"processed": processed, "failed": failed}
