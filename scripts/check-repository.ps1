param(
    [string]$Profile = ".\evals\datasets\kubesentiment\profile.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    & (Join-Path $PSScriptRoot "check.ps1")
    $ProfilePath = (Resolve-Path -LiteralPath $Profile).Path
    $Selected = Get-Content -LiteralPath $ProfilePath -Raw | ConvertFrom-Json
    $PointerPath = Join-Path $ProjectRoot "artifacts\repository-indexes\$($Selected.name).json"
    $Prepared = Get-Content -LiteralPath $PointerPath -Raw | ConvertFrom-Json
    & uv run --locked python -m evals.run --manifest $Prepared.index_manifest --profile $ProfilePath
    if ($LASTEXITCODE -ne 0) { throw "Repository baseline or trace acceptance failed." }
    Write-Host "REAL REPOSITORY ACCEPTANCE PASSED"
}
finally {
    Pop-Location
}
