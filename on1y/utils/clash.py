"""Clash external-controller helpers (rotate proxy on 429)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from on1y.config import Settings, get_settings

logger = logging.getLogger(__name__)

_SKIP_PROXY_NAMES = frozenset(
    {
        "DIRECT",
        "REJECT",
        "GLOBAL",
        "Proxy",
        "节点选择",
        "自动选择",
        "故障转移",
        "负载均衡",
        "♻️ 自动选择",
        "🚀 节点选择",
    }
)

_PREFERRED_GROUPS = (
    "GLOBAL",
    "Proxy",
    "节点选择",
    "🚀 节点选择",
    "♻️ 自动选择",
    "自动选择",
)


def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    secret = str(settings.clash_api_secret or "").strip()
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


def _in_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def _windows_localhost_base(settings: Settings) -> str:
    configured = str(settings.clash_api_base or "").strip().rstrip("/")
    if configured:
        parsed = urlparse(configured)
        port = parsed.port or 9090
    else:
        port = 9090
    return f"http://127.0.0.1:{port}"


def _client(settings: Settings, *, base_url: str | None = None) -> httpx.Client | None:
    base = (base_url or str(settings.clash_api_base or "")).strip().rstrip("/")
    if not base:
        return None
    return httpx.Client(
        base_url=base,
        headers=_headers(settings),
        timeout=settings.clash_api_timeout_seconds,
    )


def _powershell_curl(
    settings: Settings,
    *,
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, str]:
    secret = str(settings.clash_api_secret or "").strip()
    auth = f"-H \"Authorization: Bearer {secret}\"" if secret else ""
    if method.upper() == "GET":
        command = f"curl.exe -s -w \"\\n%{{http_code}}\" {auth} \"{url}\""
    else:
        payload = json.dumps(body or {}, ensure_ascii=False)
        payload = payload.replace("'", "''")
        command = (
            f"curl.exe -s -w \"\\n%{{http_code}}\" -X {method.upper()} {auth} "
            f"-H \"Content-Type: application/json\" -d '{payload}' \"{url}\""
        )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=max(settings.clash_api_timeout_seconds + 5, 10),
        check=False,
    )
    output = (proc.stdout or "").strip()
    if not output:
        raise RuntimeError(proc.stderr.strip() or "empty response from Clash WSL bridge")
    lines = output.splitlines()
    status_raw = lines[-1].strip()
    if not re.fullmatch(r"\d{3}", status_raw):
        raise RuntimeError(output[:500])
    body_text = "\n".join(lines[:-1]).strip()
    return int(status_raw), body_text


def _request(
    settings: Settings,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | None]:
    client = _client(settings)
    if client is not None:
        try:
            response = client.request(method.upper(), path, json=json_body)
            data = response.json() if response.content else None
            return response.status_code, data if isinstance(data, dict) else None
        except Exception as exc:
            logger.debug("Clash direct API failed (%s %s): %s", method, path, exc)
        finally:
            client.close()

    if _in_wsl() and shutil.which("powershell.exe"):
        base = _windows_localhost_base(settings)
        url = f"{base}{path}"
        try:
            status, body_text = _powershell_curl(settings, method=method, url=url, body=json_body)
            data: dict[str, Any] | None = None
            if body_text:
                try:
                    parsed = json.loads(body_text)
                    data = parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    if method.upper() not in {"PUT", "DELETE", "PATCH"}:
                        raise
            if status >= 400:
                raise RuntimeError(f"HTTP {status}: {body_text[:300]}")
            return status, data
        except Exception as exc:
            logger.warning("Clash WSL bridge failed (%s %s): %s", method, path, exc)

    return 0, None


def list_selector_groups(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    settings = settings or get_settings()
    status, data = _request(settings, "GET", "/proxies")
    if status != 200 or not data:
        return {}
    proxies = data.get("proxies") or {}
    return {
        name: group
        for name, group in proxies.items()
        if isinstance(group, dict) and group.get("type") == "Selector"
    }


def _pick_group(groups: dict[str, dict[str, Any]], preferred: str | None) -> str | None:
    if preferred and preferred in groups:
        return preferred
    for name in _PREFERRED_GROUPS:
        if name in groups:
            return name
    for name, data in groups.items():
        if data.get("all"):
            return name
    return None


def _next_proxy(all_nodes: list[str], current: str) -> str | None:
    candidates = [n for n in all_nodes if n not in _SKIP_PROXY_NAMES and not n.startswith("♻️")]
    if not candidates:
        candidates = [n for n in all_nodes if n not in {"DIRECT", "REJECT"}]
    if not candidates:
        return None
    if current not in candidates:
        return candidates[0]
    idx = candidates.index(current)
    return candidates[(idx + 1) % len(candidates)]


def rotate_clash_proxy(settings: Settings | None = None) -> str | None:
    """
    Switch the configured Clash selector to the next node.
    Returns 'group:old -> new' on success, None if unavailable.
    """
    settings = settings or get_settings()
    try:
        groups = list_selector_groups(settings)
        group = _pick_group(groups, settings.clash_proxy_group)
        if not group:
            logger.warning("Clash rotate skipped: no selector group found")
            return None

        data = groups[group]
        current = str(data.get("now") or "")
        nxt = _next_proxy(list(data.get("all") or []), current)
        if not nxt or nxt == current:
            logger.warning("Clash rotate skipped: no alternate node in group %s", group)
            return None

        status, _ = _request(
            settings,
            "PUT",
            f"/proxies/{quote(group, safe='')}",
            json_body={"name": nxt},
        )
        if status >= 400:
            logger.warning("Clash rotate failed: HTTP %s", status)
            return None
        label = f"{group}: {current} -> {nxt}"
        logger.info("Clash rotated proxy %s", label)
        return label
    except Exception as exc:
        logger.warning("Clash rotate failed: %s", exc)
        return None


def clash_api_reachable(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    status, _ = _request(settings, "GET", "/version")
    return status == 200
