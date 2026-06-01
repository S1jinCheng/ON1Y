#!/usr/bin/env python3
"""Initialize On1y database (wrapper around `on1y init`)."""

from on1y.cli.main import app

if __name__ == "__main__":
    raise SystemExit(app(["init"]))
