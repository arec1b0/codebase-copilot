$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot

try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required. Install it before running this script."
    }

    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }

    & uv run --locked ruff check app ingestion indexing observability evals tests scripts
    if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed." }

    & uv run --locked ruff format --check app ingestion indexing observability evals tests scripts
    if ($LASTEXITCODE -ne 0) { throw "Ruff formatting failed." }

    & uv run --locked mypy
    if ($LASTEXITCODE -ne 0) { throw "Mypy failed." }

    & uv run --locked pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Pytest failed." }

    Write-Host "CODE ACCEPTANCE PASSED"
}
finally {
    Pop-Location
}
