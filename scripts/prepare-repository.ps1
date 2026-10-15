param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [string]$Profile = ".\evals\datasets\kubesentiment\profile.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RepositoryPath = (Resolve-Path -LiteralPath $Repository).Path
Push-Location $ProjectRoot
try {
    $ProfilePath = (Resolve-Path -LiteralPath $Profile).Path
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }
    & uv run --locked python -m scripts.prepare_repository --repository $RepositoryPath --profile $ProfilePath
    if ($LASTEXITCODE -ne 0) { throw "Repository preparation failed." }
}
finally {
    Pop-Location
}
