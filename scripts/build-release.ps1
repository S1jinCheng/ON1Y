# Full Windows release: portable bundle + Tauri NSIS installer.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "package-release.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot "build-desktop.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
