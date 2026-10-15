param(
    [Parameter(Mandatory = $true)]
    [string]$IndexManifest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    $ManifestPath = (Resolve-Path $IndexManifest).Path
    & (Join-Path $PSScriptRoot "check.ps1")
    & uv run --locked python -m scripts.check_query
    if ($LASTEXITCODE -ne 0) { throw "Generation acceptance failed." }
    & uv run --locked python -m evals.run --manifest $ManifestPath
    if ($LASTEXITCODE -ne 0) { throw "Baseline or Phoenix trace acceptance failed." }
    Write-Host "STEP 6 ACCEPTANCE PASSED"
}
finally {
    Pop-Location
}
