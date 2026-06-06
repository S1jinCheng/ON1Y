# On1y frontend worker window (Next.js). Build is done in start-on1y.ps1.
param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$host.UI.RawUI.WindowTitle = "On1y Frontend"
$root = Get-On1yRoot
$frontend = Join-Path $root "frontend"
Set-Location $frontend

$npm = Get-NpmCmd
$env:NEXT_PUBLIC_ON1Y_API_BASE = Get-On1yBackendUrl
Write-Host "Using npm: $npm"
Write-Host "API base: $env:NEXT_PUBLIC_ON1Y_API_BASE"

if ($Dev) {
    Write-Host "Starting On1y frontend (dev) at $(Get-On1yFrontendUrl) ..."
    & $npm run dev
    exit $LASTEXITCODE
}

if (-not (Test-Path ".next\BUILD_ID")) {
    Write-Host "ERROR: frontend not built. Run: powershell -File scripts\start-on1y.ps1" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host "Starting On1y frontend at $(Get-On1yFrontendUrl) ..."
& $npm run start
