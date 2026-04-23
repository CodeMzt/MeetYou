param(
    [ValidateSet("prepare", "start", "check", "logs", "stop")]
    [string]$Action = "check"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $RepoRoot "deploy/docker/compose.core-postgres.yml"
$ComposeEnv = Join-Path $RepoRoot "deploy/docker/compose.env"
$Python = Join-Path $RepoRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

switch ($Action) {
    "prepare" {
        & $Python (Join-Path $RepoRoot "scripts/prepare_core_runtime.py") --profile docker --output-root deploy/docker/runtime
    }
    "start" {
        docker compose --env-file $ComposeEnv -f $ComposeFile up -d --build
    }
    "check" {
        & $Python (Join-Path $RepoRoot "scripts/check_core_runtime.py") --profile docker --runtime-root deploy/docker/runtime
        docker compose --env-file $ComposeEnv -f $ComposeFile ps
    }
    "logs" {
        docker compose --env-file $ComposeEnv -f $ComposeFile logs --tail 120
    }
    "stop" {
        docker compose --env-file $ComposeEnv -f $ComposeFile stop
    }
}
