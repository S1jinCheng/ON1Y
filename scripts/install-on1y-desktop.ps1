# Create a desktop shortcut to start On1y (L1).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
$desktopExe = Get-On1yDesktopExe
$startScript = Join-Path $root "scripts\start-on1y.cmd"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "On1y.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)

if ($desktopExe) {
    $shortcut.TargetPath = $desktopExe
    $shortcut.Arguments = ""
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = "On1y knowledge workspace (desktop app)"
}
else {
    $shortcut.TargetPath = $startScript
    $shortcut.Arguments = ""
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = "Start On1y knowledge workspace"
}

$shortcut.WindowStyle = 1

$iconPath = Join-Path $root "assets\only.ico"
if (-not (Test-Path $iconPath)) {
    $iconPath = Join-Path $root "desktop\src-tauri\icons\icon.ico"
}
if (-not (Test-Path $iconPath)) {
    $iconPath = Join-Path $root "assets\on1y.ico"
}
if (-not (Test-Path $iconPath)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source (Join-Path $root "scripts\prepare-tauri-icons.py")
        $iconPath = Join-Path $root "desktop\src-tauri\icons\icon.ico"
    }
}
if (Test-Path $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}

$shortcut.Save()

Write-Host "Desktop shortcut created:"
Write-Host "  $shortcutPath"
if ($desktopExe) {
    Write-Host "  Target: $desktopExe"
}
else {
    Write-Host "  Target: $startScript (browser mode)"
    Write-Host ""
    Write-Host "Build the desktop app first:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1"
}
Write-Host ""
Write-Host "Double-click On1y on your desktop to start the app."
