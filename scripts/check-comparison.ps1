param(
    [Parameter(Mandatory = $true)]
    [string]$Baseline
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ResolvedBaseline = (Resolve-Path -LiteralPath $Baseline).Path
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
    if ($LASTEXITCODE -ne 0) { throw "Code acceptance failed." }
    & uv run --locked python -m scripts.check_comparison --baseline $ResolvedBaseline
    if ($LASTEXITCODE -ne 0) { throw "Week 2 step 1 acceptance failed." }
}
finally {
    Pop-Location
}
