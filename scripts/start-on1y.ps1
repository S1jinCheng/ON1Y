# Start On1y (on1y serve serves API + static UI; optional browser / desktop).
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start-on1y.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start-on1y.ps1 -Quiet
#   powershell -ExecutionPolicy Bypass -File scripts\start-on1y.ps1 -Dev   # next dev on :3000
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
$appUrl = if ($Dev) { "http://127.0.0.1:3000" } else { $backendUrl }
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
$openBrowser = -not $NoBrowser -and $prefOpenBrowser
$windowStyle = if ($Quiet) { "Minimized" } else { "Normal" }

try {
    $backendUp = Test-PortListening -Port $backendPort
    $devFrontendUp = $Dev -and (Test-PortListening -Port 3000)

    if ($backendUp -and (-not $Dev -or $devFrontendUp)) {
        if (-not $Quiet) {
            Write-Host "On1y is already running."
            Write-Host "  App: $appUrl"
        }
        if (-not $Dev) {
            $desktopExe = Get-On1yDesktopExe
            if ($desktopExe) {
                Start-Process -FilePath $desktopExe -WorkingDirectory $root | Out-Null
            }
            elseif ($openBrowser) {
                Open-On1yBrowser -Url $appUrl
            }
        }
        elseif ($openBrowser) {
            Open-On1yBrowser -Url $appUrl
        }
        exit 0
    }

    if (-not $Quiet) {
        Write-Host "On1y root: $root"
    }

    $backendScript = Join-Path $root "scripts\run-on1y-backend.ps1"
    $frontendScript = Join-Path $root "scripts\run-on1y-frontend.ps1"

    if (-not $Dev) {
        Ensure-FrontendReady -Quiet:$Quiet
    }

    if (-not $backendUp) {
        if (-not $Quiet) {
            Write-Host "Starting on1y serve..."
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

    if ($Dev -and -not $devFrontendUp) {
        if (-not $Quiet) {
            Write-Host "Starting frontend dev server..."
        }
        Start-Process powershell.exe `
            -WorkingDirectory $root `
            -WindowStyle $windowStyle `
            -ArgumentList @(
                "-NoExit",
                "-ExecutionPolicy", "Bypass",
                "-File", $frontendScript,
                "-Dev"
            )
    }

    if (-not $backendUp) {
        if (-not (Wait-ForHttpOk -Url "$backendUrl/api/auth/status" -TimeoutSeconds 120)) {
            throw "on1y serve did not become ready at $backendUrl"
        }
    }

    if ($Dev) {
        if (-not $devFrontendUp) {
            if (-not (Wait-ForHttpOk -Url "http://127.0.0.1:3000" -TimeoutSeconds 120)) {
                throw "Frontend dev server did not become ready at http://127.0.0.1:3000"
            }
        }
    }
    else {
        if (-not (Wait-ForHttpOk -Url $backendUrl -TimeoutSeconds 60)) {
            throw "Workbench UI not ready at $backendUrl (run scripts\build-frontend.ps1)"
        }
    }

    if (-not $Quiet) {
        Write-Host ""
        Write-Host "On1y is ready."
        Write-Host "  Open:  $appUrl"
        Write-Host "  Stop:  powershell -ExecutionPolicy Bypass -File scripts\stop-on1y.ps1"
    }

    if (-not $Dev) {
        Start-Sleep -Milliseconds 400
        $desktopExe = Get-On1yDesktopExe
        if ($desktopExe) {
            Start-Process -FilePath $desktopExe -WorkingDirectory $root | Out-Null
        }
        elseif ($openBrowser) {
            Open-On1yBrowser -Url $appUrl
        }
    }
    elseif ($openBrowser) {
        Start-Sleep -Milliseconds 400
        Open-On1yBrowser -Url $appUrl
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
