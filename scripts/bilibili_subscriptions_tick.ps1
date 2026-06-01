# Daily Bilibili subscription sync + ingest (Windows Task Scheduler).
# Usage: powershell -File scripts\bilibili_subscriptions_tick.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

conda activate on1y
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to activate conda env on1y"
}

$ingest = if ($env:ON1Y_BILIBILI_SYNC_INGEST_LIMIT) { $env:ON1Y_BILIBILI_SYNC_INGEST_LIMIT } else { 10 }
$subs = if ($env:ON1Y_BILIBILI_SYNC_SUBTITLE_LIMIT) { $env:ON1Y_BILIBILI_SYNC_SUBTITLE_LIMIT } else { 10 }
$distill = if ($env:ON1Y_BILIBILI_SYNC_DISTILL_LIMIT) { $env:ON1Y_BILIBILI_SYNC_DISTILL_LIMIT } else { 10 }

on1y subscriptions --platform all --ingest `
    --ingest-limit $ingest `
    --subtitle-limit $subs `
    --distill-limit $distill
