# Build On1y Tauri desktop app (requires Rust + Node.js).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
$desktop = Join-Path $root "desktop"
$npm = Get-NpmCmd

if (-not (Initialize-RustPath)) {
    Write-Host "Rust toolchain not found." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Install Rust (one-time):"
    Write-Host "  https://www.rust-lang.org/tools/install"
    Write-Host "  or: winget install Rustlang.Rustup"
    Write-Host ""
    Write-Host "If you already installed Rust, close and reopen PowerShell, then retry."
    exit 1
}

Write-Host "Preparing frontend production build..."
Ensure-FrontendReady -ForceRebuild

Write-Host "Preparing Tauri icons..."
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & $python.Source (Join-Path $root "scripts\prepare-tauri-icons.py")
}
else {
    Write-Host "WARN: python not found; ensure desktop/src-tauri/icons exists" -ForegroundColor Yellow
}

Write-Host "Installing desktop npm deps..."
Push-Location $desktop
try {
    & $npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed in desktop/" }

    $env:ON1Y_ROOT = $root
    if (Stop-On1yDesktopProcess -gt 0) {
        Write-Host "Closed running On1y.exe so the build can replace it."
    }
    Write-Host "Building On1y desktop (first run may take several minutes)..."
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw "tauri build failed" }
}
finally {
    Pop-Location
}

$releaseExe = Join-Path $desktop "src-tauri\target\release\On1y.exe"
$bundleExe = Get-ChildItem -Path (Join-Path $desktop "src-tauri\target\release\bundle\nsis") -Filter "On1y_*.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1

Write-Host ""
Write-Host "Desktop build OK."
if (Test-Path $releaseExe) {
    Write-Host "  App:    $releaseExe"
}
if ($bundleExe) {
    Write-Host "  Setup:  $($bundleExe.FullName)"
}
Write-Host ""
Write-Host "Update desktop shortcut:"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\install-on1y-desktop.ps1"
