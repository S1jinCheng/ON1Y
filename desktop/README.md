# On1y Desktop (Tauri)

Native Windows shell for On1y: **WebView2** window + system tray, no browser chrome.

## What it does

1. Starts `on1y serve` (8765) if not already running  
2. Starts `npm run start` in `frontend/` (3000) if not already running  
3. Opens the workbench inside a desktop window  
4. Close button **hides to tray**; use tray menu **退出** to stop services this app started  

## Prerequisites (one-time)

1. **Rust** — https://www.rust-lang.org/tools/install  
   ```powershell
   winget install Rustlang.Rustup
   ```
   Reopen PowerShell after install.

2. **WebView2** — included in Windows 10/11; if missing:  
   https://developer.microsoft.com/microsoft-edge/webview2/

3. Existing On1y dev stack: conda env `on1y`, Node.js, frontend production build.

## Build

```powershell
cd D:\On1y
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
```

Output:

- `desktop\src-tauri\target\release\On1y.exe`
- Optional installer: `desktop\src-tauri\target\release\bundle\nsis\On1y_*.exe`

## Install shortcuts

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-on1y-desktop.ps1
powershell -ExecutionPolicy Bypass -File scripts\install-on1y-autostart.ps1
```

## Dev (hot reload shell only)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-on1y-desktop-dev.ps1
```

## Environment

| Variable | Purpose |
|----------|---------|
| `ON1Y_ROOT` | Repo root (`D:\On1y`) |
| `ON1Y_NPM_CMD` | Path to `npm.cmd` if not on PATH |

## Roadmap

- Phase 2: serve static `frontend/out` from `on1y serve` only (drop Node at runtime)  
- Phase 3: bundle `on1y-core` + installer without conda  
