#!/usr/bin/env bash
# Daily Bilibili UP subscription sync + ingest + subtitles + LLM summary.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"

if ! "$PY" -c "from on1y.config import get_settings; import sys; sys.exit(0 if get_settings().bilibili_up_sync_enabled else 1)"; then
  echo "Bilibili UP sync disabled (ON1Y_BILIBILI_UP_SYNC_ENABLED=false); skipping."
  exit 0
fi

INGEST="${ON1Y_BILIBILI_SYNC_INGEST_LIMIT:-10}"
SUBS="${ON1Y_BILIBILI_SYNC_SUBTITLE_LIMIT:-10}"
DISTILL="${ON1Y_BILIBILI_SYNC_DISTILL_LIMIT:-10}"

"$PY" scripts/sync_bilibili_feeds.py
"$PY" -c "
from on1y.adapters.sqlite_storage import get_storage
from on1y.pipeline.video_enrich import run_video_enrich_pipeline
s = get_storage()
try:
    print(run_video_enrich_pipeline(
        s,
        platform='bilibili',
        ingest_limit=${INGEST},
        subtitle_limit=${SUBS},
        distill_limit=${DISTILL},
    ))
finally:
    s.close()
"
