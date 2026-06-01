#!/usr/bin/env python3
"""Ingest a single URL (wrapper around `on1y ingest <url>`)."""

import sys

from on1y.cli.main import app

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else None
    if not url:
        print("Usage: ingest_one.py <url>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(app(["ingest", url]))
