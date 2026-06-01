"""Background LLM distill batch job."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "platform": None,
    "distilled": 0,
    "failed": 0,
    "remaining": None,
    "error": None,
}


def distill_batch_status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def start_distill_batch_job(
    *,
    platform: str | None = "bilibili",
    batch_size: int = 10,
    max_items: int = 500,
) -> dict[str, Any]:
    with _lock:
        if _state["running"]:
            return {
                "started": False,
                "running": True,
                "message": "摘要生成任务进行中",
            }
        _state.update(
            {
                "running": True,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "platform": platform,
                "distilled": 0,
                "failed": 0,
                "remaining": None,
                "error": None,
            }
        )

    def _run() -> None:
        from on1y.adapters.sqlite_storage import get_storage
        from on1y.distill.processor import run_distill_batch
        from on1y.distill.prompts import PROMPT_VERSION

        error: str | None = None
        storage = get_storage()
        total_distilled = 0
        total_failed = 0
        try:
            while total_distilled + total_failed < max_items:
                remaining = storage.count_raw_ids_needing_distill(
                    prompt_version=PROMPT_VERSION,
                    platform=platform,
                )
                with _lock:
                    _state["remaining"] = remaining
                if remaining <= 0:
                    break
                limit = min(batch_size, max_items - total_distilled - total_failed, remaining)
                result = run_distill_batch(storage, limit, platform=platform)
                total_distilled += int(result.get("distilled", 0))
                total_failed += int(result.get("failed", 0))
                with _lock:
                    _state["distilled"] = total_distilled
                    _state["failed"] = total_failed
                if result.get("distilled", 0) == 0 and result.get("failed", 0) == 0:
                    break
            logger.info(
                "Background distill batch finished platform=%s distilled=%s failed=%s",
                platform,
                total_distilled,
                total_failed,
            )
        except Exception as exc:
            error = str(exc)
            logger.exception("Background distill batch failed")
        finally:
            storage.close()
            with _lock:
                _state["running"] = False
                _state["finished_at"] = datetime.now(timezone.utc).isoformat()
                _state["error"] = error

    threading.Thread(target=_run, daemon=True, name="on1y-distill-batch").start()
    return {
        "started": True,
        "running": True,
        "message": "已在后台开始生成摘要",
    }
