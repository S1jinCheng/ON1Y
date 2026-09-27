#!/usr/bin/env bash
# Build on the target Mac architecture. Python, Node and Rust are build-time only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -x "$ROOT/.build-tools/cargo/bin/cargo" ]]; then
  export RUSTUP_HOME="$ROOT/.build-tools/rustup"
  export CARGO_HOME="$ROOT/.build-tools/cargo"
  export PATH="$CARGO_HOME/bin:$PATH"
fi
export npm_config_cache="${npm_config_cache:-$ROOT/build/npm-cache}"
if [[ "$(uname -s)" != Darwin ]]; then
  echo "Build macOS bundles on a Mac." >&2
  exit 1
fi
PYTHON="${ON1Y_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo 'Create .venv with Python 3.11 and run: .venv/bin/python -m pip install -e ".[dev]"' >&2
  exit 1
fi
command -v cargo >/dev/null
command -v npm >/dev/null
export NEXT_TELEMETRY_DISABLED=1
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/build/playwright-browsers"
export PYINSTALLER_CONFIG_DIR="$ROOT/build/pyinstaller-cache"
# Native dependency wheels used by this build require macOS 14 or newer.
export MACOSX_DEPLOYMENT_TARGET=14.0

npm ci --prefix frontend
npm ci --prefix desktop
npm --prefix frontend run build
# Preserve Chromium's signed .app and framework structure outside PyInstaller.
"$PYTHON" -m playwright install chromium
"$PYTHON" -m PyInstaller packaging/on1y.spec --noconfirm \
  --distpath dist/portable/backend-build --workpath build/pyinstaller
"$PYTHON" scripts/stage-desktop.py
npm --prefix desktop run tauri -- icon src-tauri/icons/icon.png --output ../build/macos-icons
cp build/macos-icons/icon.icns desktop/src-tauri/icons/icon.icns
npm --prefix desktop run tauri -- build "$@"
echo "Bundles: $ROOT/desktop/src-tauri/target/release/bundle/"
