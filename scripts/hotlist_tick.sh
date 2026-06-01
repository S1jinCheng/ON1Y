#!/usr/bin/env bash
# Daily hot-list sync (Zhihu hot questions → 热榜 theme).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec "${ROOT}/.venv/bin/python" scripts/sync_hotlist.py
