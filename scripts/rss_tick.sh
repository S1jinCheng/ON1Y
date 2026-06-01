#!/usr/bin/env bash
# One cron-friendly tick: poll RSS feeds then process up to N queue items.
# Usage: ./scripts/rss_tick.sh [limit]
set -euo pipefail
cd "$(dirname "$0")/.."
LIMIT="${1:-5}"
source venv/bin/activate
on1y rss run --limit "$LIMIT"
