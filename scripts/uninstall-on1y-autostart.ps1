# Remove On1y login autostart task.
$ErrorActionPreference = "Stop"

$taskName = "On1y"
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Autostart task '$taskName' is not installed."
    exit 0
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Removed autostart task '$taskName'."
