"""Resolve logged-in YouTube account name / avatar from saved cookies."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from on1y.config import Settings, get_settings
from on1y.cookies.loader import extract_cookie_list, load_cookie_file, resolve_cookie_path
from on1y.utils.youtube_author import fetch_youtube_channel_avatar

logger = logging.getLogger(__name__)

_YT_INITIAL_MARKER = "ytInitialData"
_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _cookie_jar(cookie_path: Path) -> dict[str, str]:
    data = load_cookie_file(cookie_path)
    cookies = extract_cookie_list(data)
    jar: dict[str, str] = {}
    for row in cookies:
        domain = str(row.get("domain") or "")
        if "youtube.com" not in domain and "google.com" not in domain:
            continue
        name = str(row.get("name") or "").strip()
        if name:
            jar[name] = str(row.get("value") or "")
    return jar


def _parse_yt_initial_data(html: str) -> dict[str, Any] | None:
    marker = html.find(_YT_INITIAL_MARKER)
    if marker < 0:
        return None
    brace = html.find("{", marker)
    if brace < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(brace, len(html)):
        ch = html[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[brace : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if "accessibilityData" in value:
            text = _text_value(value.get("accessibilityData"))
            if text:
                return text
        for key in ("simpleText", "text", "content"):
            text = _text_value(value.get(key))
            if text:
                return text
        runs = value.get("runs")
        if isinstance(runs, list):
            parts = [_text_value(item.get("text")) for item in runs if isinstance(item, dict)]
            joined = "".join(part for part in parts if part)
            if joined:
                return joined
    return ""


def _thumbnail_url(value: Any) -> str:
    if isinstance(value, dict):
        thumbs = value.get("thumbnails")
        if isinstance(thumbs, list) and thumbs:
            for item in reversed(thumbs):
                if isinstance(item, dict):
                    url = str(item.get("url") or "").strip()
                    if url:
                        return url
        for key in ("avatar", "image", "avatarThumbnail", "accountAvatar"):
            url = _thumbnail_url(value.get(key))
            if url:
                return url
    return ""


def _profile_from_node(node: dict[str, Any]) -> dict[str, str] | None:
    channel_id = ""
    for key in ("browseId", "externalId", "channelId"):
        candidate = str(node.get(key) or "").strip()
        if _CHANNEL_ID_RE.match(candidate):
            channel_id = candidate
            break
    browse = node.get("browseEndpoint")
    if isinstance(browse, dict) and not channel_id:
        candidate = str(browse.get("browseId") or "").strip()
        if _CHANNEL_ID_RE.match(candidate):
            channel_id = candidate
    navigation = node.get("navigationEndpoint")
    if isinstance(navigation, dict) and not channel_id:
        browse = navigation.get("browseEndpoint")
        if isinstance(browse, dict):
            candidate = str(browse.get("browseId") or "").strip()
            if _CHANNEL_ID_RE.match(candidate):
                channel_id = candidate

    avatar_url = ""
    for key in (
        "avatar",
        "avatarThumbnail",
        "accountAvatar",
        "image",
        "thumbnail",
        "accountPhoto",
    ):
        avatar_url = _thumbnail_url(node.get(key))
        if avatar_url:
            break

    account_name = ""
    for key in ("accountName", "accountNameText", "title", "channelName", "name"):
        account_name = _text_value(node.get(key))
        if account_name:
            break
    if not account_name:
        account_name = _text_value(node.get("accessibility", {}).get("accessibilityData", {}).get("label"))
    if account_name.lower().startswith("avatar image"):
        account_name = account_name.split("avatar image", 1)[-1].strip(" :·-")
    account_name = _clean_account_name(account_name)

    if not channel_id and not avatar_url:
        return None
    if not channel_id and avatar_url and not account_name:
        return None
    return {
        "account_id": channel_id,
        "account_name": account_name,
        "avatar_url": avatar_url,
    }


def _clean_account_name(name: str) -> str:
    text = str(name or "").strip()
    lowered = text.lower()
    for prefix in ("go to channel ", "前往频道 ", "访问频道 "):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _candidates_from_topbar(initial: dict[str, Any]) -> list[dict[str, str]]:
    topbar = initial.get("topbar")
    if not isinstance(topbar, dict):
        return []
    desktop = topbar.get("desktopTopbarRenderer")
    if not isinstance(desktop, dict):
        return []
    buttons = desktop.get("topbarButtons")
    if not isinstance(buttons, list):
        return []
    out: list[dict[str, str]] = []
    for button in buttons:
        _walk_profile_candidates(button, out)
    return out


def _walk_profile_candidates(node: Any, out: list[dict[str, str]], *, depth: int = 0) -> None:
    if depth > 24:
        return
    if isinstance(node, dict):
        for key in (
            "activeAccountHeader",
            "accountItemRenderer",
            "buttonRenderer",
            "channelMetadataRenderer",
        ):
            child = node.get(key)
            if isinstance(child, dict):
                profile = _profile_from_node(child)
                if profile:
                    out.append(profile)
        if "browseEndpoint" in node or "avatarThumbnail" in node or "accountAvatar" in node:
            profile = _profile_from_node(node)
            if profile:
                out.append(profile)
        for value in node.values():
            _walk_profile_candidates(value, out, depth=depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk_profile_candidates(item, out, depth=depth + 1)


def _decode_json_string(raw: str) -> str:
    """Decode a JSON string fragment from YouTube embedded HTML (UTF-8 or \\u escapes)."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if "\\" in text:
        try:
            return json.loads(f'"{text}"')
        except json.JSONDecodeError:
            pass
    return text


def _find_channel_metadata(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        renderer = node.get("channelMetadataRenderer")
        if isinstance(renderer, dict):
            return renderer
        for value in node.values():
            found = _find_channel_metadata(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_channel_metadata(item)
            if found is not None:
                return found
    return None


def _pick_best_profile(candidates: list[dict[str, str]]) -> dict[str, str] | None:
    if not candidates:
        return None

    def score(row: dict[str, str]) -> int:
        value = 0
        if row.get("account_id"):
            value += 4
        if row.get("avatar_url"):
            value += 3
        if row.get("account_name"):
            value += 2
        name = str(row.get("account_name") or "").lower()
        if name in {"your channel", "你的频道", "youtube"}:
            value -= 2
        if "go to channel" in name or "前往频道" in name:
            value -= 10
        return value

    ranked = sorted(candidates, key=score, reverse=True)
    merged: dict[str, str] = {"account_id": "", "account_name": "", "avatar_url": ""}
    for row in ranked:
        for key in merged:
            if not merged[key] and row.get(key):
                merged[key] = row[key]
        if merged["account_id"] and merged["account_name"] and merged["avatar_url"]:
            break
    if not any(merged.values()):
        return None
    return merged


def _channel_title_from_html(html: str) -> str:
    initial = _parse_yt_initial_data(html)
    if initial:
        meta = _find_channel_metadata(initial)
        if meta:
            title = _text_value(meta.get("title"))
            if title:
                return title
    match = re.search(
        r'"channelMetadataRenderer"\s*:\s*\{[^{}]*"title"\s*:\s*"((?:[^"\\]|\\.)*)"',
        html,
    )
    if match:
        return _decode_json_string(match.group(1))
    return ""


def _profile_from_initial_data(initial: dict[str, Any]) -> dict[str, str] | None:
    candidates = _candidates_from_topbar(initial)
    profile = _pick_best_profile(candidates)
    if profile and profile.get("account_id"):
        return profile
    if not candidates:
        _walk_profile_candidates(initial, candidates)
    return _pick_best_profile(candidates)


def _fetch_profile_once(
    *,
    jar: dict[str, str],
    settings: Settings,
    proxy: str | None,
) -> dict[str, Any]:
    client_kwargs: dict[str, Any] = {
        "headers": _DEFAULT_HEADERS,
        "cookies": jar,
        "timeout": settings.http_timeout_seconds,
        "follow_redirects": True,
    }
    if proxy:
        client_kwargs["proxy"] = proxy
    with httpx.Client(**client_kwargs) as client:
        response = client.get("https://www.youtube.com/")
        response.raise_for_status()
        initial = _parse_yt_initial_data(response.text)
        profile = _profile_from_initial_data(initial) if initial else None

        account_id = str((profile or {}).get("account_id") or "").strip() or None
        account_name = _clean_account_name(str((profile or {}).get("account_name") or "").strip()) or None
        avatar_url = str((profile or {}).get("avatar_url") or "").strip() or None

        if account_id:
            channel_resp = client.get(f"https://www.youtube.com/channel/{account_id}")
            if channel_resp.status_code == 200:
                title = _channel_title_from_html(channel_resp.text)
                if title:
                    account_name = title
                from on1y.utils.youtube_author import _avatar_from_channel_html

                channel_avatar = _avatar_from_channel_html(channel_resp.text)
                if channel_avatar:
                    avatar_url = channel_avatar

        if account_id and not avatar_url:
            avatar_url = fetch_youtube_channel_avatar(account_id, settings=settings) or None

        return {
            "account_id": account_id,
            "account_name": account_name,
            "avatar_url": avatar_url,
        }


def fetch_youtube_account_profile(
    *,
    cookie_path: Path | None = None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return account_id, account_name, avatar_url for the logged-in YouTube session."""
    settings = settings or get_settings()
    path = cookie_path or resolve_cookie_path("youtube", settings)
    jar = _cookie_jar(path)
    if not jar:
        return {"account_id": None, "account_name": None, "avatar_url": None}

    from on1y.network.proxy import effective_ytdlp_proxy

    proxy = effective_ytdlp_proxy(settings=settings)
    try:
        profile = _fetch_profile_once(jar=jar, settings=settings, proxy=proxy)
        if any(profile.values()) or not proxy:
            return profile
        logger.info("YouTube profile empty via proxy %s; retrying without proxy", proxy)
        return _fetch_profile_once(jar=jar, settings=settings, proxy=None)
    except Exception as exc:
        if proxy:
            try:
                logger.info("YouTube profile failed via proxy %s (%s); retrying without proxy", proxy, exc)
                return _fetch_profile_once(jar=jar, settings=settings, proxy=None)
            except Exception:
                pass
        logger.debug("YouTube account profile lookup failed: %s", exc)
        return {"account_id": None, "account_name": None, "avatar_url": None}
