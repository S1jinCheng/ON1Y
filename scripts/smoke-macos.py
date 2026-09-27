"""Start a packaged backend with temporary data and verify HTTP and SQLite startup."""

from __future__ import annotations

import argparse
import io
import json
import os
import socket
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


def upload_archive(opener, base_url: str, token: str, items: list[dict], mode="overwrite"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "on1y-archive",
                    "version": 1,
                    "item_count": len(items),
                    "include_settings": False,
                }
            ),
        )
        archive.writestr("themes.json", "[]")
        archive.writestr(
            "items.jsonl", "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n"
        )
    boundary = "on1y-isolated-archive-smoke"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="smoke.on1y.zip"\r\nContent-Type: application/zip\r\n\r\n'
        ).encode()
        + buffer.getvalue()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = Request(
        f"{base_url}/api/user/archive/import?on_conflict={mode}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with opener.open(request, timeout=20) as response:
        return json.load(response)


def download_archive_items(opener, base_url: str, token: str):
    request = Request(
        f"{base_url}/api/user/archive/export", headers={"Authorization": f"Bearer {token}"}
    )
    with (
        opener.open(request, timeout=20) as response,
        zipfile.ZipFile(io.BytesIO(response.read())) as archive,
    ):
        return [
            json.loads(line)
            for line in archive.read("items.jsonl").decode("utf-8").split("\n")
            if line.strip()
        ]


def check_archive_roundtrip(opener, base_url: str, token: str) -> None:
    """Exercise Unicode and conflict handling with synthetic content in the frozen backend."""
    text = '前段\u2028中段\u2029尾段\x85附注 "引号"\n换行'
    item = {
        "url": "https://example.com/on1y-archive-smoke",
        "platform": "web",
        "source": "manual",
        "raw_title": text,
        "body_text": text,
        "content_type": "article",
        "extract_status": "ok",
        "source_meta": {"user_note_html": text},
        "distill": {"summary": "original summary"},
    }
    target = {**item, "url": "https://example.com/on1y-archive-target"}
    item["relations"] = [
        {
            "to_url": target["url"],
            "relation_type": "related",
            "note": "original link",
            "source": "user",
        }
    ]
    result = upload_archive(opener, base_url, token, [item, target])
    assert result["imported"] == 2 and result["error_count"] == 0
    restored = download_archive_items(opener, base_url, token)[0]
    assert restored["body_text"] == text
    assert restored["source_meta"]["user_note_html"] == text

    changed = {
        **item,
        "body_text": "replacement body",
        "relations": [{**item["relations"][0], "note": "must not overwrite on skip"}],
    }
    changed.pop("distill")
    result = upload_archive(opener, base_url, token, [changed, target], mode="skip")
    assert (result["imported"], result["skipped"], result["error_count"]) == (0, 2, 0)
    restored = download_archive_items(opener, base_url, token)[0]
    assert restored["body_text"] == text
    assert restored["relations"][0]["note"] == "original link"
    assert restored["distill"]["summary"] == "original summary"

    changed["relations"] = []
    result = upload_archive(opener, base_url, token, [changed])
    assert result["imported"] == 1 and result["error_count"] == 0
    restored = download_archive_items(opener, base_url, token)[0]
    assert restored["body_text"] == "replacement body"
    assert restored["relations"] == []
    assert "distill" not in restored


def smoke(bundle: Path) -> None:
    resources = bundle.resolve() / "Contents" / "Resources"
    backend = resources / "backend" / "on1y" / "on1y"
    root = resources / "app"
    if not backend.is_file() or not (root / "frontend/out/index.html").is_file():
        raise FileNotFoundError(f"Incomplete On1y application bundle: {bundle}")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="on1y-mac-smoke-") as temporary:
        data = Path(temporary)
        env = {
            **os.environ,
            "ON1Y_ROOT": str(root),
            "ON1Y_DATA_DIR": str(data),
            "ON1Y_DB_PATH": str(data / "on1y.db"),
            "ON1Y_DISABLE_DOTENV": "1",
            "ON1Y_AUTH_REQUIRED": "true",
            "ON1Y_AUTH_ALLOW_REGISTRATION": "true",
            "ON1Y_SINGLE_USER_MODE": "false",
            "ON1Y_BOOTSTRAP_PASSWORD": "",
            "ON1Y_AUTH_SECRET_KEY": "isolated-smoke-test-secret",
            "ON1Y_WEB_HOST": "127.0.0.1",
            "ON1Y_WEB_PORT": str(port),
            "ON1Y_BUNDLED": "1",
            "ON1Y_DESKTOP_SHELL": "1",
            "ON1Y_LAUNCH_PREFS_FILE": str(data / "bootstrap/app-launch.json"),
            "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        }
        native = subprocess.run(
            [str(backend), "--self-test"],
            cwd=data,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if native.returncode != 0:
            raise RuntimeError(f"Native dependency test failed:\n{native.stdout}\n{native.stderr}")
        print(native.stdout.strip())
        opener = build_opener(ProxyHandler({}))
        with (data / "backend.log").open("w+") as log:
            process = subprocess.Popen(
                [str(backend), "serve"], cwd=root, env=env, stdout=log, stderr=log
            )
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"Backend exited with {process.returncode}")
                    try:
                        url = f"http://127.0.0.1:{port}/api/auth/status"
                        with opener.open(url, timeout=2) as response:
                            assert response.status == 200
                            assert json.load(response)["user_count"] == 0
                        break
                    except (URLError, TimeoutError):
                        time.sleep(0.25)
                else:
                    raise TimeoutError("Packaged backend did not become healthy")
                registration = Request(
                    f"http://127.0.0.1:{port}/api/auth/register",
                    data=json.dumps(
                        {"username": "smoke-test", "password": "isolated-test-password"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with opener.open(registration, timeout=10) as response:
                    token = json.load(response)["token"]
                login = Request(
                    f"http://127.0.0.1:{port}/api/auth/login",
                    data=json.dumps(
                        {"username": "smoke-test", "password": "isolated-test-password"}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with opener.open(login, timeout=10) as response:
                    token = json.load(response)["token"]
                    assert token
                for path in ("/", "/api/app/desktop", "/api/device-sync", "/api/papers/settings"):
                    request = Request(
                        f"http://127.0.0.1:{port}{path}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    with opener.open(request, timeout=10) as response:
                        body = response.read()
                        assert response.status == 200
                        if path == "/":
                            assert b"/_next/" in body
                        elif path == "/api/app/desktop":
                            status = json.loads(body)
                            assert status["platform"] == "darwin"
                            assert status["is_bundled_release"]
                            assert Path(status["data_dir"]).resolve() == data.resolve()
                        elif path == "/api/device-sync":
                            assert not json.loads(body)["enabled"]
                        else:
                            vault = Path(json.loads(body)["literature_vault_path"])
                            assert vault.is_absolute() and vault.resolve().is_relative_to(
                                data.resolve()
                            )
                assert (data / "on1y.db").is_file()
                check_archive_roundtrip(opener, f"http://127.0.0.1:{port}", token)
                print(
                    "PASS: native libraries, login, frontend, sync API, "
                    "Unicode archive and conflicts"
                )
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read())
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    smoke(parser.parse_args().bundle)
