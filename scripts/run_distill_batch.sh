#!/usr/bin/env bash
# Batch distill until every eligible item has v2-fast tags + summary.
set -euo pipefail
cd "$(dirname "$0")/.."
BATCH="${1:-20}"
MAX_ROUNDS="${2:-100}"
PY="./venv/bin/on1y"

for ((i=1; i<=MAX_ROUNDS; i++)); do
  echo "=== distill round $i $(date -Iseconds) ==="
  out=$("$PY" distill --limit "$BATCH" 2>&1) || true
  echo "$out"
  if echo "$out" | grep -q '"message": "no items to distill"'; then
    echo "Done at round $i — all items classified"
    break
  fi
  if echo "$out" | grep -q '"distilled": 0'; then
    if ! echo "$out" | grep -q '"failed": [1-9]'; then
      echo "Done at round $i — nothing left"
      break
    fi
  fi
done
