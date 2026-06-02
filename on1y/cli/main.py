"""On1y CLI entrypoint: `on1y <command>`."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from on1y import __version__
from on1y.adapters.sqlite_storage import get_storage
from on1y.config import get_settings
from on1y.ingestion.enqueue import enqueue_url
from on1y.ingestion.rss import (
    list_feed_status,
    load_feeds,
    poll_rss_feeds,
    poll_rss_feeds_backfill,
    reset_feed_cursor,
)
from on1y.logging import setup_logging
from on1y.models.enums import SourceType
from on1y.pipeline.processor import process_url
from on1y.pipeline.worker import run_worker


def _cmd_init(_: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_data_dir()
    storage = get_storage()
    storage.close()
    print(f"Database initialized at {settings.db_path}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_data_dir()
    storage = get_storage()

    if args.queue:
        pending_id = enqueue_url(storage, args.url, source=SourceType.MANUAL)
        storage.close()
        print(
            json.dumps(
                {"queued": True, "pending_id": pending_id, "url": args.url},
                ensure_ascii=False,
            )
        )
        return 0

    raw = process_url(storage, args.url, source=SourceType.MANUAL)
    storage.close()
    print(
        json.dumps(
            {
                "id": raw.id,
                "url": raw.url,
                "platform": raw.platform,
                "extract_status": raw.extract_status.value,
                "word_count": raw.word_count,
                "title": raw.raw_title,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_enqueue(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_data_dir()
    storage = get_storage()
    source = SourceType(args.source)
    pending_id = enqueue_url(storage, args.url, source=source)
    storage.close()
    print(json.dumps({"pending_id": pending_id, "url": args.url}, ensure_ascii=False))
    return 0


def _cmd_worker(args: argparse.Namespace) -> int:
    run_worker(once=args.once)
    return 0


def _cmd_subtitles(args: argparse.Namespace) -> int:
    from on1y.pipeline.backfill import backfill_video_subtitle_jobs
    from on1y.pipeline.subtitle_worker import run_subtitle_batch

    storage = get_storage()
    try:
        if getattr(args, "subtitles_action", None) == "backfill":
            count = backfill_video_subtitle_jobs(storage)
            print(json.dumps({"backfilled": count}, ensure_ascii=False))
            return 0
        result = run_subtitle_batch(storage, args.limit)
    finally:
        storage.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_catchup(args: argparse.Namespace) -> int:
    from on1y.pipeline.catchup import run_catchup

    storage = get_storage()
    try:
        result = run_catchup(
            storage,
            ingest_batch=args.ingest_batch,
            subtitle_batch=args.subtitle_batch,
            max_rounds=args.max_rounds,
            pause_seconds=args.pause,
        )
    finally:
        storage.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_pipeline_youtube(args: argparse.Namespace) -> int:
    from on1y.pipeline.run_youtube import run_youtube_pipeline

    storage = get_storage()
    try:
        result = run_youtube_pipeline(
            storage,
            ingest_limit=args.ingest,
            subtitle_limit=args.subtitles,
            distill_limit=args.distill,
        )
    finally:
        storage.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_pipeline_zhihu(args: argparse.Namespace) -> int:
    storage = get_storage()
    try:
        if getattr(args, "catchup", False):
            from on1y.pipeline.zhihu_catchup import run_zhihu_catchup

            result = run_zhihu_catchup(
                storage,
                ingest_per_round=max(1, args.ingest),
                max_rounds=args.max_rounds,
            )
            print(json.dumps({"catchup": result}, ensure_ascii=False, indent=2))
            return 0 if not result.get("antibot_stopped") else 1

        from on1y.pipeline.run_zhihu import run_zhihu_pipeline

        result = run_zhihu_pipeline(
            storage,
            ingest_limit=args.ingest,
            distill_limit=args.distill,
        )
    finally:
        storage.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not (result.get("ingest") or {}).get("antibot_stopped") else 1


def _cmd_hotlist(args: argparse.Namespace) -> int:
    if getattr(args, "hotlist_action", None) == "auto":
        return _cmd_hotlist_auto(args)

    from on1y.hotlist import sync_hotlists

    storage = get_storage()
    try:
        report = sync_hotlists(
            storage,
            sources=args.sources,
            auto_distill=args.auto_distill,
            auto_tag=not getattr(args, "no_auto_tag", False),
        )
    finally:
        storage.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_hotlist_auto(args: argparse.Namespace) -> int:
    from on1y.hotlist.economist_auto import run_economist_auto_tick

    report = run_economist_auto_tick(
        force_edition=(getattr(args, "edition_date", None) or "").strip() or None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report.get("errors") else 1


def _cmd_subscriptions(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    from on1y.subscriptions import sync_subscriptions

    sync_since_ts: int | None = None
    if args.since:
        try:
            day = datetime.strptime(args.since.strip(), "%Y-%m-%d").date()
        except ValueError:
            print(json.dumps({"error": f"invalid --since date: {args.since!r}"}, ensure_ascii=False))
            return 1
        sync_since_ts = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())

    storage = get_storage()
    try:
        report = sync_subscriptions(
            storage,
            platform=args.platform,
            sync_config=not args.poll_only,
            poll=not args.config_only and not args.dry_run,
            backfill=args.backfill,
            dry_run=args.dry_run,
            sync_since_ts=sync_since_ts,
            sync_hotlist=args.sync_hotlist,
            refresh_feeds=args.refresh_feeds or None,
        )
        if args.ingest and not args.dry_run and not args.config_only:
            if args.platform in {"bilibili", "all"}:
                from on1y.pipeline.video_enrich import run_video_enrich_pipeline

                report["enrich"] = run_video_enrich_pipeline(
                    storage,
                    platform="bilibili",
                    ingest_limit=args.ingest_limit,
                    subtitle_limit=args.subtitle_limit,
                    distill_limit=args.distill_limit,
                )
            if args.platform in {"youtube", "zhihu", "all"}:
                from on1y.pipeline.worker import run_worker_batch

                report["worker"] = run_worker_batch(
                    storage, args.ingest_limit, close_storage=False
                )
    finally:
        storage.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    from on1y.pipeline.bootstrap import run_bootstrap

    if args.youtube or args.zhihu:
        youtube = args.youtube
        zhihu = args.zhihu
    else:
        youtube = zhihu = True

    storage = get_storage()
    try:
        result = run_bootstrap(
            storage,
            youtube=youtube,
            zhihu=zhihu,
            sync_zhihu_follows=args.sync_zhihu_follows,
            sync_zhihu_favlists=args.sync_zhihu_favlists,
            max_feed_items=args.max_feed_items,
            youtube_ingest_batch=args.youtube_ingest_batch,
            youtube_subtitle_batch=args.youtube_subtitle_batch,
            zhihu_max_rounds=args.zhihu_max_rounds,
            pause_seconds=args.pause,
        )
    finally:
        storage.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_rss_poll(storage, args: argparse.Namespace) -> int:
    if getattr(args, "backfill", False):
        count = poll_rss_feeds_backfill(
            storage,
            label=getattr(args, "label", None),
            label_prefix=getattr(args, "label_prefix", None),
            max_items_per_feed=args.max_items,
        )
    else:
        count = poll_rss_feeds(storage)
    print(json.dumps({"enqueued": count}, ensure_ascii=False))
    return 0


def _cmd_rss_feeds(_: argparse.Namespace) -> int:
    feeds = load_feeds()
    print(json.dumps([{"label": f.label, "url": f.url, "enabled": f.enabled} for f in feeds], indent=2))
    return 0


def _cmd_rss_status(storage, _: argparse.Namespace) -> int:
    rows = list_feed_status(storage)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    storage.close()
    return 0


def _cmd_rss_reset(storage, args: argparse.Namespace) -> int:
    if not args.label:
        storage.close()
        print("Usage: on1y rss reset <feed-label>", file=sys.stderr)
        return 1
    if not reset_feed_cursor(storage, args.label):
        storage.close()
        print(f"Unknown feed label: {args.label}", file=sys.stderr)
        return 1
    storage.close()
    print(json.dumps({"reset": args.label}, ensure_ascii=False))
    return 0


def _cmd_rss_run(storage, args: argparse.Namespace) -> int:
    enqueued = poll_rss_feeds(storage)
    processed = 0
    for _ in range(args.limit):
        pending = storage.claim_next_pending()
        if pending is None:
            break
        try:
            process_url(storage, pending.url, source=pending.source, source_meta=pending.source_meta)
            storage.mark_pending_done(pending.id)
            processed += 1
        except Exception as exc:
            import logging

            retry = pending.attempts < get_settings().worker_max_retries
            storage.mark_pending_failed(pending.id, str(exc), retry=retry)
            logging.getLogger(__name__).error("RSS run failed for %s: %s", pending.url, exc)
    storage.close()
    print(json.dumps({"enqueued": enqueued, "processed": processed}, ensure_ascii=False))
    return 0


def _cmd_rss(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_data_dir()
    storage = get_storage()
    action = args.rss_action
    if action == "poll":
        rc = _cmd_rss_poll(storage, args)
    elif action == "feeds":
        storage.close()
        rc = _cmd_rss_feeds(args)
    elif action == "status":
        rc = _cmd_rss_status(storage, args)
    elif action == "reset":
        rc = _cmd_rss_reset(storage, args)
    elif action == "run":
        rc = _cmd_rss_run(storage, args)
    else:
        storage.close()
        return 1
    if action != "status" and action != "feeds":
        storage.close()
    return rc


def _cmd_list(args: argparse.Namespace) -> int:
    storage = get_storage()
    items = storage.list_raw_items(
        platform=args.platform,
        source=args.source,
        limit=args.limit,
        offset=args.offset,
    )
    storage.close()
    payload = [
        {
            "id": i.id,
            "url": i.url,
            "platform": i.platform,
            "source": i.source.value,
            "title": i.raw_title,
            "extract_status": i.extract_status.value,
            "word_count": i.word_count,
            "ingested_at": i.ingested_at.isoformat() if i.ingested_at else None,
        }
        for i in items
    ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_user_password(args: argparse.Namespace) -> int:
    from on1y.user.accounts import UserStore

    storage = get_storage()
    try:
        store = UserStore(storage)
        user = store.set_password(args.username, args.password)
        print(f"Password updated for user {user.username!r} (id={user.id})")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        storage.close()
    return 0


def _cmd_cookies_status(_: argparse.Namespace) -> int:
    from on1y.config import get_settings
    from on1y.cookies.loader import PLATFORM_COOKIE_ATTR, cookie_file_status

    settings = get_settings()
    rows = [cookie_file_status(platform, settings) for platform in PLATFORM_COOKIE_ATTR]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    missing = [r["platform"] for r in rows if not r["exists"]]
    if missing and settings.require_login_cookies:
        print(
            f"\nMissing cookies for: {', '.join(missing)}. "
            "Run: python scripts/export_cookies.py <platform>",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    storage = get_storage()
    raw = None
    if args.url:
        raw = storage.get_raw_by_url(args.url)
    if raw is None and args.id is not None:
        raw = storage.get_raw_by_id(args.id)
    storage.close()
    if raw is None:
        print("Not found", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "id": raw.id,
                "url": raw.url,
                "platform": raw.platform,
                "source": raw.source.value,
                "title": raw.raw_title,
                "extract_status": raw.extract_status.value,
                "word_count": raw.word_count,
                "body_preview": (raw.body_text or "")[:500],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="on1y",
        description="On1y Phase 1 — ingestion and extraction",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize database schema")
    p_init.set_defaults(func=_cmd_init)

    p_ingest = sub.add_parser("ingest", help="Extract URL and store (or queue with --queue)")
    p_ingest.add_argument("url", help="URL to ingest")
    p_ingest.add_argument(
        "--queue",
        action="store_true",
        help="Enqueue only; process later with `on1y worker`",
    )
    p_ingest.set_defaults(func=_cmd_ingest)

    p_enq = sub.add_parser("enqueue", help="Add URL to pending queue")
    p_enq.add_argument("url")
    p_enq.add_argument(
        "--source",
        default=SourceType.MANUAL.value,
        choices=[s.value for s in SourceType],
    )
    p_enq.set_defaults(func=_cmd_enqueue)

    p_worker = sub.add_parser("worker", help="Process pending URL queue")
    p_worker.add_argument("--once", action="store_true", help="Process one item then exit")
    p_worker.set_defaults(func=_cmd_worker)

    p_sub = sub.add_parser(
        "subtitles",
        help="Video phase B: fetch subtitles (YouTube, Bilibili)",
    )
    p_sub.add_argument(
        "subtitles_action",
        nargs="?",
        choices=["run", "backfill"],
        default="run",
    )
    p_sub.add_argument("--limit", type=int, default=10)
    p_sub.set_defaults(func=_cmd_subtitles)

    p_catchup = sub.add_parser(
        "catchup",
        help="Drain backlog: ingest all pending URLs + fetch all subtitles (no LLM)",
    )
    p_catchup.add_argument("--ingest-batch", type=int, default=20)
    p_catchup.add_argument("--subtitle-batch", type=int, default=10)
    p_catchup.add_argument("--max-rounds", type=int, default=500)
    p_catchup.add_argument("--pause", type=float, default=1.0, help="Seconds between rounds")
    p_catchup.set_defaults(func=_cmd_catchup)

    p_pipe = sub.add_parser("pipeline", help="Run multi-phase pipelines")
    p_pipe_sub = p_pipe.add_subparsers(dest="pipeline_action", required=True)
    p_yt = p_pipe_sub.add_parser(
        "youtube",
        help="ingest (fast) → subtitles → distill (RSS→标签一条龙)",
    )
    p_yt.add_argument("--ingest", type=int, default=10, help="Max pending_urls to fast-ingest")
    p_yt.add_argument("--subtitles", type=int, default=10, help="Max subtitle jobs")
    p_yt.add_argument("--distill", type=int, default=5, help="Max LLM distill (0=skip)")
    p_yt.set_defaults(func=_cmd_pipeline_youtube)

    p_zh = p_pipe_sub.add_parser(
        "zhihu",
        help="Playwright ingest → LLM distill (RSSHub 知乎订阅)",
    )
    p_zh.add_argument(
        "--ingest",
        type=int,
        default=3,
        help="Max Zhihu pending_urls to extract (default 3, spaced for anti-bot)",
    )
    p_zh.add_argument("--distill", type=int, default=5, help="Max LLM distill (0=skip)")
    p_zh.add_argument(
        "--catchup",
        action="store_true",
        help="Cold-start: drain all Zhihu pending_urls (respects anti-bot stops)",
    )
    p_zh.add_argument(
        "--max-rounds",
        type=int,
        default=500,
        help="Max rounds for --catchup",
    )
    p_zh.set_defaults(func=_cmd_pipeline_zhihu)

    p_boot = sub.add_parser(
        "bootstrap",
        help="Cold-start: RSS backfill + YouTube/Zhihu catchup (no LLM)",
    )
    p_boot.add_argument("--youtube", action="store_true", help="YouTube only")
    p_boot.add_argument("--zhihu", action="store_true", help="Zhihu only")
    p_boot.add_argument(
        "--sync-zhihu-follows",
        action="store_true",
        help="Pull Zhihu follow list into config before backfill",
    )
    p_boot.add_argument(
        "--sync-zhihu-favlists",
        action="store_true",
        help="Pull Zhihu 收藏夹 into config before backfill",
    )
    p_boot.add_argument(
        "--max-feed-items",
        type=int,
        default=None,
        help="Max RSS entries per feed (default ON1Y_RSS_BACKFILL_MAX_ITEMS_PER_FEED)",
    )
    p_boot.add_argument("--youtube-ingest-batch", type=int, default=15)
    p_boot.add_argument("--youtube-subtitle-batch", type=int, default=8)
    p_boot.add_argument("--zhihu-max-rounds", type=int, default=500)
    p_boot.add_argument("--pause", type=float, default=1.0, help="YouTube catchup pause between rounds")
    p_boot.set_defaults(func=_cmd_bootstrap)

    p_subs = sub.add_parser(
        "subscriptions",
        help="Sync subscriptions: bilibili (API), youtube/zhihu (RSS), all",
    )
    p_subs.add_argument(
        "--platform",
        choices=["bilibili", "youtube", "zhihu", "all"],
        default="bilibili",
        help=(
            "bilibili=dynamic UP feed; youtube/zhihu=RSS feeds (yt-/zhihu-); "
            "zhihu does not include hotlist (use: on1y hotlist sync); all=bilibili+youtube+zhihu RSS"
        ),
    )
    p_subs.add_argument(
        "--refresh-feeds",
        action="store_true",
        help="Refresh feeds.yaml from YouTube/Zhihu follow lists before RSS poll",
    )
    p_subs.add_argument(
        "--sync-hotlist",
        action="store_true",
        help="Also sync Zhihu hotlist (off by default for --platform zhihu)",
    )
    p_subs.add_argument(
        "--config-only",
        action="store_true",
        help="Only refresh feeds.yaml from platform follow list",
    )
    p_subs.add_argument(
        "--poll-only",
        action="store_true",
        help="Only poll for new content (skip feeds.yaml merge)",
    )
    p_subs.add_argument(
        "--backfill",
        action="store_true",
        help="Enqueue recent items per UP (cold start)",
    )
    p_subs.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Only sync items on/after this date (overrides saved settings)",
    )
    p_subs.add_argument("--dry-run", action="store_true")
    p_subs.add_argument(
        "--ingest",
        action="store_true",
        help="After poll, ingest + subtitles + LLM distill (Bilibili)",
    )
    p_subs.add_argument("--ingest-limit", type=int, default=10)
    p_subs.add_argument(
        "--subtitle-limit",
        type=int,
        default=10,
        help="Max subtitle jobs when --ingest (default 10)",
    )
    p_subs.add_argument(
        "--distill-limit",
        type=int,
        default=10,
        help="Max LLM distill jobs when --ingest (default 10)",
    )
    p_subs.set_defaults(func=_cmd_subscriptions)

    p_hotlist = sub.add_parser("hotlist", help="Daily hot-list column sync")
    p_hotlist_sub = p_hotlist.add_subparsers(dest="hotlist_action", required=True)
    p_hotlist_sync = p_hotlist_sub.add_parser("sync", help="Sync hot lists (zhihu, economist, …)")
    p_hotlist_sync.add_argument(
        "--source",
        action="append",
        dest="sources",
        default=["zhihu"],
        choices=["zhihu", "economist"],
        help="Hot-list source (repeatable; default: zhihu)",
    )
    p_hotlist_sync.add_argument(
        "--auto-distill",
        action="store_true",
        help="Run full LLM distill after ingest (optional)",
    )
    p_hotlist_sync.add_argument(
        "--no-auto-tag",
        action="store_true",
        help="Skip LLM research tags (default: tag new/changed items)",
    )
    p_hotlist_sync.set_defaults(func=_cmd_hotlist)
    p_hotlist_auto = p_hotlist_sub.add_parser(
        "auto",
        help="Auto-detect new Economist edition on GitHub; ingest + optional Kindle email",
    )
    p_hotlist_auto.add_argument(
        "--edition-date",
        default=None,
        help="Force sync/send this edition (YYYY-MM-DD); default: latest on GitHub only if new",
    )
    p_hotlist_auto.set_defaults(func=_cmd_hotlist)

    p_rss = sub.add_parser("rss", help="RSS subscriptions (config/feeds.yaml)")
    p_rss.add_argument(
        "rss_action",
        choices=["poll", "feeds", "status", "reset", "run"],
        nargs="?",
        default="poll",
        help="poll=enqueue new; run=poll+process; feeds/status=config",
    )
    p_rss.add_argument("label", nargs="?", help="Feed label (for reset)")
    p_rss.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max queue items to process in `rss run`",
    )
    p_rss.add_argument(
        "--backfill",
        action="store_true",
        help="Cold-start: enqueue up to --max-items entries per feed (skip already stored)",
    )
    p_rss.add_argument(
        "--max-items",
        type=int,
        default=100,
        help="Max entries per feed for --backfill",
    )
    p_rss.add_argument(
        "--label-prefix",
        default=None,
        help="Only backfill feeds whose label starts with this prefix (e.g. zhihu-, yt-)",
    )
    p_rss.set_defaults(func=_cmd_rss)

    p_list = sub.add_parser("list", help="List stored raw items")
    p_list.add_argument("--platform", default=None)
    p_list.add_argument("--source", default=None)
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--offset", type=int, default=0)
    p_list.set_defaults(func=_cmd_list)

    p_user = sub.add_parser("user", help="Multi-user account management")
    p_user_sub = p_user.add_subparsers(dest="user_action", required=True)
    p_user_pass = p_user_sub.add_parser("passwd", help="Reset a user's login password")
    p_user_pass.add_argument("username", help="Username (e.g. admin)")
    p_user_pass.add_argument("password", help="New password (min 8 characters)")
    p_user_pass.set_defaults(func=_cmd_user_password)

    p_cookies = sub.add_parser("cookies", help="Check login cookie files")
    p_cookies.add_argument("action", choices=["status"], nargs="?", default="status")
    p_cookies.set_defaults(func=_cmd_cookies_status)

    p_show = sub.add_parser("show", help="Show one raw item")
    p_show.add_argument("--url", default=None)
    p_show.add_argument("--id", type=int, default=None)
    p_show.set_defaults(func=_cmd_show)

    p_search = sub.add_parser("search", help="Full-text search over knowledge archive")
    p_search.add_argument(
        "search_action",
        nargs="?",
        choices=["query", "rebuild"],
        default="query",
    )
    p_search.add_argument("terms", nargs="*", help="Search terms (ANDed)")
    p_search.add_argument("--query", "-q", dest="query_opt", default=None, help="Search string")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--offset", type=int, default=0)
    p_search.add_argument("--platform", default=None)
    p_search.add_argument("--source", default=None)
    p_search.set_defaults(func=_cmd_search)

    p_serve = sub.add_parser("serve", help="Start local web dashboard")
    p_serve.add_argument("--host", default=None, help="Bind host (default ON1Y_WEB_HOST)")
    p_serve.add_argument("--port", type=int, default=None, help="Bind port (default ON1Y_WEB_PORT)")
    p_serve.set_defaults(func=_cmd_serve)

    p_distill = sub.add_parser("distill", help="Phase 2: LLM classify & summarize raw_items")
    p_distill.add_argument(
        "distill_action",
        nargs="?",
        choices=["run", "list", "show"],
        default="run",
    )
    p_distill.add_argument("--id", type=int, default=None, help="raw_items.id")
    p_distill.add_argument("--limit", type=int, default=10)
    p_distill.add_argument("--force", action="store_true", help="Re-distill even if exists")
    p_distill.set_defaults(func=_cmd_distill)

    p_alerts = sub.add_parser("alerts", help="View pipeline alerts (429 / 风控)")
    p_alerts.add_argument(
        "alerts_action",
        nargs="?",
        choices=["list", "clear"],
        default="list",
    )
    p_alerts.add_argument("--limit", type=int, default=20)
    p_alerts.add_argument("--active", action="store_true", help="Only unacknowledged alerts")
    p_alerts.set_defaults(func=_cmd_alerts)

    return parser


def _cmd_alerts(args: argparse.Namespace) -> int:
    from on1y.alerts import acknowledge_alerts, list_alerts

    if args.alerts_action == "clear":
        count = acknowledge_alerts(clear_all=True)
        print(json.dumps({"cleared": count}, ensure_ascii=False))
        return 0

    rows = list_alerts(limit=args.limit, active_only=args.active)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    if rows and args.active:
        return 1
    return 0


def _cmd_distill(args: argparse.Namespace) -> int:
    from on1y.distill.processor import distill_raw_item, list_distill_candidate_ids
    from on1y.exceptions import ConfigurationError

    storage = get_storage()
    try:
        if args.distill_action == "list":
            rows = storage.list_distilled_summary(limit=args.limit)
            storage.close()
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0

        if args.distill_action == "show":
            if args.id is None:
                print("Usage: on1y distill show --id <raw_id>", file=sys.stderr)
                storage.close()
                return 1
            detail = storage.get_distilled_detail(args.id)
            storage.close()
            if detail is None:
                print("Not distilled yet. Run: on1y distill --id", args.id, file=sys.stderr)
                return 1
            print(json.dumps(detail, ensure_ascii=False, indent=2, default=str))
            return 0

        if args.id is not None:
            ids = [args.id]
        else:
            ids = list_distill_candidate_ids(storage, limit=args.limit, force=args.force)

        if not ids:
            storage.close()
            print(json.dumps({"distilled": 0, "message": "no items to distill"}, ensure_ascii=False))
            return 0

        ok, failed = 0, 0
        results: list[dict[str, object]] = []
        for raw_id in ids:
            try:
                did = distill_raw_item(storage, raw_id, force=args.force)
                ok += 1
                results.append({"raw_id": raw_id, "distilled_id": did, "status": "ok"})
            except Exception as exc:
                failed += 1
                results.append({"raw_id": raw_id, "status": "failed", "error": str(exc)})
                logging.getLogger(__name__).error("Distill failed raw_id=%s: %s", raw_id, exc)

        storage.close()
        print(
            json.dumps(
                {"distilled": ok, "failed": failed, "items": results},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if failed == 0 else 1
    except ConfigurationError as exc:
        storage.close()
        print(str(exc), file=sys.stderr)
        return 1


def _cmd_search(args: argparse.Namespace) -> int:
    storage = get_storage()
    try:
        if args.search_action == "rebuild":
            from on1y.search.fts import rebuild_knowledge_fts

            conn = storage._connect()
            count = rebuild_knowledge_fts(conn)
            conn.commit()
            print(json.dumps({"rebuilt": count, "engine": "fts5-trigram"}, ensure_ascii=False))
            return 0

        query = args.query_opt or " ".join(args.terms or []).strip()
        if not query:
            print("Usage: on1y search [-q QUERY | terms...]", file=sys.stderr)
            return 1
        result = storage.search_knowledge_items(
            query=query,
            limit=args.limit,
            offset=args.offset,
            platform=args.platform,
            source=args.source,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        storage.close()


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        from on1y.web.app import run_server
    except ImportError:
        print(
            "Web UI requires fastapi and uvicorn. Run: pip install -e .",
            file=sys.stderr,
        )
        return 1
    settings = get_settings()
    settings.ensure_data_dir()
    host = args.host or settings.web_host
    port = args.port or settings.web_port
    print(f"On1y dashboard: http://{host}:{port}/")
    print("Press Ctrl+C to stop.")
    run_server(host=host, port=port)
    return 0


def app(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(app())
