"""PyInstaller entrypoint for bundled on1y CLI."""

import multiprocessing
import sys


def self_test() -> int:
    """Build-time check of native libraries inside the frozen distribution."""
    import json
    import sqlite3

    import paddle
    import pymupdf
    from paddleocr import LayoutDetection

    assert LayoutDetection is not None
    matrix = paddle.ones([2, 2])
    assert paddle.matmul(matrix, matrix).numpy().tolist() == [[2.0, 2.0], [2.0, 2.0]]
    with pymupdf.open() as document:
        document.new_page()
        assert len(document.tobytes()) > 0
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE VIRTUAL TABLE smoke USING fts5(text)")
    print(json.dumps({"native_dependencies": "ok", "paddle": paddle.__version__}))
    return 0

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--self-test"]:
        raise SystemExit(self_test())
    from on1y.cli.main import app

    raise SystemExit(app())
