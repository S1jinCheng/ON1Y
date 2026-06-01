"""Background worker — consumes pending_urls queue."""

from __future__ import annotations

import logging
import signal
import time

from on1y.alerts import maybe_alert_from_error
from on1y.adapters.sqlite_storage import SqliteStorage, get_storage
from on1y.config import get_settings
from on1y.exceptions import DuplicateVideoError, ExtractionError
from on1y.extract.registry import get_default_registry
from on1y.logging import setup_logging
from on1y.pipeline.processor import process_url

logger = logging.getLogger(__name__)

_stop = False


def _platform_from_url(url: str) -> str:
    from on1y.utils.platform import detect_platform

    return detect_platform(url) or "unknown"


def _handle_signal(signum: int, frame: object) -> None:
    global _stop
    logger.info("Received signal %s, shutting down gracefully...", signum)
    _stop = True


def run_worker(*, once: bool = False, storage: SqliteStorage | None = None) -> None:
    setup_logging()
    settings = get_settings()
    settings.ensure_data_dir()

    storage = storage or get_storage()
    registry = get_default_registry()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "Worker started (poll=%ss, max_retries=%s)",
        settings.worker_poll_seconds,
        settings.worker_max_retries,
    )

    while not _stop:
        pending = storage.claim_next_pending()
        if pending is None:
            if once:
                logger.info("Queue empty, exiting (--once).")
                break
            time.sleep(settings.worker_poll_seconds)
            continue

        logger.info("Processing pending id=%s url=%s", pending.id, pending.url)
        try:
            process_url(
                storage,
                pending.url,
                source=pending.source,
                source_meta=pending.source_meta,
                registry=registry,
            )
            storage.mark_pending_done(pending.id)
        except DuplicateVideoError as exc:
            storage.mark_pending_done(pending.id)
            logger.info(
                "Skipped duplicate video id=%s url=%s (kept youtube raw_id=%s)",
                pending.id,
                pending.url,
                exc.preferred_raw_id,
            )
        except ExtractionError as exc:
            msg = str(exc)
            retry = pending.attempts < settings.worker_max_retries
            storage.mark_pending_failed(pending.id, msg, retry=retry)
            maybe_alert_from_error(
                msg,
                platform=_platform_from_url(pending.url),
                worker="ingest",
                url=pending.url,
            )
            logger.error(
                "Extraction failed id=%s retry=%s: %s",
                pending.id,
                retry,
                exc,
            )
        except Exception as exc:
            msg = f"unexpected: {exc}"
            retry = pending.attempts < settings.worker_max_retries
            storage.mark_pending_failed(pending.id, msg, retry=retry)
            maybe_alert_from_error(
                msg,
                platform=_platform_from_url(pending.url),
                worker="ingest",
                url=pending.url,
            )
            logger.exception("Unexpected error for pending id=%s", pending.id)

        if once:
            break

    storage.close()
    logger.info("Worker stopped.")


def _process_one_pending(
    storage: SqliteStorage,
    pending,
    *,
    registry,
) -> str:
    """Process one queue item. Returns 'processed', 'failed', or 'empty'."""
    logger.info("Processing pending id=%s url=%s", pending.id, pending.url)
    try:
        process_url(
            storage,
            pending.url,
            source=pending.source,
            source_meta=pending.source_meta,
            registry=registry,
        )
        storage.mark_pending_done(pending.id)
        return "processed"
    except DuplicateVideoError as exc:
        storage.mark_pending_done(pending.id)
        logger.info(
            "Skipped duplicate video id=%s url=%s (kept youtube raw_id=%s)",
            pending.id,
            pending.url,
            exc.preferred_raw_id,
        )
        return "processed"
    except ExtractionError as exc:
        msg = str(exc)
        retry = pending.attempts < get_settings().worker_max_retries
        storage.mark_pending_failed(pending.id, msg, retry=retry)
        maybe_alert_from_error(
            msg,
            platform=_platform_from_url(pending.url),
            worker="ingest",
            url=pending.url,
        )
        logger.error("Extraction failed id=%s retry=%s: %s", pending.id, retry, exc)
        return "failed"
    except Exception as exc:
        msg = f"unexpected: {exc}"
        retry = pending.attempts < get_settings().worker_max_retries
        storage.mark_pending_failed(pending.id, msg, retry=retry)
        maybe_alert_from_error(
            msg,
            platform=_platform_from_url(pending.url),
            worker="ingest",
            url=pending.url,
        )
        logger.exception("Unexpected error for pending id=%s", pending.id)
        return "failed"


def run_worker_batch(
    storage: SqliteStorage,
    limit: int,
    *,
    close_storage: bool = False,
    platform: str | None = None,
) -> dict[str, int]:
    """Process up to `limit` pending URLs. Optionally filter by platform."""
    from on1y.extract.registry import get_default_registry

    registry = get_default_registry()
    processed = 0
    failed = 0
    claim = (
        (lambda: storage.claim_next_pending_for_platform(platform))
        if platform
        else storage.claim_next_pending
    )

    for _ in range(max(0, limit)):
        pending = claim()
        if pending is None:
            break
        outcome = _process_one_pending(storage, pending, registry=registry)
        if outcome == "processed":
            processed += 1
        else:
            failed += 1

    if close_storage:
        storage.close()
    return {"processed": processed, "failed": failed}
