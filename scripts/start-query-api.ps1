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
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is required." }
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }
    $env:COPILOT_INDEX_MANIFEST = $ManifestPath
    & uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE -ne 0) { throw "Query API process failed." }
}
finally {
    Pop-Location
}
