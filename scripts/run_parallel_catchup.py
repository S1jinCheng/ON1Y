#!/usr/bin/env python3
"""Run platform-isolated catchup workers in parallel."""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from on1y.adapters.sqlite_storage import get_storage
from on1y.pipeline.subtitle_catchup import run_subtitle_catchup
from on1y.pipeline.video_catchup import run_video_catchup
from on1y.pipeline.zhihu_catchup import run_zhihu_catchup
from on1y.utils.platform import PLATFORM_BILIBILI, PLATFORM_YOUTUBE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("parallel_catchup")


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel platform catchup")
    parser.add_argument("--zhihu-per-round", type=int, default=1)
    parser.add_argument("--video-ingest", type=int, default=5)
    parser.add_argument("--video-subtitles", type=int, default=3)
    parser.add_argument("--youtube-subtitles", type=int, default=0, help="Per-round YouTube subtitle batch (0=skip)")
    parser.add_argument("--bilibili-subtitles", type=int, default=0, help="Per-round Bilibili subtitle batch (0=use video-subtitles split)")
    parser.add_argument("--max-rounds", type=int, default=500)
    parser.add_argument("--zhihu-only", action="store_true")
    parser.add_argument("--video-only", action="store_true")
    parser.add_argument("--subtitles-only", action="store_true", help="Skip ingest; run subtitle catchups only")
    parser.add_argument("--skip-youtube-subtitles", action="store_true")
    args = parser.parse_args()

    bilibili_sub_batch = args.bilibili_subtitles or max(1, args.video_subtitles // 2)
    youtube_sub_batch = args.youtube_subtitles or max(1, args.video_subtitles // 2)

    def zhihu_job() -> dict:
        storage = get_storage()
        try:
            return run_zhihu_catchup(
                storage,
                ingest_per_round=args.zhihu_per_round,
                max_rounds=args.max_rounds,
            )
        finally:
            storage.close()

    def video_job() -> dict:
        storage = get_storage()
        try:
            return run_video_catchup(
                storage,
                ingest_per_round=0 if args.subtitles_only else args.video_ingest,
                subtitle_per_round=0 if args.subtitles_only else args.video_subtitles,
                max_rounds=args.max_rounds,
                parallel_subtitles=not args.subtitles_only,
            )
        finally:
            storage.close()

    def bilibili_subtitle_job() -> dict:
        storage = get_storage()
        try:
            return run_subtitle_catchup(
                storage,
                PLATFORM_BILIBILI,
                batch_size=bilibili_sub_batch,
                max_rounds=args.max_rounds,
            )
        finally:
            storage.close()

    def youtube_subtitle_job() -> dict:
        storage = get_storage()
        try:
            return run_subtitle_catchup(
                storage,
                PLATFORM_YOUTUBE,
                batch_size=youtube_sub_batch,
                max_rounds=args.max_rounds,
            )
        finally:
            storage.close()

    jobs: list[tuple[str, object]] = []

    if args.subtitles_only:
        if bilibili_sub_batch > 0:
            jobs.append(("bilibili-subtitles", bilibili_subtitle_job))
        if not args.skip_youtube_subtitles and youtube_sub_batch > 0:
            jobs.append(("youtube-subtitles", youtube_subtitle_job))
    else:
        if not args.video_only:
            jobs.append(("zhihu", zhihu_job))
        if not args.zhihu_only:
            if args.bilibili_subtitles > 0 or args.youtube_subtitles > 0:
                jobs.append(("bilibili-subtitles", bilibili_subtitle_job))
                if not args.skip_youtube_subtitles and youtube_sub_batch > 0:
                    jobs.append(("youtube-subtitles", youtube_subtitle_job))
                if args.video_ingest > 0:
                    jobs.append(("video-ingest", video_job))
            else:
                jobs.append(("video", video_job))

    if not jobs:
        log.error("Nothing to run")
        return 1

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                log.info("%s finished: %s", name, result)
            except Exception:
                log.exception("%s failed", name)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
