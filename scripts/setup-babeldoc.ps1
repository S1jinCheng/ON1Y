param(
    [string]$Version = "0.6.4"
)

$ErrorActionPreference = "Stop"
$existing = Get-Command babeldoc -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "BabelDOC is already available at $($existing.Source)"
    & $existing.Source --version
    exit $LASTEXITCODE
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/ first."
}

& $uv.Source tool install --python 3.12 "BabelDOC==$Version"
if ($LASTEXITCODE -ne 0) {
    throw "BabelDOC installation failed with exit code $LASTEXITCODE"
}

$installed = Get-Command babeldoc -ErrorAction SilentlyContinue
if (-not $installed) {
    throw "BabelDOC was installed but is not on PATH. Restart On1y or configure its executable path in Papers settings."
}
& $installed.Source --version