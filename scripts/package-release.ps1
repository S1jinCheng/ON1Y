# Assemble dist/portable (backend + app assets) for Tauri NSIS / zip release.
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

Write-Host "[1/4] Frontend static export..."
Ensure-FrontendReady -ForceRebuild -Quiet

Write-Host "[2/4] PyInstaller backend (first run may take several minutes)..."
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

Write-Host "[3/4] Staging portable app layout..."
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

Write-Host "[4/4] Creating zip archive..."
Stop-On1yDesktopProcess | Out-Null
Start-Sleep -Milliseconds 500
$version = "0.1.0"
$zipPath = Join-Path $root "dist\On1y-portable-$version-win64.zip"
$zipStage = Join-Path $root "dist\zip-stage"
if (Test-Path $zipStage) { Remove-Item -Recurse -Force $zipStage }
New-Item -ItemType Directory -Path $zipStage | Out-Null
Copy-Item -Recurse -Force $appDir (Join-Path $zipStage "app")
Copy-Item -Recurse -Force $backendDir (Join-Path $zipStage "backend")
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path (Join-Path $zipStage "*") -DestinationPath $zipPath -Force
Remove-Item -Recurse -Force $zipStage -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Portable bundle ready:" -ForegroundColor Green
Write-Host "  App assets:  $appDir"
Write-Host "  Backend:     $(Join-Path $backendDir 'on1y\on1y.exe')"
Write-Host "  Zip:         $zipPath"
Write-Host ""
Write-Host "Next: build NSIS installer"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1"
