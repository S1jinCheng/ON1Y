# On1y Desktop (Tauri)

Native Windows shell for On1y: **WebView2** window + system tray.

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

## Stop

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop-on1y.ps1
```
