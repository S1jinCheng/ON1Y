#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -x "$ROOT/.build-tools/cargo/bin/cargo" ]]; then
  export RUSTUP_HOME="$ROOT/.build-tools/rustup"
  export CARGO_HOME="$ROOT/.build-tools/cargo"
  export PATH="$CARGO_HOME/bin:$PATH"
fi
export ON1Y_ROOT="$ROOT"
export PATH="$ROOT/.venv/bin:$PATH"
export NEXT_TELEMETRY_DISABLED=1
if [[ ! -f frontend/out/index.html ]]; then
  npm --prefix frontend run build
fi
# Development does not require a staged PyInstaller release.
npm --prefix desktop run tauri -- dev --config '{"bundle":{"resources":[]}}'
