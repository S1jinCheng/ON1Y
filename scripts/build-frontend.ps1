# One-time / manual frontend production build.
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
Ensure-FrontendReady -ForceRebuild
if (Sync-FrontendToPortableBundle -Root $root) {
    Write-Host "Synced frontend/out -> dist/portable/app/frontend/out"
}
Write-Host "Frontend build OK."
Write-Host ""
Write-Host "Note: target\release\On1y.exe embeds resources from the LAST build-desktop run."
Write-Host "  UI only:  powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1"
Write-Host "  Python too: package-release.ps1 then build-desktop.ps1"
Write-Host "  Dev (no rebuild): on1y serve  -> http://127.0.0.1:8765"
