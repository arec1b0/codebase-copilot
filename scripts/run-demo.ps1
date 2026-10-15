$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    foreach ($Command in @("uv", "git", "docker", "ollama")) {
        if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
            throw "$Command is required; install the prerequisites in README.md."
        }
    }
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }
    & (Join-Path $PSScriptRoot "infra.ps1") -Action up
    try {
        $Tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    }
    catch {
        throw "Start Ollama from the Start menu or run ollama serve, then retry."
    }
    if (-not ($Tags.models | Where-Object { $_.name -eq "qwen2.5-coder:3b" })) {
        & ollama pull qwen2.5-coder:3b
        if ($LASTEXITCODE -ne 0) { throw "Model download failed." }
    }
    & uv run --locked python -m scripts.prepare_demo
    if ($LASTEXITCODE -ne 0) { throw "Demo preparation failed." }
    $Prepared = Get-Content -LiteralPath (Join-Path $ProjectRoot "artifacts\demo-index.json") -Raw | ConvertFrom-Json
    $ManifestPath = $Prepared.index_manifest
    Write-Host "Demo manifest: $ManifestPath"
    Write-Host "API documentation: http://127.0.0.1:8000/docs"
    & (Join-Path $PSScriptRoot "start-query-api.ps1") -IndexManifest "$ManifestPath"
}
finally {
    Pop-Location
}
