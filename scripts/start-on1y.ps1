# Start On1y as a local desktop app (backend + frontend + optional browser).
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start-on1y.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start-on1y.ps1 -Quiet   # login autostart (minimized windows)
param(
    [switch]$Quiet,
    [switch]$NoBrowser,
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
$env:ON1Y_ROOT = $root
$backendPort = Get-On1yBackendPort
$backendUrl = Get-On1yBackendUrl
$frontendUrl = Get-On1yFrontendUrl
$launchPrefsPath = Join-Path $root "data\app-launch.json"
$prefOpenBrowser = $true
if (Test-Path $launchPrefsPath) {
    try {
        $launchPrefs = Get-Content $launchPrefsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -ne $launchPrefs.open_browser_on_start) {
            $prefOpenBrowser = [bool]$launchPrefs.open_browser_on_start
        }
    }
    catch {
        # keep default
    }
}
# Quiet only minimizes worker windows; browser follows data/app-launch.json (settings toggle).
$openBrowser = -not $NoBrowser -and $prefOpenBrowser
$windowStyle = if ($Quiet) { "Minimized" } else { "Normal" }

try {
    $backendUp = Test-PortListening -Port $backendPort
    $frontendUp = Test-PortListening -Port 3000

    if ($backendUp -and $frontendUp) {
        if ($openBrowser) {
            Open-On1yBrowser -Url $frontendUrl
        }
        elseif (-not $Quiet) {
            Write-Host "On1y is already running."
            Write-Host "  Frontend: $frontendUrl"
            Write-Host "  Backend:  $backendUrl"
        }
        exit 0
    }

    if (-not $Quiet) {
        Write-Host "On1y root: $root"
    }

    $backendScript = Join-Path $root "scripts\run-on1y-backend.ps1"
    $frontendScript = Join-Path $root "scripts\run-on1y-frontend.ps1"

    if (-not $frontendUp -and -not $Dev) {
        Ensure-FrontendReady -Dev:$Dev -Quiet:$Quiet
    }

    if (-not $backendUp) {
        if (-not $Quiet) {
            Write-Host "Starting backend..."
        }
        Start-Process powershell.exe `
            -WorkingDirectory $root `
            -WindowStyle $windowStyle `
            -ArgumentList @(
                "-NoExit",
                "-ExecutionPolicy", "Bypass",
                "-File", $backendScript
            )
        Start-Sleep -Seconds 2
    }

    if (-not $frontendUp) {
        if (-not $Quiet) {
            Write-Host "Starting frontend..."
        }
        $frontendArgs = @(
            "-NoExit",
            "-ExecutionPolicy", "Bypass",
            "-File", $frontendScript
        )
        if ($Dev) {
            $frontendArgs += "-Dev"
        }
        Start-Process powershell.exe `
            -WorkingDirectory $root `
            -WindowStyle $windowStyle `
            -ArgumentList $frontendArgs
    }

    if (-not $backendUp) {
        if (-not (Wait-ForHttpOk -Url "$backendUrl/api/auth/status" -TimeoutSeconds 120)) {
            throw "Backend did not become ready at $backendUrl (check the On1y Backend window)"
        }
    }

    if (-not $frontendUp) {
        $frontendTimeout = if ($Dev) { 120 } else { 60 }
        if (-not (Wait-ForHttpOk -Url $frontendUrl -TimeoutSeconds $frontendTimeout)) {
            throw "Frontend did not become ready at $frontendUrl (check the On1y Frontend window)"
        }
    }

    if ($openBrowser) {
        Start-Sleep -Milliseconds 400
        Open-On1yBrowser -Url $frontendUrl
    }

    if (-not $Quiet) {
        Write-Host ""
        Write-Host "On1y is ready."
        Write-Host "  Open:     $frontendUrl"
        Write-Host "  Backend:  $backendUrl"
        Write-Host "  Stop:     powershell -ExecutionPolicy Bypass -File scripts\stop-on1y.ps1"
    }
}
catch {
    Write-On1yStartLog -Message $_.Exception.Message
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $(Join-Path $root 'data\on1y-start.log')"
  if (-not $Quiet) {
        Read-Host "Press Enter to close"
    }
    exit 1
}
