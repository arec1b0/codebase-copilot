$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is required." }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is required." }
    & (Join-Path $PSScriptRoot "check.ps1")
    & uv run --locked python -m scripts.check_ingestion
    if ($LASTEXITCODE -ne 0) { throw "Step 3 acceptance failed." }
}
finally {
    Pop-Location
}
