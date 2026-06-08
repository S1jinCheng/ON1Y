# Assemble dist/portable (backend + app assets) for Tauri NSIS installer.
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
$dist = Join-Path $root "dist\portable"
$appDir = Join-Path $dist "app"
$backendDir = Join-Path $dist "backend"

Write-Host "=== On1y release packaging ===" -ForegroundColor Cyan

Stop-On1yDesktopProcess | Out-Null
Get-Process -Name "on1y" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800

Initialize-On1yConda

Write-Host "[1/3] Frontend static export..."
Ensure-FrontendReady -ForceRebuild -Quiet

Write-Host "[2/3] PyInstaller backend (first run may take several minutes)..."
$pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if (-not $pyinstaller) {
    Write-Host "Installing PyInstaller into conda env on1y..."
    pip install "pyinstaller>=6.0"
}
Push-Location $root
try {
    & pyinstaller (Join-Path $root "packaging\on1y.spec") --noconfirm --distpath (Join-Path $dist "backend-build") --workpath (Join-Path $root "build\pyinstaller") --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
}
finally {
    Pop-Location
}

Write-Host "[3/3] Staging app resources for installer..."
if (Test-Path $appDir) { Remove-Item -Recurse -Force $appDir }
if (Test-Path $backendDir) { Remove-Item -Recurse -Force $backendDir }
New-Item -ItemType Directory -Path $appDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appDir "config") -Force | Out-Null
New-Item -ItemType Directory -Path $backendDir -Force | Out-Null

$pyOut = Join-Path $dist "backend-build\on1y"
if (-not (Test-Path (Join-Path $pyOut "on1y.exe"))) {
    throw "PyInstaller output missing: $pyOut\on1y.exe"
}
Copy-Item -Recurse -Force $pyOut (Join-Path $backendDir "on1y")

Copy-Item -Recurse -Force (Join-Path $root "frontend\out") (Join-Path $appDir "frontend\out")
Copy-Item -Recurse -Force (Join-Path $root "sql") (Join-Path $appDir "sql")
Copy-Item -Force (Join-Path $root ".env.example") (Join-Path $appDir ".env.example")
foreach ($name in @("feeds.yaml.example", "zhihu_follows.txt.example", "youtube_channels.txt.example", "user_profile.json.example")) {
    $src = Join-Path $root "config\$name"
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $appDir "config\$name")
    }
}

Write-Host ""
Write-Host "Release resources ready:" -ForegroundColor Green
Write-Host "  App assets:  $appDir"
Write-Host "  Backend:     $(Join-Path $backendDir 'on1y\on1y.exe')"
Write-Host ""
Write-Host "Next: build NSIS installer"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1"
