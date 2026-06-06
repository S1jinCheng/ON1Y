# Stop On1y backend (8765) and frontend (3000).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$backendPort = Get-On1yBackendPort
$stoppedBackend = Stop-PortListener -Port $backendPort
$stoppedFrontend = Stop-PortListener -Port 3000

if (($stoppedBackend + $stoppedFrontend) -eq 0) {
    Write-Host "On1y does not appear to be running (ports $backendPort and 3000 are free)."
}
else {
    Write-Host "On1y stopped."
}
