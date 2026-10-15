param(
    [string]$Repository = "",
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ($Repository) { $Repository = [System.IO.Path]::GetFullPath($Repository) }
Push-Location $ProjectRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is required." }
    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }
    $Arguments = @("run", "--locked", "python", "-m", "scripts.run_repository")
    if ($Repository) { $Arguments += @("--repository", $Repository) }
    if ($CheckOnly) { $Arguments += "--check-only" }
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Repository launcher failed." }
}
finally {
    Pop-Location
}
