param(
    [Parameter(Mandatory = $true)]
    [string]$Baseline,
    [Parameter(Mandatory = $true)]
    [string]$Packet,
    [ValidateRange(1, 65535)]
    [int]$OllamaPort = 11434,
    [switch]$AllowBackendChange
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ResolvedBaseline = (Resolve-Path -LiteralPath $Baseline).Path
$ResolvedPacket = (Resolve-Path -LiteralPath $Packet).Path
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
    if ($LASTEXITCODE -ne 0) { throw "Code acceptance failed." }

    $JudgeArguments = @("run", "--locked", "python", "-m", "evals.rejudge", "--baseline", $ResolvedBaseline, "--packet", $ResolvedPacket, "--ollama-port", "$OllamaPort")
    if ($AllowBackendChange) { $JudgeArguments += "--allow-backend-change" }
    & uv @JudgeArguments
    if ($LASTEXITCODE -ne 0) { throw "Frozen-answer judge acceptance failed." }
    Write-Host "WEEK 2 STEP 3 ACCEPTANCE PASSED"
}
finally {
    Pop-Location
}
