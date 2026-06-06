# Stop On1y desktop app and on1y serve (legacy :3000 dev server if any).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$stoppedDesktop = Stop-On1yDesktopProcess
$backendPort = Get-On1yBackendPort
$stoppedBackend = Stop-PortListener -Port $backendPort
$stoppedDevFrontend = Stop-PortListener -Port 3000

$total = $stoppedDesktop + $stoppedBackend + $stoppedDevFrontend
if ($total -eq 0) {
    Write-Host "On1y does not appear to be running (desktop app and port $backendPort are free)."
}
else {
    Write-Host "On1y stopped (desktop=$stoppedDesktop, serve=$stoppedBackend, dev-frontend=$stoppedDevFrontend)."
}
