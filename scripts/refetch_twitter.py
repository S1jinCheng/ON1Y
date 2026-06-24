"""Re-fetch ingested X/Twitter raw_items with the structured Markdown extractor."""
from __future__ import annotations

import argparse
import logging

from on1y.adapters.sqlite_storage import get_storage
from on1y.auth.context import user_context
from on1y.distill.processor import maybe_package_short_content
from on1y.extract.twitter import TwitterExtractor

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _twitter_raw_ids(storage, *, limit: int | None) -> list[tuple[int, str]]:
    conn = storage._connect()
    query = """
        SELECT id, url FROM raw_items
        WHERE platform = 'twitter' AND deleted_at IS NULL
        ORDER BY id ASC
    """
    params: list[object] = []
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [(int(r["id"]), str(r["url"])) for r in rows]


def refetch_ingested(*, user_id: int, limit: int | None, delay: bool) -> dict[str, int]:
    extractor = TwitterExtractor()
    storage = get_storage()
    stats = {"ok": 0, "failed": 0, "skipped": 0}
    try:
        with user_context(user_id):
            items = _twitter_raw_ids(storage, limit=limit)
            logger.info("Re-fetching %s ingested twitter item(s)", len(items))
            from on1y.browser.playwright_isolated import run_playwright_isolated
            from on1y.browser.playwright_session import PlaywrightSession
            from on1y.config import get_settings

            settings = get_settings()

            def _run_batch() -> None:
                with PlaywrightSession(
                    cookie_path=extractor.cookie_path(settings),
                    seed_domain=extractor.seed_domain(),
                ) as session:
                    for raw_id, url in items:
                        try:
                            result = extractor.extract(url, session=session)
                            raw = storage.get_raw_by_id(raw_id)
                            if raw is None:
                                stats["skipped"] += 1
                                continue
                            meta = dict(raw.source_meta or {})
                            if result.source_meta:
                                meta.update(result.source_meta)
                            from on1y.utils.author_meta import author_meta_patch
                            from on1y.knowledge.creators import normalize_twitter_author_url

                            patch = author_meta_patch(
                                author=result.author,
                                author_avatar=result.author_avatar,
                                author_url=result.author_url,
                            )
                            if patch.get("author_url"):
                                patch["author_url"] = normalize_twitter_author_url(
                                    patch["author_url"]
                                )
                            meta.update(patch)
                            from on1y.models.enums import ContentType, ExtractStatus, SourceType
                            from on1y.models.raw import RawItemCreate

                            create = RawItemCreate(
                                url=raw.url,
                                platform=raw.platform,
                                source=raw.source,
                                raw_title=result.raw_title or raw.raw_title,
                                body_text=result.body_text,
                                content_type=result.content_type or ContentType.ARTICLE,
                                extract_status=result.extract_status or ExtractStatus.OK,
                                extract_error=result.extract_error,
                                source_meta=meta,
                            )
                            updated = storage.upsert_raw_item(create)
                            maybe_package_short_content(storage, updated.id, updated.body_text)
                            stats["ok"] += 1
                            logger.info("OK raw_id=%s url=%s", raw_id, url)
                            if delay and settings.twitter_min_interval_seconds > 0:
                                import time

                                time.sleep(settings.twitter_min_interval_seconds)
                        except Exception as exc:
                            stats["failed"] += 1
                            logger.error("FAIL raw_id=%s url=%s: %s", raw_id, url, exc)

            run_playwright_isolated(_run_batch)
    finally:
        storage.close()
    return stats


def drain_pending(*, user_id: int, batch_size: int, max_rounds: int) -> dict[str, object]:
    storage = get_storage()
    try:
        with user_context(user_id):
            from on1y.pipeline.twitter_catchup import run_twitter_catchup

            return run_twitter_catchup(
                storage,
                ingest_per_round=batch_size,
                max_rounds=max_rounds,
            )
    finally:
        storage.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-fetch X/Twitter content")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--ingested-limit", type=int, default=0, help="0 = all ingested")
    parser.add_argument("--pending-batch", type=int, default=15)
    parser.add_argument("--pending-rounds", type=int, default=20)
    parser.add_argument("--skip-pending", action="store_true")
    parser.add_argument("--skip-ingested", action="store_true")
    parser.add_argument("--no-delay", action="store_true")
    args = parser.parse_args()

    ingested_limit = None if args.ingested_limit <= 0 else args.ingested_limit

    if not args.skip_ingested:
        ingested = refetch_ingested(
            user_id=args.user_id,
            limit=ingested_limit,
            delay=not args.no_delay,
        )
        logger.info("Ingested re-fetch: %s", ingested)

    if not args.skip_pending:
        pending = drain_pending(
            user_id=args.user_id,
            batch_size=args.pending_batch,
            max_rounds=args.pending_rounds,
        )
        logger.info("Pending drain: %s", pending)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
