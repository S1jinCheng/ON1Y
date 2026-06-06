# One-time / manual frontend production build.
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

Ensure-FrontendReady -ForceRebuild
Write-Host "Frontend build OK."
