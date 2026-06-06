# Shared helpers for On1y Windows app scripts (start / stop / autostart).

function Get-On1yRoot {
    if ($env:ON1Y_ROOT -and (Test-Path $env:ON1Y_ROOT)) {
        return (Resolve-Path $env:ON1Y_ROOT).Path
    }
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Initialize-On1yConda {
    if (Get-Command conda -ErrorAction SilentlyContinue) {
        conda activate on1y
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to activate conda env 'on1y'. Run: conda create -n on1y python=3.11"
        }
        return
    }

    $condaCandidates = @(
        "$env:USERPROFILE\anaconda3\Scripts\conda.exe",
        "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
        "$env:USERPROFILE\Anaconda3\Scripts\conda.exe",
        "D:\anaconda\Scripts\conda.exe",
        "$env:LOCALAPPDATA\miniconda3\Scripts\conda.exe",
        "$env:ProgramData\miniconda3\Scripts\conda.exe"
    )

    foreach ($condaExe in $condaCandidates) {
        if (-not (Test-Path $condaExe)) {
            continue
        }
        $hook = & $condaExe "shell.powershell" "hook" | Out-String
        Invoke-Expression $hook
        conda activate on1y
        if ($LASTEXITCODE -ne 0) {
            throw "Found conda at $condaExe but env 'on1y' is missing."
        }
        return
    }

    throw "conda not found. Install Anaconda/Miniconda and create env: conda create -n on1y python=3.11"
}

function Test-PortListening {
    param([int]$Port)
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        return $null -ne $conn
    }
    catch {
        $line = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING" | Select-Object -First 1
        return $null -ne $line
    }
}

function Wait-ForHttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 90,
        [int]$IntervalMs = 500
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
            # not ready yet
        }
        Start-Sleep -Milliseconds $IntervalMs
    }
    return $false
}

function Stop-PortListener {
    param([int]$Port)
    $stopped = 0
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            $procId = $conn.OwningProcess
            if (-not $procId) { continue }
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "Stopping $($proc.ProcessName) (PID $procId) on port $Port"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $stopped++
            }
        }
    }
    catch {
        $lines = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
        foreach ($line in $lines) {
            $procId = [int]($line -replace '^\s+|\s+$', '' -split '\s+')[-1]
            if ($procId -gt 0) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $stopped++
            }
        }
    }
    return $stopped
}

function Get-On1yBackendPort {
    $port = 8765
    if ($env:ON1Y_WEB_PORT) {
        $port = [int]$env:ON1Y_WEB_PORT
    }
    elseif (Test-Path (Join-Path (Get-On1yRoot) ".env")) {
        $match = Select-String -Path (Join-Path (Get-On1yRoot) ".env") -Pattern '^\s*ON1Y_WEB_PORT\s*=\s*(\d+)' |
            Select-Object -First 1
        if ($match) {
            $port = [int]$match.Matches[0].Groups[1].Value
        }
    }
    return $port
}

function Get-On1yFrontendUrl {
    return "http://127.0.0.1:3000"
}

function Get-On1yBackendUrl {
    $port = Get-On1yBackendPort
    return "http://127.0.0.1:$port"
}

function Get-On1yCliExe {
    $names = @("on1y.exe", "on1y")
    $envRoots = @(
        "$env:CONDA_PREFIX\Scripts",
        "$env:USERPROFILE\anaconda3\envs\on1y\Scripts",
        "$env:USERPROFILE\miniconda3\envs\on1y\Scripts",
        "$env:USERPROFILE\Anaconda3\envs\on1y\Scripts",
        "D:\anaconda\envs\on1y\Scripts",
        "$env:LOCALAPPDATA\miniconda3\envs\on1y\Scripts"
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($dir in $envRoots) {
        foreach ($name in $names) {
            $candidate = Join-Path $dir $name
            if (Test-Path $candidate) {
                return (Resolve-Path $candidate).Path
            }
        }
    }

    Initialize-On1yConda
    return (Get-Command on1y -ErrorAction Stop).Source
}

function Open-On1yBrowser {
    param([string]$Url)
    try {
        Start-Process $Url | Out-Null
    }
    catch {
        Start-Process "cmd.exe" -ArgumentList @("/c", "start", '""', $Url) | Out-Null
    }
}

function Write-On1yStartLog {
    param([string]$Message)
    $root = Get-On1yRoot
    $logDir = Join-Path $root "data"
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path (Join-Path $logDir "on1y-start.log") -Value $line -Encoding utf8
}

function Initialize-RustPath {
    if (Get-Command cargo -ErrorAction SilentlyContinue) {
        return $true
    }
    $cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE ".cargo" }
    $cargoBin = Join-Path $cargoHome "bin"
    $cargoExe = Join-Path $cargoBin "cargo.exe"
    if (-not (Test-Path $cargoExe)) {
        return $false
    }
    $env:PATH = "$cargoBin;$env:PATH"
    return $null -ne (Get-Command cargo -ErrorAction SilentlyContinue)
}

function Stop-On1yDesktopProcess {
    $stopped = 0
    foreach ($proc in Get-Process -Name "On1y" -ErrorAction SilentlyContinue) {
        Write-Host "Stopping On1y desktop (PID $($proc.Id))..."
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        $stopped++
    }
    if ($stopped -gt 0) {
        Start-Sleep -Milliseconds 800
    }
    return $stopped
}

function Get-On1yDesktopExe {
    $root = Get-On1yRoot
    $candidates = @(
        (Join-Path $root "desktop\src-tauri\target\release\On1y.exe"),
        (Join-Path $root "desktop\src-tauri\target\debug\On1y.exe")
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return (Resolve-Path $path).Path
        }
    }
    return $null
}

function Get-NpmCmd {
    if ($env:ON1Y_NPM_CMD -and (Test-Path $env:ON1Y_NPM_CMD)) {
        return (Resolve-Path $env:ON1Y_NPM_CMD).Path
    }

    $candidates = @(
        "D:\npm.cmd",
        "$env:ProgramFiles\nodejs\npm.cmd",
        "${env:ProgramFiles(x86)}\nodejs\npm.cmd",
        "$env:APPDATA\npm\npm.cmd",
        "$env:LOCALAPPDATA\Programs\nodejs\npm.cmd"
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) {
            return (Resolve-Path $path).Path
        }
    }

    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "npm not found. Install Node.js LTS or set ON1Y_NPM_CMD to npm.cmd"
}

function Test-FrontendBuildStale {
    param([string]$FrontendDir)
    $buildId = Join-Path $FrontendDir ".next\BUILD_ID"
    if (-not (Test-Path $buildId)) {
        return $true
    }
    $buildTime = (Get-Item $buildId).LastWriteTimeUtc
    $srcRoot = Join-Path $FrontendDir "src"
    if (-not (Test-Path $srcRoot)) {
        return $false
    }
    $latestSrc = Get-ChildItem $srcRoot -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latestSrc) {
        return $false
    }
    return $latestSrc.LastWriteTimeUtc -gt $buildTime
}

function Test-FrontendBuildMissing {
    param([string]$FrontendDir)
    return -not (Test-Path (Join-Path $FrontendDir ".next\BUILD_ID"))
}

function Invoke-FrontendBuild {
    param(
        [string]$FrontendDir,
        [switch]$Quiet
    )
    $npm = Get-NpmCmd
    $env:NEXT_PUBLIC_ON1Y_API_BASE = Get-On1yBackendUrl
    if (-not $Quiet) {
        Write-Host "Building frontend (1-3 min, please wait)..."
    }
    Push-Location $FrontendDir
    try {
        & $npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
    }
    finally {
        Pop-Location
    }
}

function Ensure-FrontendReady {
    param(
        [switch]$Dev,
        [switch]$Quiet,
        [switch]$ForceRebuild
    )
    $root = Get-On1yRoot
    $frontend = Join-Path $root "frontend"
    $npm = Get-NpmCmd
    $env:NEXT_PUBLIC_ON1Y_API_BASE = Get-On1yBackendUrl

    if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
        if (-not $Quiet) {
            Write-Host "Installing frontend dependencies (first run)..."
        }
        Push-Location $frontend
        try {
            & $npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
        }
        finally {
            Pop-Location
        }
    }

    if ($Dev) {
        return
    }

    if (Test-FrontendBuildMissing -FrontendDir $frontend) {
        Invoke-FrontendBuild -FrontendDir $frontend -Quiet:$Quiet
        return
    }

    if ($ForceRebuild) {
        Invoke-FrontendBuild -FrontendDir $frontend -Quiet:$Quiet
        return
    }

    if ((Test-FrontendBuildStale -FrontendDir $frontend) -and -not $Quiet) {
        Write-Host "Frontend source is newer than the last build; starting with the existing build."
        Write-Host "To apply UI changes: powershell -ExecutionPolicy Bypass -File scripts\build-frontend.ps1"
    }
}
