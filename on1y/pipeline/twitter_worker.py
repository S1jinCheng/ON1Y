"""Drain Twitter pending_urls with rate-limited Playwright batches."""

from __future__ import annotations

import logging
import time

from on1y.adapters.sqlite_storage import SqliteStorage
from on1y.alerts import AlertKind, emit_alert, maybe_alert_from_error
from on1y.browser.playwright_client import is_playwright_antibot_error
from on1y.browser.playwright_session import PlaywrightSession
from on1y.browser.twitter_playwright import normalize_twitter_status_url
from on1y.config import get_settings
from on1y.exceptions import ExtractionError
from on1y.extract.twitter import TwitterExtractor
from on1y.models.raw import RawItemCreate
from on1y.utils.author_meta import author_meta_patch
from on1y.utils.platform import PLATFORM_TWITTER, detect_platform

logger = logging.getLogger(__name__)


def run_twitter_worker_batch(
    storage: SqliteStorage,
    limit: int,
    *,
    close_storage: bool = False,
) -> dict[str, object]:
    from on1y.browser.playwright_isolated import run_playwright_isolated

    return run_playwright_isolated(
        lambda: _run_twitter_worker_batch_impl(
            storage,
            limit,
            close_storage=close_storage,
        )
    )


def _run_twitter_worker_batch_impl(
    storage: SqliteStorage,
    limit: int,
    *,
    close_storage: bool = False,
) -> dict[str, object]:
    settings = get_settings()
    extractor = TwitterExtractor()
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
            pending = storage.claim_next_pending_for_platform(PLATFORM_TWITTER)
            if pending is None:
                break

            if detect_platform(pending.url) != PLATFORM_TWITTER:
                storage.mark_pending_failed(
                    pending.id,
                    "not a twitter url",
                    retry=False,
                )
                skipped += 1
                continue

            logger.info("Twitter worker id=%s url=%s", pending.id, pending.url)
            try:
                normalized = normalize_twitter_status_url(pending.url)
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
                create = RawItemCreate(
                    url=normalized,
                    platform=PLATFORM_TWITTER,
                    source=pending.source,
                    raw_title=result.raw_title or meta.get("entry_title"),
                    body_text=result.body_text,
                    content_type=result.content_type,
                    extract_status=result.extract_status,
                    extract_error=result.extract_error,
                    source_meta=meta,
                )
                raw = storage.upsert_raw_item(create)
                storage.mark_pending_done(pending.id)
                processed += 1
                logger.info(
                    "Twitter done id=%s raw_id=%s words=%s",
                    pending.id,
                    raw.id,
                    raw.word_count,
                )
            except ExtractionError as exc:
                msg = str(exc)
                retry = pending.attempts < settings.worker_max_retries
                if _is_twitter_antibot(msg):
                    retry = False
                    antibot_stopped = True
                    emit_alert(
                        AlertKind.ANTIBOT,
                        PLATFORM_TWITTER,
                        msg,
                        worker="twitter",
                        url=pending.url,
                    )
                else:
                    maybe_alert_from_error(
                        msg,
                        platform=PLATFORM_TWITTER,
                        worker="twitter",
                        url=pending.url,
                    )
                storage.mark_pending_failed(pending.id, msg, retry=retry)
                failed += 1
                logger.error("Twitter extraction failed id=%s retry=%s: %s", pending.id, retry, exc)
                if antibot_stopped:
                    break
            except Exception as exc:
                msg = f"unexpected: {exc}"
                retry = pending.attempts < settings.worker_max_retries
                if _is_twitter_antibot(msg):
                    retry = False
                    antibot_stopped = True
                    emit_alert(
                        AlertKind.ANTIBOT,
                        PLATFORM_TWITTER,
                        msg,
                        worker="twitter",
                        url=pending.url,
                    )
                else:
                    maybe_alert_from_error(
                        msg,
                        platform=PLATFORM_TWITTER,
                        worker="twitter",
                        url=pending.url,
                    )
                storage.mark_pending_failed(pending.id, msg, retry=retry)
                failed += 1
                logger.exception("Unexpected twitter error id=%s", pending.id)
                if antibot_stopped:
                    break

            if processed + failed > 0 and settings.twitter_min_interval_seconds > 0:
                if not antibot_stopped:
                    time.sleep(settings.twitter_min_interval_seconds)

    if close_storage:
        storage.close()

    return {
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "antibot_stopped": antibot_stopped,
    }


def _is_twitter_antibot(message: str) -> bool:
    if is_playwright_antibot_error(message):
        return True
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "login wall",
            "blocked automated",
            "rate limit",
            "something went wrong",
        )
    )
