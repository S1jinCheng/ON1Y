# Ensure the current Windows user can read/write On1y data (SQLite needs write for WAL).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
$data = Join-Path $root "data"
if (-not (Test-Path $data)) {
    New-Item -ItemType Directory -Path $data -Force | Out-Null
}

$user = $env:USERNAME
Write-Host "Granting Modify on $data to $user ..."
icacls $data /grant "${user}:(OI)(CI)M" /T | Out-Null
Write-Host "Done. Re-run start-on1y if the backend failed before."
