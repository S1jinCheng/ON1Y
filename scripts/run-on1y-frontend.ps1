# Dev-only: Next.js dev server on :3000 (production UI is served by on1y serve).
param(
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

if (-not $Dev) {
    Write-Host "Production mode no longer uses a separate frontend process." -ForegroundColor Yellow
    Write-Host "UI is served by on1y serve at $(Get-On1yBackendUrl)"
    Write-Host "Use: powershell -File scripts\start-on1y.ps1"
    Read-Host "Press Enter to close"
    exit 0
}

$host.UI.RawUI.WindowTitle = "On1y Frontend (dev)"
$root = Get-On1yRoot
$frontend = Join-Path $root "frontend"
Set-Location $frontend

$npm = Get-NpmCmd
$env:NEXT_PUBLIC_ON1Y_API_BASE = Get-On1yBackendUrl
Write-Host "Using npm: $npm"
Write-Host "API base: $env:NEXT_PUBLIC_ON1Y_API_BASE"
Write-Host "Starting Next.js dev at http://127.0.0.1:3000 ..."
& $npm run dev
exit $LASTEXITCODE
