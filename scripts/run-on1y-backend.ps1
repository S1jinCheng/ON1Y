# On1y backend worker window (on1y serve).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$host.UI.RawUI.WindowTitle = "On1y Backend"
$root = Get-On1yRoot
$env:ON1Y_ROOT = $root
$env:ON1Y_DATA_DIR = Join-Path $root "data"
$env:ON1Y_DB_PATH = Join-Path $root "data\on1y.db"
Set-Location $root

# SQLite WAL requires write access to data/; fix inherited RX-only ACLs once per machine.
$dataDir = Join-Path $root "data"
$dbFile = Join-Path $dataDir "on1y.db"
if ((Test-Path $dbFile) -and -not (Test-Path (Join-Path $dataDir ".permissions-ok"))) {
    try {
        $probe = Join-Path $dataDir ".write-probe"
        Set-Content -Path $probe -Value "ok" -Encoding ascii
        Remove-Item $probe -Force
        New-Item -ItemType File -Path (Join-Path $dataDir ".permissions-ok") -Force | Out-Null
    }
    catch {
        Write-Host "Data folder is not writable; fixing permissions ..."
        & (Join-Path $root "scripts\fix-data-permissions.ps1")
        New-Item -ItemType File -Path (Join-Path $dataDir ".permissions-ok") -Force | Out-Null
    }
}

$on1yExe = Get-On1yCliExe
Write-Host "Starting On1y backend at $(Get-On1yBackendUrl) ..."
Write-Host "Using: $on1yExe"
& $on1yExe serve
