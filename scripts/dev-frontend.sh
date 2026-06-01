#!/usr/bin/env bash
# Run Next.js frontend with a Linux Node/npm (avoid Windows /mnt/d/npm in WSL).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"

pick_node() {
  if command -v node >/dev/null 2>&1 && [[ "$(command -v node)" != /mnt/* ]]; then
    command -v node
    return 0
  fi
  if [[ -x "$HOME/.cursor-server/bin/"*/node ]]; then
    find "$HOME/.cursor-server/bin" -maxdepth 2 -type f -name node -executable 2>/dev/null | head -1
    return 0
  fi
  return 1
}

NODE_BIN="$(pick_node || true)"
if [[ -z "${NODE_BIN:-}" ]]; then
  echo "No Linux node found. Install in WSL:"
  echo "  sudo apt update && sudo apt install -y nodejs npm"
  exit 1
fi

NODE_DIR="$(dirname "$NODE_BIN")"
export PATH="$NODE_DIR:$PATH"

# Prefer Linux npm; fall back to npx bundled via node if npm is still on /mnt/*
if ! command -v npm >/dev/null 2>&1 || [[ "$(command -v npm)" == /mnt/* ]]; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "Windows npm detected (/mnt/d/npm). Install Linux npm:"
    echo "  sudo apt update && sudo apt install -y npm"
    exit 1
  fi
fi

cd "$FRONTEND"
if [[ ! -d node_modules ]]; then
  npm install
fi

export NEXT_PUBLIC_ON1Y_API_BASE="${NEXT_PUBLIC_ON1Y_API_BASE:-http://127.0.0.1:8765}"
exec npm run dev
