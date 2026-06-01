"""Pipeline alerts for rate limits (429) and anti-bot / 风控 blocks."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from on1y.config import Settings, get_settings

logger = logging.getLogger(__name__)

_RATE_LIMIT_RE = re.compile(
    r"429|too many requests|rate.?limit|HTTP Error 429|Too Many Requests|"
    r"status code: 429|status=429",
    re.IGNORECASE,
)

_ANTIBOT_RE = re.compile(
    r"安全验证|网络环境存在异常|开始验证|/account/unhuman|blocked automated browser|"
    r"security verification|验证码|captcha",
    re.IGNORECASE,
)

_KIND_LABELS = {
    "rate_limit": "限流 (429)",
    "antibot": "风控 / 安全验证",
}


class AlertKind(str, Enum):
    RATE_LIMIT = "rate_limit"
    ANTIBOT = "antibot"


def classify_pipeline_error(message: str) -> AlertKind | None:
    if _ANTIBOT_RE.search(message):
        return AlertKind.ANTIBOT
    if _RATE_LIMIT_RE.search(message):
        return AlertKind.RATE_LIMIT
    return None


def is_rate_limit_error(message: str) -> bool:
    return classify_pipeline_error(message) == AlertKind.RATE_LIMIT


def is_antibot_error(message: str) -> bool:
    return classify_pipeline_error(message) == AlertKind.ANTIBOT


def _alerts_log_path(settings: Settings) -> Path:
    return settings.data_dir / "alerts.jsonl"


def _active_alerts_path(settings: Settings) -> Path:
    return settings.data_dir / "alerts-active.json"


def _cooldown_state_path(settings: Settings) -> Path:
    return settings.data_dir / "alerts-cooldown.json"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cooldown_key(kind: AlertKind, platform: str, worker: str) -> str:
    return f"{kind.value}:{platform}:{worker}"


def _in_cooldown(kind: AlertKind, platform: str, worker: str, settings: Settings) -> bool:
    path = _cooldown_state_path(settings)
    state = _load_json(path, {})
    key = _cooldown_key(kind, platform, worker)
    last = state.get(key)
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        elapsed = (datetime.now(UTC) - last_dt).total_seconds()
        return elapsed < settings.alert_cooldown_seconds
    except ValueError:
        return False


def _mark_cooldown(kind: AlertKind, platform: str, worker: str, settings: Settings) -> None:
    path = _cooldown_state_path(settings)
    state = _load_json(path, {})
    state[_cooldown_key(kind, platform, worker)] = _now_iso()
    _save_json(path, state)


def emit_alert(
    kind: AlertKind,
    platform: str,
    message: str,
    *,
    worker: str = "pipeline",
    url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """
    Record and notify about a rate-limit or anti-bot event.
    Returns the alert dict when emitted, None if suppressed by cooldown/disabled.
    """
    settings = settings or get_settings()
    if not settings.alert_enabled:
        return None
    if _in_cooldown(kind, platform, worker, settings):
        logger.debug("Alert suppressed (cooldown): %s %s %s", kind.value, platform, worker)
        return None

    alert: dict[str, Any] = {
        "id": uuid4().hex[:12],
        "kind": kind.value,
        "kind_label": _KIND_LABELS.get(kind.value, kind.value),
        "platform": platform,
        "worker": worker,
        "message": message[:2000],
        "url": url,
        "created_at": _now_iso(),
        "acknowledged": False,
    }

    settings.ensure_data_dir()
    log_path = _alerts_log_path(settings)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(alert, ensure_ascii=False) + "\n")

    active = _load_json(_active_alerts_path(settings), [])
    if not isinstance(active, list):
        active = []
    active = [a for a in active if isinstance(a, dict)]
    active.append(alert)
    active = active[-20:]
    _save_json(_active_alerts_path(settings), active)

    _mark_cooldown(kind, platform, worker, settings)
    _deliver_notification(alert, settings)
    logger.warning(
        "ALERT [%s] %s/%s: %s",
        alert["kind_label"],
        platform,
        worker,
        message[:300],
    )
    return alert


def maybe_alert_from_error(
    message: str,
    *,
    platform: str,
    worker: str,
    url: str | None = None,
) -> dict[str, Any] | None:
    kind = classify_pipeline_error(message)
    if kind is None:
        return None
    return emit_alert(kind, platform, message, worker=worker, url=url)


def list_alerts(*, limit: int = 30, active_only: bool = False) -> list[dict[str, Any]]:
    settings = get_settings()
    if active_only:
        active = _load_json(_active_alerts_path(settings), [])
        if not isinstance(active, list):
            return []
        return [a for a in active if isinstance(a, dict) and not a.get("acknowledged")][-limit:]

    path = _alerts_log_path(settings)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for line in reversed(lines[-limit:]):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def acknowledge_alerts(*, alert_id: str | None = None, clear_all: bool = False) -> int:
    settings = get_settings()
    path = _active_alerts_path(settings)
    active = _load_json(path, [])
    if not isinstance(active, list):
        return 0
    if clear_all:
        _save_json(path, [])
        return len(active)
    if alert_id:
        kept = [a for a in active if isinstance(a, dict) and a.get("id") != alert_id]
        removed = len(active) - len(kept)
        for a in active:
            if isinstance(a, dict) and a.get("id") == alert_id:
                a["acknowledged"] = True
        _save_json(path, [a for a in active if isinstance(a, dict) and not a.get("acknowledged")])
        return removed
    return 0


def _deliver_notification(alert: dict[str, Any], settings: Settings) -> None:
    title = f"On1y · {alert['kind_label']}"
    body = f"{alert['platform']} / {alert['worker']}\n{alert['message'][:400]}"
    banner = f"\n{'=' * 60}\n⚠️  On1y 告警: {title}\n{body}\n{'=' * 60}\n"
    print(banner, file=sys.stderr, flush=True)
    if settings.alert_terminal_bell:
        print("\a", file=sys.stderr, end="", flush=True)

    if settings.alert_notify_send and shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "-u", "critical", title, body.replace("\n", " ")],
                check=False,
                timeout=5,
            )
        except Exception as exc:
            logger.debug("notify-send failed: %s", exc)

    if settings.alert_webhook_url:
        _post_webhook(alert, settings.alert_webhook_url)


def _post_webhook(alert: dict[str, Any], webhook_url: str) -> None:
    import httpx

    payload = {
        "text": (
            f"⚠️ On1y {alert['kind_label']}\n"
            f"平台: {alert['platform']} · {alert['worker']}\n"
            f"{alert.get('url') or ''}\n"
            f"{alert['message'][:500]}"
        ),
        "alert": alert,
    }
    try:
        httpx.post(webhook_url, json=payload, timeout=10.0)
    except Exception as exc:
        logger.warning("Alert webhook failed: %s", exc)
