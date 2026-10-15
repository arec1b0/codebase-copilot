$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot

try {
    & (Join-Path $PSScriptRoot "check.ps1")
    & uv run --locked python -m scripts.check_query
    if ($LASTEXITCODE -ne 0) { throw "Step 5 acceptance failed." }
}
finally {
    Pop-Location
}
