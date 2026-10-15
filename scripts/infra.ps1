param(
    [ValidateSet("up", "check", "status", "down")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is required. Install it and enable Linux containers."
    }
    $ContainerOS = & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw "Docker daemon is not available. Start Docker Desktop." }
    if ($ContainerOS -ne "linux") { throw "Docker Desktop must use Linux containers." }

    $ComposeArguments = @(
        "compose",
        "--project-directory", $ProjectRoot,
        "--env-file", (Join-Path $ProjectRoot ".env"),
        "-f", (Join-Path $ProjectRoot "deploy\compose.yaml")
    )

    if ($Action -eq "up" -or $Action -eq "check") {
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv is required." }
        & uv run --locked python scripts\init_env.py
        if ($LASTEXITCODE -ne 0) { throw "Local environment initialization failed." }
    }

    if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
        throw ".env is missing. Run this script with -Action up first."
    }
    & docker @ComposeArguments config --quiet
    if ($LASTEXITCODE -ne 0) { throw "Compose configuration is invalid." }

    switch ($Action) {
        "up" {
            & docker @ComposeArguments pull
            if ($LASTEXITCODE -ne 0) { throw "Image download failed." }
            & docker @ComposeArguments up -d --wait --wait-timeout 180
            if ($LASTEXITCODE -ne 0) { throw "Infrastructure startup failed." }
            & uv run --locked python scripts\check_infra.py
            if ($LASTEXITCODE -ne 0) { throw "Step 2 acceptance failed." }
        }
        "check" {
            & uv run --locked python scripts\check_infra.py
            if ($LASTEXITCODE -ne 0) { throw "Step 2 acceptance failed." }
        }
        "status" {
            & docker @ComposeArguments ps
            if ($LASTEXITCODE -ne 0) { throw "Could not inspect infrastructure." }
        }
        "down" {
            & docker @ComposeArguments down
            if ($LASTEXITCODE -ne 0) { throw "Infrastructure shutdown failed." }
            Write-Host "Infrastructure stopped. Named volumes preserved."
        }
    }
}
finally {
    Pop-Location
}
