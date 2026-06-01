#!/usr/bin/env bash
# Install Google Chrome on Debian/Ubuntu/WSL for On1y cookie export & Playwright.
set -euo pipefail

if command -v google-chrome-stable >/dev/null 2>&1; then
  echo "google-chrome-stable already installed: $(google-chrome-stable --version)"
  exit 0
fi

echo "Installing Google Chrome (official .deb)..."
sudo apt-get update -qq
sudo apt-get install -y wget ca-certificates

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
deb="$tmp/google-chrome-stable.deb"
url="https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"

echo "Downloading Chrome (~120MB, may take 1–5 min; not stuck)..."
if ! wget --show-progress -O "$deb" "$url"; then
  echo "Download failed. Check proxy (ON1Y_YTDLP_PROXY) or network." >&2
  exit 1
fi

echo "Installing package..."
if ! sudo apt-get install -y "$deb"; then
  echo "Fixing dependencies..."
  sudo apt-get install -f -y
fi

echo "Done: $(google-chrome-stable --version)"
echo "Next: python scripts/export_cookies.py youtube"
