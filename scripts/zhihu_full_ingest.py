#!/usr/bin/env python3
"""
知乎关注源全量入库（在 RSS 可见范围内尽量抓全）。

限制：RSSHub 每个 activities/answers 源通常只有最近 ~20 条，无法拉取数年前的全部历史。
流程：同步关注列表 → 清空 zhihu_sync_since → RSS backfill → pipeline catchup → LLM 蒸馏。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from on1y.adapters.sqlite_storage import get_storage
from on1y.config import PROJECT_ROOT, get_settings
from on1y.ingestion.rss import poll_rss_feeds_backfill
from on1y.ingestion.zhihu_feeds import follows_from_file, merge_zhihu_feeds_yaml
from on1y.ingestion.zhihu_follow_list import (
    fetch_zhihu_favlists,
    fetch_zhihu_followees,
    merge_follows_file,
)
from on1y.pipeline.zhihu_catchup import run_zhihu_catchup
from on1y.subscriptions.settings import load_subscription_settings, save_subscription_settings
from on1y.utils.platform import PLATFORM_ZHIHU

logger = logging.getLogger(__name__)


def _count_zhihu_raw(storage) -> int:
    row = storage._connect().execute(
        "SELECT COUNT(*) AS c FROM raw_items WHERE platform = ?",
        (PLATFORM_ZHIHU,),
    ).fetchone()
    return int(row["c"]) if row else 0


def _ensure_rsshub(base: str, timeout: float = 5.0) -> None:
    url = base.rstrip("/") + "/"
    try:
        with httpx.Client(timeout=timeout) as client:
            client.get(url)
    except Exception as exc:
        raise SystemExit(
            f"RSSHub 不可用 ({base}): {exc}\n"
            "请先启动 Docker 容器，例如:\n"
            "  docker start rsshub\n"
            "  docker run -d --name rsshub -p 12000:1200 diygod/rsshub"
        ) from exc


def _expand_dual_answers(follows_path: Path) -> int:
    """为每个 activities 关注追加 answers 源（去重）。"""
    lines = follows_path.read_text(encoding="utf-8").splitlines()
    existing = {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}
    added = 0
    for line in list(lines):
        stripped = line.strip()
        if not stripped.startswith("activities:"):
            continue
        token = stripped.split(":", 1)[1].strip()
        answers_line = f"answers:{token}"
        if answers_line not in existing:
            lines.append(answers_line)
            existing.add(answers_line)
            added += 1
    if added:
        follows_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return added


def run_full_ingest(
    *,
    user_id: int = 1,
    sync_follows: bool = True,
    sync_favlists: bool = True,
    dual_answers: bool = True,
    clear_sync_since: bool = True,
    max_feed_items: int = 500,
    catchup_ingest_per_round: int = 1,
    catchup_max_rounds: int = 2000,
    antibot_retries: int = 3,
    distill_limit: int = 0,
) -> dict[str, Any]:
    settings = get_settings()
    _ensure_rsshub(settings.zhihu_rsshub_base)

    report: dict[str, Any] = {"steps": []}

    follows_path = PROJECT_ROOT / "config" / "zhihu_follows.txt"
    if sync_follows or sync_favlists:
        step: dict[str, Any] = {}
        if sync_follows:
            followees = fetch_zhihu_followees(settings=settings)
            added, total = merge_follows_file(followees, follows_path)
            step["followees"] = {"fetched": len(followees), "added": added, "total": total}
        if sync_favlists:
            favlists = fetch_zhihu_favlists(settings=settings)
            added, total = merge_follows_file(favlists, follows_path)
            step["favlists"] = {"fetched": len(favlists), "added": added, "total": total}
        if dual_answers:
            step["answers_lines_added"] = _expand_dual_answers(follows_path)
        follows = follows_from_file(follows_path)
        merged = merge_zhihu_feeds_yaml(
            follows,
            feeds_path=settings.rss_config_path,
            rsshub_base=settings.zhihu_rsshub_base,
            enabled=True,
            dry_run=False,
        )
        step["feeds_merged"] = merged
        report["steps"].append({"sync_feeds": step})

    if clear_sync_since:
        save_subscription_settings(zhihu_sync_since="", user_id=user_id)
        report["steps"].append(
            {
                "clear_sync_since": load_subscription_settings(user_id=user_id).get(
                    "zhihu_sync_since"
                )
            }
        )

    storage = get_storage()
    try:
        pending_before = storage.count_pending_for_platform(PLATFORM_ZHIHU)
        raw_before = _count_zhihu_raw(storage)

        enqueued = poll_rss_feeds_backfill(
            storage,
            label_prefix="zhihu-",
            max_items_per_feed=max_feed_items,
            skip_existing=True,
            sync_since_ts=None,
        )
        pending_after_poll = storage.count_pending_for_platform(PLATFORM_ZHIHU)
        report["steps"].append(
            {
                "rss_backfill": {
                    "enqueued": enqueued,
                    "pending_before": pending_before,
                    "pending_after_poll": pending_after_poll,
                    "max_feed_items": max_feed_items,
                }
            }
        )

        catchup_totals: dict[str, Any] = {
            "processed": 0,
            "failed": 0,
            "rounds": 0,
            "antibot_stopped": False,
            "retries": 0,
        }
        for attempt in range(antibot_retries + 1):
            result = run_zhihu_catchup(
                storage,
                ingest_per_round=max(1, catchup_ingest_per_round),
                max_rounds=catchup_max_rounds,
            )
            catchup_totals["processed"] += int(result["processed"])
            catchup_totals["failed"] += int(result["failed"])
            catchup_totals["rounds"] += int(result["rounds"])
            pending_left = int(result["queue_pending"])
            if not result["antibot_stopped"]:
                catchup_totals["pending_left"] = pending_left
                break
            catchup_totals["antibot_stopped"] = True
            catchup_totals["retries"] = attempt + 1
            if attempt < antibot_retries and pending_left > 0:
                wait = settings.zhihu_antibot_pause_seconds
                logger.warning(
                    "Anti-bot pause %.0fs then retry (%s/%s)",
                    wait,
                    attempt + 1,
                    antibot_retries,
                )
                time.sleep(wait)
            else:
                catchup_totals["pending_left"] = pending_left
                break

        report["steps"].append({"catchup": catchup_totals})

        if distill_limit > 0:
            from on1y.distill.processor import run_distill_batch

            distill = run_distill_batch(storage, distill_limit, platform=PLATFORM_ZHIHU)
            report["steps"].append({"distill": distill})

        report["summary"] = {
            "raw_zhihu_before": raw_before,
            "raw_zhihu_after": _count_zhihu_raw(storage),
            "pending_left": storage.count_pending_for_platform(PLATFORM_ZHIHU),
            "new_raw_items": _count_zhihu_raw(storage) - raw_before,
        }
    finally:
        storage.close()

    return report


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Zhihu follow feeds: RSS backfill + catchup")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--no-sync-follows", action="store_true")
    parser.add_argument("--no-favlists", action="store_true")
    parser.add_argument("--no-dual-answers", action="store_true")
    parser.add_argument("--keep-sync-since", action="store_true")
    parser.add_argument("--max-feed-items", type=int, default=500)
    parser.add_argument("--ingest-per-round", type=int, default=1)
    parser.add_argument("--max-rounds", type=int, default=2000)
    parser.add_argument("--distill", type=int, default=0, help="Max LLM distill after ingest")
    args = parser.parse_args()

    report = run_full_ingest(
        user_id=args.user_id,
        sync_follows=not args.no_sync_follows,
        sync_favlists=not args.no_favlists,
        dual_answers=not args.no_dual_answers,
        clear_sync_since=not args.keep_sync_since,
        max_feed_items=args.max_feed_items,
        catchup_ingest_per_round=args.ingest_per_round,
        catchup_max_rounds=args.max_rounds,
        distill_limit=args.distill,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    pending = report.get("summary", {}).get("pending_left", 0)
    antibot = any(
        s.get("catchup", {}).get("antibot_stopped")
        for s in report.get("steps", [])
        if "catchup" in s
    )
    return 1 if (pending and antibot) else 0


if __name__ == "__main__":
    sys.exit(main())
