"""Zhihu queue worker — Playwright batch with rate limiting and anti-bot handling."""

from __future__ import annotations

import logging
import time

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.alerts import AlertKind, emit_alert, maybe_alert_from_error
from on1y.browser.playwright_client import is_playwright_antibot_error
from on1y.browser.playwright_session import PlaywrightSession
from on1y.config import get_settings
from on1y.exceptions import ExtractionError
from on1y.extract.zhihu import ZhihuExtractor
from on1y.models.raw import RawItemCreate
from on1y.utils.author_meta import author_meta_patch
from on1y.utils.platform import PLATFORM_ZHIHU, detect_platform, normalize_url
from on1y.utils.zhihu_author import enrich_zhihu_author_meta
from on1y.utils.zhihu_title import resolve_zhihu_title

logger = logging.getLogger(__name__)


def run_zhihu_worker_batch(
    storage: SqliteStorage,
    limit: int,
    *,
    close_storage: bool = False,
) -> dict[str, object]:
    """
    Process up to `limit` Zhihu URLs from pending_urls.
    Reuses one browser session; sleeps between items for anti-bot spacing.
    """
    from on1y.browser.playwright_isolated import run_playwright_isolated

    return run_playwright_isolated(
        lambda: _run_zhihu_worker_batch_impl(
            storage,
            limit,
            close_storage=close_storage,
        )
    )


def _run_zhihu_worker_batch_impl(
    storage: SqliteStorage,
    limit: int,
    *,
    close_storage: bool = False,
) -> dict[str, object]:
    settings = get_settings()
    extractor = ZhihuExtractor()
    processed = 0
    failed = 0
    skipped = 0
    antibot_stopped = False

    if limit <= 0:
        return {
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "antibot_stopped": False,
        }

    with PlaywrightSession(
        cookie_path=extractor.cookie_path(settings),
        seed_domain=extractor.seed_domain(),
    ) as session:
        for _ in range(limit):
            pending = storage.claim_next_pending_for_platform(PLATFORM_ZHIHU)
            if pending is None:
                break

            if detect_platform(pending.url) != PLATFORM_ZHIHU:
                storage.mark_pending_failed(
                    pending.id,
                    "not a zhihu url",
                    retry=False,
                )
                skipped += 1
                continue

            logger.info("Zhihu worker id=%s url=%s", pending.id, pending.url)
            try:
                normalized = normalize_url(pending.url)
                result = extractor.extract(normalized, session=session)
                result = result.truncated(settings.max_body_chars)
                meta = dict(pending.source_meta or {})
                meta.update(
                    author_meta_patch(
                        author=result.author,
                        author_avatar=result.author_avatar,
                        author_url=result.author_url,
                    )
                )
                meta = enrich_zhihu_author_meta(meta, normalized)
                create = RawItemCreate(
                    url=normalized,
                    platform=PLATFORM_ZHIHU,
                    source=pending.source,
                    raw_title=resolve_zhihu_title(normalized, result.raw_title, meta),
                    body_text=result.body_text,
                    content_type=result.content_type,
                    extract_status=result.extract_status,
                    extract_error=result.extract_error,
                    source_meta=meta,
                )
                raw = storage.upsert_raw_item(create)
                storage.mark_pending_done(pending.id)
                processed += 1
                from on1y.distill.processor import maybe_package_short_content

                maybe_package_short_content(storage, raw.id, raw.body_text)
                logger.info(
                    "Zhihu done id=%s raw_id=%s words=%s",
                    pending.id,
                    raw.id,
                    raw.word_count,
                )
            except ExtractionError as exc:
                msg = str(exc)
                retry = pending.attempts < settings.worker_max_retries
                if is_playwright_antibot_error(msg):
                    retry = False
                    antibot_stopped = True
                    emit_alert(
                        AlertKind.ANTIBOT,
                        PLATFORM_ZHIHU,
                        msg,
                        worker="zhihu",
                        url=pending.url,
                    )
                else:
                    maybe_alert_from_error(
                        msg,
                        platform=PLATFORM_ZHIHU,
                        worker="zhihu",
                        url=pending.url,
                    )
                storage.mark_pending_failed(pending.id, msg, retry=retry)
                failed += 1
                logger.error("Zhihu extraction failed id=%s retry=%s: %s", pending.id, retry, exc)
                if antibot_stopped:
                    logger.warning(
                        "Anti-bot detected; stopping batch. Wait ~%.0fs before retrying.",
                        settings.zhihu_antibot_pause_seconds,
                    )
                    break
            except Exception as exc:
                msg = f"unexpected: {exc}"
                retry = pending.attempts < settings.worker_max_retries
                if is_playwright_antibot_error(msg):
                    retry = False
                    antibot_stopped = True
                    emit_alert(
                        AlertKind.ANTIBOT,
                        PLATFORM_ZHIHU,
                        msg,
                        worker="zhihu",
                        url=pending.url,
                    )
                else:
                    maybe_alert_from_error(
                        msg,
                        platform=PLATFORM_ZHIHU,
                        worker="zhihu",
                        url=pending.url,
                    )
                storage.mark_pending_failed(pending.id, msg, retry=retry)
                failed += 1
                logger.exception("Unexpected zhihu error id=%s", pending.id)
                if antibot_stopped:
                    break

            if processed + failed > 0 and settings.zhihu_min_interval_seconds > 0:
                if not antibot_stopped:
                    time.sleep(settings.zhihu_min_interval_seconds)

    if close_storage:
        storage.close()

    return {
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "antibot_stopped": antibot_stopped,
    }
