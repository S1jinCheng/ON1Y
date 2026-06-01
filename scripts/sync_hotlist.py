#!/usr/bin/env python3
"""Daily hot-list sync (Zhihu first; more sources later)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from on1y.adapters.sqlite_storage import get_storage
from on1y.hotlist import sync_hotlists


def main() -> int:
    storage = get_storage()
    try:
        report = sync_hotlists(storage)
    finally:
        storage.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
