param(
    [Parameter(Mandatory = $true)]
    [string]$Corpus
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot

try {
    $CorpusPath = (Resolve-Path $Corpus).Path
    if (-not (Test-Path (Join-Path $CorpusPath "manifest.json"))) {
        throw "Corpus manifest is missing. Run Step 3 acceptance first."
    }
    & (Join-Path $PSScriptRoot "check.ps1")
    & uv run --locked python -m scripts.check_retrieval --corpus $CorpusPath
    if ($LASTEXITCODE -ne 0) { throw "Step 4 acceptance failed." }
}
finally {
    Pop-Location
}
