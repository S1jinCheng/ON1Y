# Register On1y to start on Windows login (L2).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\lib\on1y-windows.ps1"

$root = Get-On1yRoot
$desktopExe = Get-On1yDesktopExe
$startScript = Join-Path $root "scripts\start-on1y.cmd"
$taskName = "On1y"

if ($desktopExe) {
    $action = New-ScheduledTaskAction `
        -Execute $desktopExe `
        -Argument "--autostart" `
        -WorkingDirectory $root
    $description = "Start On1y desktop app on login (tray; window if enabled in settings)."
}
else {
    $action = New-ScheduledTaskAction `
        -Execute $startScript `
        -Argument "-Quiet" `
        -WorkingDirectory $root
    $description = "Start On1y backend and frontend on login (opens browser if enabled in settings)."
}

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description $description `
    -Force | Out-Null

Write-Host "Autostart installed (task: $taskName)."
if ($desktopExe) {
    Write-Host "  On login: On1y desktop app (tray + optional window)."
    Write-Host "  Target: $desktopExe --autostart"
}
else {
    Write-Host "  On login: backend + frontend (browser mode)."
    Write-Host "  Build desktop app for native window: scripts\build-desktop.ps1"
}
Write-Host "  Window on login follows Settings -> General -> Open browser on start."
Write-Host ""
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File scripts\uninstall-on1y-autostart.ps1"
