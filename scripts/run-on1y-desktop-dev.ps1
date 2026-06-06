# Run On1y Tauri desktop in dev mode (requires Rust).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
$desktop = Join-Path $root "desktop"
$npm = Get-NpmCmd

if (-not (Initialize-RustPath)) {
    throw "Rust/cargo not found. Install from https://www.rust-lang.org/tools/install"
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & $python.Source (Join-Path $root "scripts\prepare-tauri-icons.py")
}

$env:ON1Y_ROOT = $root
Push-Location $desktop
try {
    & $npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    & $npm run dev
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
