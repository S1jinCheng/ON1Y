# On1y Desktop (Tauri)

Native desktop shell for On1y: WebView2 on Windows, WKWebView on macOS,
with a system tray / menu bar icon and a bundled Python backend.

## macOS

The macOS build targets macOS 14+ and the architecture of the build machine.
Apple Silicon and Intel must be built separately with matching Python, Node and
Rust architectures; a universal Rust executable alone does not make the Python
backend universal. Apple Silicon is the initial local validation target.

Install Xcode Command Line Tools, Python 3.11, Node.js 22.13+ and a current stable
Rust toolchain. From the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
npm ci --prefix frontend
npm ci --prefix desktop
bash scripts/run-macos.sh
```

Build a self-contained app and disk image:

```bash
bash scripts/build-macos.sh
# Or build only the application bundle:
bash scripts/build-macos.sh --bundles app
```

The script exports the frontend, bundles Python with PyInstaller, preserves
Chromium's native app and framework structure, stages public configuration
templates, generates the macOS icon, and invokes
Tauri. Output is in `desktop/src-tauri/target/release/bundle/macos/On1y.app`
and `desktop/src-tauri/target/release/bundle/dmg/`. End users do not need Python,
Node, Rust or WebView2 installed. The PaddleOCR model downloads on first use
unless `data/models/PP-DocLayout-M` is present when building.

Packaged user data lives in `~/Library/Application Support/On1y/data`; writable
configuration and `.env` live alongside it. Data directory overrides are stored
there so app upgrades do not overwrite user data or modify the signed app bundle.
Source builds keep their data in the repository's `data/` directory.

The desktop settings can register a user LaunchAgent for the next login. Disabling
it removes only `~/Library/LaunchAgents/app.on1y.desktop.plist`. Moving the app
after enabling startup requires toggling startup off and on to refresh its path.
PDF reader selection accepts `.app` bundles, and updates select the matching
architecture's `.dmg` instead of the Windows installer.

Local builds use ad-hoc signing. For distribution outside your own Mac, configure
an Apple Developer signing identity and notarization credentials using
[Tauri's macOS signing guide](https://v2.tauri.app/distribute/sign/macos/).
Set `APPLE_SIGNING_IDENTITY` for both the Python backend and Tauri; the build
script does not publish a GitHub release or provision signing credentials.

Verify a built app without touching your real knowledge library:

```bash
.venv/bin/python scripts/smoke-macos.py desktop/src-tauri/target/release/bundle/macos/On1y.app
```

This checks native Paddle/PDF/SQLite dependencies, first launch with an empty
database, local test-account registration, the frontend and the desktop API.
The test account and database are removed with the temporary test directory.

## Windows

## Architecture (phase 2)

```
On1y.exe
  └─ on1y serve :8765
       ├─ /api/*        → FastAPI
       └─ /*            → frontend/out (static export)
```

No Node.js / `npm run start` at runtime.

## Prerequisites

1. **Rust** — https://www.rust-lang.org/tools/install  
2. **WebView2** — included in Windows 10/11  
3. **Conda env `on1y`** + **Node.js** (build-time only for `npm run build`)

## Build

```powershell
cd D:\On1y
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
powershell -ExecutionPolicy Bypass -File scripts\install-on1y-desktop.ps1
```

`build-desktop.ps1` runs `npm run build` (static export → `frontend/out/`) then compiles Tauri.

## Dev

- **UI hot reload**: `powershell -File scripts\start-on1y.ps1 -Dev` (backend + `next dev` on :3000)  
- **Desktop shell dev**: `powershell -File scripts\run-on1y-desktop-dev.ps1`

## Personal sync

Personal Windows / Mac sync is opt-in and uses a separate, single-library relay.
Setup, privacy boundaries and local testing are documented in
[PERSONAL-SYNC.md](PERSONAL-SYNC.md).

## Stop

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop-on1y.ps1
```
