"""BabelDOC-backed bilingual PDF translation jobs.

BabelDOC stays in an isolated subprocess. A short-lived localhost gateway keeps
provider credentials out of process arguments and adapts both the existing
On1y OpenAI-compatible AI setting and DeepL to BabelDOC's OpenAI interface.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)
BABELDOC_VERSION = "0.6.4"
_TRANSLATION_STOP = threading.Event()
_TRANSLATION_THREAD: threading.Thread | None = None
_RECOVERED_USERS: set[int] = set()


class TranslationAdapter(Protocol):
    """A provider translates one immutable PDF into another file."""

    def translate_pdf(
        self,
        input_path: Path,
        output_path: Path,
        *,
        source: str,
        target: str,
    ) -> dict[str, Any]: ...


def next_bilingual_path(
    directory: Path,
    original_stem: str,
    suffix: str = "CN-EN",
) -> Path:
    """Return a new path without ever selecting an existing bilingual PDF."""
    clean_suffix = re.sub(r"[^A-Za-z0-9-]+", "-", suffix).strip("-") or "bilingual"
    first = directory / f"{original_stem}_{clean_suffix}.pdf"
    if not first.exists():
        return first
    version = 2
    while True:
        candidate = directory / f"{original_stem}_{clean_suffix}_v{version}.pdf"
        if not candidate.exists():
            return candidate
        version += 1


def _output_suffix(source: str, target: str) -> str:
    def short(value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.startswith("zh"):
            return "CN"
        if normalized.startswith("en"):
            return "EN"
        return re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")[:12] or "XX"

    return f"{short(target)}-{short(source)}"


def resolve_babeldoc_executable(configured: str | None = None) -> str | None:
    """Resolve a configured BabelDOC executable or the uv tool on PATH."""
    raw = str(configured or "").strip().strip('"')
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        found = shutil.which(raw)
        return found
    return shutil.which("babeldoc")


def translation_worker_status(configured: str | None = None) -> dict[str, Any]:
    executable = resolve_babeldoc_executable(configured)
    return {
        "available": bool(executable),
        "executable": executable,
        "engine": "BabelDOC",
        "version": BABELDOC_VERSION,
        "isolation": "subprocess",
        "license": "AGPL-3.0",
        "install_command": f'uv tool install --python 3.12 "BabelDOC=={BABELDOC_VERSION}"',
    }


def flatten_pdf_visual_regions(
    input_path: Path,
    output_path: Path,
    regions: dict[int, list[tuple[float, float, float, float]]],
    *,
    render_scale: float = 2.0,
) -> int:
    """Replace figure/table regions with opaque snapshots before translation.

    Removing the underlying PDF text prevents labels inside charts and figures from
    being sent to the translation provider. Captions remain live text outside the
    protected regions and are translated normally.
    """

    import pymupdf

    document = pymupdf.open(input_path)
    protected = 0
    try:
        for page_number, boxes in regions.items():
            if page_number < 0 or page_number >= document.page_count:
                continue
            page = document[page_number]
            snapshots: list[tuple[Any, bytes]] = []
            for box in boxes:
                rect = pymupdf.Rect(*box) & page.rect
                if rect.width < 2 or rect.height < 2:
                    continue
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(render_scale, render_scale),
                    clip=rect,
                    alpha=False,
                )
                snapshots.append((rect, pixmap.tobytes("png")))
                page.add_redact_annot(rect, fill=(1, 1, 1), cross_out=False)
            if not snapshots:
                continue
            page.apply_redactions(images=2, graphics=1, text=0)
            for rect, image_bytes in snapshots:
                page.insert_image(
                    rect,
                    stream=image_bytes,
                    keep_proportion=False,
                    overlay=True,
                )
                protected += 1
        if protected:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            document.save(output_path, garbage=4, deflate=True)
    finally:
        document.close()
    return protected


def prepare_translation_input(input_path: Path, work_dir: Path) -> tuple[Path, int]:
    """Create a translation-only PDF with figures/tables flattened as original images."""

    from on1y.papers.figures import detect_translation_visual_regions

    regions = detect_translation_visual_regions(input_path, work_dir / "visual-detection")
    if not regions:
        return input_path, 0
    protected_path = work_dir / "protected-input.pdf"
    count = flatten_pdf_visual_regions(input_path, protected_path, regions)
    if not count or not protected_path.is_file():
        return input_path, 0
    return protected_path, count


@dataclass
class GatewayUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    character_count: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.prompt_tokens,
            "output_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "character_count": self.character_count,
        }


class LocalTranslationGateway:
    """Expose one authenticated local OpenAI-compatible endpoint per PDF job."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.token = "on1y-" + uuid4().hex
        self.usage = GatewayUsage()
        self._usage_lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("translation gateway is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> LocalTranslationGateway:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                if self.path.rstrip("/") != "/v1/chat/completions":
                    self._json(404, {"error": {"message": "not found"}})
                    return
                if self.headers.get("Authorization") != f"Bearer {gateway.token}":
                    self._json(401, {"error": {"message": "unauthorized"}})
                    return
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                    if length <= 0 or length > 20 * 1024 * 1024:
                        raise ValueError("invalid request size")
                    payload = json.loads(self.rfile.read(length))
                    self._json(200, gateway.complete(payload))
                except Exception as exc:
                    logger.warning("Local translation gateway request failed: %s", exc)
                    self._json(502, {"error": {"message": str(exc)}})

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="on1y-translation-gateway",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.config["provider"] == "deepl":
            return self._complete_deepl(payload)
        return self._complete_openai(payload)

    def _complete_openai(self, payload: dict[str, Any]) -> dict[str, Any]:
        from on1y.llm.client import resolve_chat_completions_url

        upstream = dict(payload)
        upstream["model"] = self.config["model"]
        upstream.pop("stream", None)
        headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=float(self.config.get("timeout") or 600)) as client:
            for attempt in range(3):
                response = client.post(
                    resolve_chat_completions_url(self.config["base_url"]),
                    headers=headers,
                    json=upstream,
                )
                if response.status_code != 429 and response.status_code < 500:
                    break
                if attempt < 2:
                    time.sleep(2**attempt)
        if response.is_error:
            detail = response.text[:1000]
            raise RuntimeError(f"AI provider returned {response.status_code}: {detail}")
        data = response.json()
        usage = data.get("usage") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            total = int(usage.get("total_tokens") or prompt + completion)
            with self._usage_lock:
                self.usage.prompt_tokens += prompt
                self.usage.completion_tokens += completion
                self.usage.total_tokens += total
        return data

    def _complete_deepl(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = self._extract_translation_text(payload)
        if not text:
            translated = text
        else:
            endpoint = (
                "https://api-free.deepl.com/v2/translate"
                if self.config.get("deepl_plan") == "free"
                else "https://api.deepl.com/v2/translate"
            )
            body: dict[str, Any] = {
                "text": [text],
                "source_lang": self._deepl_language(self.config["source"], target=False),
                "target_lang": self._deepl_language(self.config["target"], target=True),
                "preserve_formatting": True,
                "show_billed_characters": True,
            }
            if "<" in text and ">" in text:
                body["tag_handling"] = "xml"
                body["ignore_tags"] = ["code"]
            headers = {
                "Authorization": f"DeepL-Auth-Key {self.config['api_key']}",
                "Content-Type": "application/json",
            }
            with httpx.Client(timeout=120) as client:
                for attempt in range(3):
                    response = client.post(endpoint, headers=headers, json=body)
                    if response.status_code != 429 and response.status_code < 500:
                        break
                    if attempt < 2:
                        time.sleep(2**attempt)
            if response.is_error:
                trace_id = response.headers.get("X-Trace-ID")
                suffix = f" (trace {trace_id})" if trace_id else ""
                raise RuntimeError(
                    f"DeepL returned {response.status_code}{suffix}: {response.text[:1000]}"
                )
            rows = response.json().get("translations") or []
            if not rows:
                raise RuntimeError("DeepL returned no translation")
            translated = str(rows[0].get("text") or "")
            billed_characters = int(rows[0].get("billed_characters") or len(text))
        with self._usage_lock:
            self.usage.character_count += billed_characters if text else 0
        return {
            "id": "chatcmpl-on1y-deepl",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "deepl",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": translated},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @staticmethod
    def _extract_translation_text(payload: dict[str, Any]) -> str:
        messages = payload.get("messages") or []
        content = ""
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = str(message.get("content") or "")
                break
        markers = (
            "Now translate the following text:\n\n",
            "Input:\n\n",
        )
        for marker in markers:
            if marker in content:
                return content.rsplit(marker, 1)[1]
        return content

    @staticmethod
    def _deepl_language(value: str, *, target: bool) -> str:
        normalized = value.strip().replace("_", "-").casefold()
        if normalized in {"zh", "zh-cn", "zh-hans"}:
            return "ZH-HANS" if target else "ZH"
        if normalized in {"zh-tw", "zh-hant"}:
            return "ZH-HANT" if target else "ZH"
        if normalized == "en":
            return "EN-US" if target else "EN"
        return normalized.upper()


class BabelDocSubprocessAdapter:
    """Run BabelDOC out-of-process and copy only its dual PDF into the Vault."""

    def __init__(
        self,
        *,
        executable: str,
        provider_config: dict[str, Any],
        qps: int = 2,
        ocr_workaround: bool = False,
        glossary_path: str | None = None,
        progress: Callable[[float, str], None] | None = None,
    ) -> None:
        self.executable = executable
        self.provider_config = provider_config
        self.qps = qps
        self.ocr_workaround = ocr_workaround
        self.glossary_path = glossary_path
        self.progress = progress or (lambda _value, _stage: None)

    def translate_pdf(
        self,
        input_path: Path,
        output_path: Path,
        *,
        source: str,
        target: str,
    ) -> dict[str, Any]:
        if output_path.exists():
            raise FileExistsError(f"immutable bilingual PDF already exists: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        log_tail: deque[str] = deque(maxlen=120)
        self.progress(1, "detecting figures and tables")
        with tempfile.TemporaryDirectory(prefix=".babeldoc-", dir=output_path.parent) as temp:
            temp_dir = Path(temp)
            translation_input, protected_visuals = prepare_translation_input(
                input_path, temp_dir
            )
            self.progress(3, "starting BabelDOC")
            with LocalTranslationGateway(self.provider_config) as gateway:
                command = self._command(
                    input_path=translation_input,
                    output_dir=temp_dir,
                    source=source,
                    target=target,
                    gateway=gateway,
                )
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                process = subprocess.Popen(  # noqa: S603
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=flags,
                )
                assert process.stdout is not None
                self.progress(5, "BabelDOC parsing")
                for line in process.stdout:
                    cleaned = line.strip()
                    if cleaned:
                        log_tail.append(cleaned)
                        stage = self._stage_from_log(cleaned)
                        if stage:
                            self.progress(stage[0], stage[1])
                return_code = process.wait()
                if return_code:
                    detail = "\n".join(log_tail)[-8000:]
                    raise RuntimeError(
                        f"BabelDOC exited with code {return_code}"
                        + (f":\n{detail}" if detail else "")
                    )
                candidates = [
                    path
                    for path in temp_dir.rglob("*.dual.pdf")
                    if not path.name.endswith(".decompressed.pdf")
                ]
                if not candidates:
                    detail = "\n".join(log_tail)[-4000:]
                    raise RuntimeError(
                        "BabelDOC completed without a dual PDF" + (f":\n{detail}" if detail else "")
                    )
                produced = max(
                    candidates, key=lambda path: (path.stat().st_mtime_ns, path.stat().st_size)
                )
                if produced.read_bytes()[:5] != b"%PDF-":
                    raise RuntimeError("BabelDOC output is not a PDF")
                temporary = output_path.with_suffix(".translating")
                if temporary.exists():
                    temporary.unlink()
                shutil.copy2(produced, temporary)
                if output_path.exists():
                    temporary.unlink(missing_ok=True)
                    raise FileExistsError(f"immutable bilingual PDF already exists: {output_path}")
                temporary.replace(output_path)
                self.progress(100, "completed")
                return {
                    **gateway.usage.as_dict(),
                    "protected_visuals": protected_visuals,
                    "log_tail": "\n".join(log_tail)[-8000:] or None,
                }

    def _command(
        self,
        *,
        input_path: Path,
        output_dir: Path,
        source: str,
        target: str,
        gateway: LocalTranslationGateway,
    ) -> list[str]:
        command = [
            self.executable,
            "--openai",
            "--openai-model",
            "on1y-translation-gateway",
            "--openai-base-url",
            gateway.base_url,
            "--openai-api-key",
            gateway.token,
            "--files",
            str(input_path),
            "--output",
            str(output_dir),
            "--lang-in",
            source,
            "--lang-out",
            target,
            "--qps",
            str(self.qps),
            "--no-mono",
            "--no-watermark",
            "--no-auto-extract-glossary",
        ]
        if self.provider_config["provider"] == "deepl":
            command.append("--disable-rich-text-translate")
        if self.ocr_workaround:
            command.append("--ocr-workaround")
        if self.glossary_path and self.provider_config["provider"] == "on1y_ai":
            command.extend(["--glossary-files", self.glossary_path])
        return command

    @staticmethod
    def _stage_from_log(line: str) -> tuple[float, str] | None:
        lowered = line.casefold()
        stages = (
            ("detectscannedfile", 10, "detecting scanned pages"),
            ("layoutparser", 20, "analyzing layout"),
            ("paragraphfinder", 35, "finding paragraphs"),
            ("automatictermextractor", 45, "extracting terms"),
            ("iltranslator", 55, "translating"),
            ("typesetting", 82, "typesetting"),
            ("pdfcreater", 92, "rendering PDF"),
        )
        for marker, value, label in stages:
            if marker in lowered:
                return value, label
        return None


def _provider_config(user_id: int, provider: str, source: str, target: str) -> dict[str, Any]:
    from on1y.llm.settings import resolve_llm_settings
    from on1y.papers.settings_store import load_paper_settings

    paper_settings = load_paper_settings(user_id)
    if provider == "deepl":
        key = str(paper_settings.translation_api_key or "").strip()
        if not key:
            raise RuntimeError("DeepL API key is not configured")
        return {
            "provider": "deepl",
            "api_key": key,
            "deepl_plan": paper_settings.translation_deepl_plan,
            "source": source,
            "target": target,
            "model": "DeepL",
        }
    llm = resolve_llm_settings(user_id=user_id)
    if not llm.api_key_set:
        raise RuntimeError("On1y AI API key is not configured")
    return {
        "provider": "on1y_ai",
        "api_key": llm.api_key,
        "base_url": llm.base_url,
        "model": paper_settings.translation_model_override or llm.model,
        "timeout": max(600, llm.timeout_seconds),
        "source": source,
        "target": target,
    }


def process_translation_job(user_id: int, vault: Any, job: dict[str, Any]) -> None:
    """Translate one already-claimed job and persist its terminal state."""
    from on1y.papers.settings_store import load_paper_settings

    settings = load_paper_settings(user_id)
    executable = resolve_babeldoc_executable(settings.translation_babeldoc_executable)
    if not executable:
        vault.fail_translation_job(
            job["id"],
            "BabelDOC is not installed. Run: "
            f"uv tool install --python 3.12 BabelDOC=={BABELDOC_VERSION}",
        )
        return
    source = str(job["source_lang"])
    target = str(job["target_lang"])
    input_path = vault.root / str(job["input_relpath"])
    if not input_path.is_file():
        vault.fail_translation_job(job["id"], f"original PDF not found: {input_path}")
        return
    bilingual_dir = input_path.parent.parent / "Bilingual"
    output_path = next_bilingual_path(
        bilingual_dir,
        input_path.stem,
        _output_suffix(source, target),
    )

    def progress(value: float, stage: str) -> None:
        vault.update_translation_progress(job["id"], value, stage)

    try:
        provider = str(job["provider"])
        config = _provider_config(user_id, provider, source, target)
        adapter = BabelDocSubprocessAdapter(
            executable=executable,
            provider_config=config,
            qps=settings.translation_qps,
            ocr_workaround=settings.translation_ocr_workaround,
            glossary_path=settings.translation_glossary_path,
            progress=progress,
        )
        usage = adapter.translate_pdf(
            input_path,
            output_path,
            source=source,
            target=target,
        )
        vault.complete_translation_job(job["id"], output_path, usage)
    except Exception as exc:
        logger.exception("Literature translation job %s failed", job["id"])
        vault.fail_translation_job(job["id"], str(exc))


def _translation_loop() -> None:
    from on1y.adapters.sqlite_storage import get_storage
    from on1y.papers.literature import LiteratureVault
    from on1y.papers.settings_store import paper_settings_path
    from on1y.user.accounts import list_sync_user_ids

    while not _TRANSLATION_STOP.is_set():
        worked = False
        try:
            storage = get_storage()
            try:
                # Translation jobs are explicit, persisted work. They must resume after a
                # backend restart even when nobody has opened a browser session yet.
                user_ids = list_sync_user_ids(storage, current_user_only=False)
            finally:
                storage.close()
            seen_vaults: set[str] = set()
            for user_id in user_ids:
                if _TRANSLATION_STOP.is_set():
                    break
                try:
                    # Do not create default Paper settings for unrelated accounts.
                    # A shared custom Vault is processed once by its first configured owner.
                    if not paper_settings_path(user_id).is_file():
                        continue
                    vault = LiteratureVault(user_id)
                    vault_key = os.path.normcase(str(vault.root))
                    if vault_key in seen_vaults:
                        continue
                    seen_vaults.add(vault_key)
                    if user_id not in _RECOVERED_USERS:
                        vault.recover_stale_translation_jobs()
                        _RECOVERED_USERS.add(user_id)
                    job = vault.claim_next_translation_job()
                    if job:
                        worked = True
                        process_translation_job(user_id, vault, job)
                except Exception:
                    logger.exception("Literature translation worker failed for user %s", user_id)
        except Exception:
            logger.exception("Literature translation worker tick failed")
        _TRANSLATION_STOP.wait(timeout=0.2 if worked else 3)


def start_literature_translation_loop() -> None:
    global _TRANSLATION_THREAD
    if _TRANSLATION_THREAD and _TRANSLATION_THREAD.is_alive():
        return
    _TRANSLATION_STOP.clear()
    _TRANSLATION_THREAD = threading.Thread(
        target=_translation_loop,
        name="on1y-literature-translation",
        daemon=True,
    )
    _TRANSLATION_THREAD.start()


def stop_literature_translation_loop() -> None:
    _TRANSLATION_STOP.set()
