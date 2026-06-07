"""PyInstaller entrypoint for bundled on1y CLI."""

from on1y.cli.main import app

if __name__ == "__main__":
    raise SystemExit(app())
