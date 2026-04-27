param(
    [ValidateSet("start", "check", "help")]
    [string]$Mode = "start",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$SkipService,
    [switch]$SkipDesktopClient,
    [switch]$SkipUi
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$MainPy = Join-Path $RepoRoot "main.py"
$UiDir = Join-Path $RepoRoot "meetyou-ui"
$DesktopClientConfig = Join-Path $RepoRoot "user\desktop_client.json"
$UserConfig = Join-Path $RepoRoot "user\config.json"
$DotEnvPath = Join-Path $RepoRoot ".env"

function Write-Section([string]$Text) { Write-Host "`n== $Text ==" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[OK] $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "[WARN] $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) { Write-Host "[FAIL] $Text" -ForegroundColor Red }

function Import-DotEnv {
    if (-not (Test-Path $DotEnvPath)) { return }
    Get-Content $DotEnvPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $parts = $line -split "=", 2
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (-not $name) { return }
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Get-AuthHeaders {
    $headers = @{}
    if ($env:MEETYOU_GATEWAY_ACCESS_TOKEN) {
        $headers["Authorization"] = "Bearer $($env:MEETYOU_GATEWAY_ACCESS_TOKEN)"
    }
    return $headers
}

function Invoke-JsonGet([string]$Path) {
    $headers = Get-AuthHeaders
    return Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + $Path) -Method Get -Headers $headers -TimeoutSec 8
}

function As-List($Payload) {
    if ($null -eq $Payload) { return @() }
    if ($Payload.PSObject.Properties.Name -contains "value") { return @($Payload.value) }
    return @($Payload)
}

function Get-DesktopBackendBaseUrl {
    $hostName = if ($env:MEETYOU_DESKTOP_LOCAL_HOST) { $env:MEETYOU_DESKTOP_LOCAL_HOST } else { "127.0.0.1" }
    $port = if ($env:MEETYOU_DESKTOP_LOCAL_PORT) { $env:MEETYOU_DESKTOP_LOCAL_PORT } else { "38951" }
    if (Test-Path $DesktopClientConfig) {
        try {
            $payload = Get-Content $DesktopClientConfig -Raw | ConvertFrom-Json
            if ($payload.local_bridge_host) { $hostName = [string]$payload.local_bridge_host }
            if ($payload.local_bridge_port) { $port = [string]$payload.local_bridge_port }
        } catch {
        }
    }
    return "http://$hostName`:$port"
}

function Wait-Health([int]$TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $null = Invoke-JsonGet "/health"
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Start-ComponentProcess([string]$WorkingDirectory, [string]$CommandText) {
    $wrapped = "cd /d `"$WorkingDirectory`" && $CommandText"
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $wrapped) -WorkingDirectory $WorkingDirectory -WindowStyle Hidden | Out-Null
}

function Show-Help {
    Write-Host "Usage:"
    Write-Host "  scripts\manual-acceptance.cmd start"
    Write-Host "  scripts\manual-acceptance.cmd check"
    Write-Host "  scripts\manual-acceptance.cmd help"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -BaseUrl http://127.0.0.1:8000"
    Write-Host "  -SkipService"
    Write-Host "  -SkipDesktopClient"
    Write-Host "  -SkipUi"
    Write-Host ""
    Write-Host "Notes:"
    Write-Host "  - For remote Core checks, keep Core running and point BaseUrl at the remote service."
    Write-Host "    scripts\manual-acceptance.cmd check -BaseUrl https://your-remote-core.example"
    Write-Host "  - scripts\manual-acceptance.cmd start launches the local service and UI stack."
}

function Validate-Environment {
    Write-Section "Environment"
    Import-DotEnv
    $env:MEETYOU_CORE_BASE_URL = $BaseUrl.TrimEnd("/")
    if ($env:MEETYOU_GATEWAY_ACCESS_TOKEN -and -not $env:MEETYOU_CLIENT_ACCESS_TOKEN) {
        $env:MEETYOU_CLIENT_ACCESS_TOKEN = $env:MEETYOU_GATEWAY_ACCESS_TOKEN
    }
    Write-Ok "Core base URL: $env:MEETYOU_CORE_BASE_URL"
    if (-not (Test-Path $PythonExe)) { throw "Python virtual environment not found: $PythonExe" }
    if (-not (Test-Path $MainPy)) { throw "main.py not found: $MainPy" }
    if (-not (Test-Path $UiDir)) { throw "frontend directory not found: $UiDir" }
    if (-not (Test-Path $UserConfig)) { Write-Warn "user\config.json not found; service may fail to start" } else { Write-Ok "user\config.json found" }
    if (-not (Test-Path $DesktopClientConfig)) { Write-Warn "user\desktop_client.json not found; desktop provider may fail to start" } else { Write-Ok "user\desktop_client.json found" }
}

function Start-ManualAcceptanceStack {
    Validate-Environment
    Write-Section "Start service"
    $serviceHealthy = $false
    try {
        $null = Invoke-JsonGet "/health"
        $serviceHealthy = $true
        Write-Ok "service already running"
    } catch {
        $serviceHealthy = $false
    }

    if ($SkipService) {
        Write-Warn "service start skipped"
    } elseif (-not $serviceHealthy) {
        Start-ComponentProcess -WorkingDirectory $RepoRoot -CommandText ('"' + $PythonExe + '" "' + $MainPy + '" service')
        if (Wait-Health) { Write-Ok "service health check passed" } else { Write-Fail "service health check timed out"; return 1 }
    }

    if (-not $SkipDesktopClient -and $SkipUi) {
        Write-Section "Start desktop provider"
        Start-ComponentProcess -WorkingDirectory $RepoRoot -CommandText ('"' + $PythonExe + '" "' + $MainPy + '" desktop-client')
        Write-Ok "desktop provider launched"
    } elseif (-not $SkipDesktopClient) {
        Write-Section "Desktop backend"
        Write-Ok "desktop backend will be launched by Electron UI"
    } else {
        Write-Warn "desktop provider start skipped"
    }

    if (-not $SkipUi) {
        Write-Section "Start UI"
        Start-ComponentProcess -WorkingDirectory $UiDir -CommandText "npm run dev"
        Write-Ok "UI process launched"
    } else {
        Write-Warn "UI start skipped"
    }

    Write-Section "Next steps"
    Write-Host "1. Wait 10-20 seconds for endpoint providers to connect."
    Write-Host "2. Run: scripts\manual-acceptance.cmd check"
    Write-Host "3. Record the V4 checks in docs\v4\test-report.md"
    return 0
}

function Run-ManualAcceptanceCheck {
    Validate-Environment
    Write-Section "API checks"
    $failed = $false

    try {
        $null = Invoke-JsonGet "/health"
        Write-Ok "/health ok"
    } catch {
        Write-Fail "/health failed: $($_.Exception.Message)"
        return 1
    }

    try {
        $desktopStatus = Invoke-RestMethod -Uri ((Get-DesktopBackendBaseUrl) + "/desktop/status") -Method Get -TimeoutSec 5
        Write-Ok ("/desktop/status ok, api_prefix: {0}" -f $desktopStatus.api_prefix)
    } catch {
        Write-Warn "/desktop/status not reachable yet"
    }

    try {
        $workspaces = As-List (Invoke-JsonGet "/client/workspaces")
        Write-Ok ("/client/workspaces ok, count: {0}" -f $workspaces.Count)
    } catch {
        Write-Fail "/client/workspaces failed: $($_.Exception.Message)"
        $failed = $true
    }

    try {
        $operatorWorkspaces = As-List (Invoke-JsonGet "/operator/workspaces")
        Write-Ok ("/operator/workspaces ok, count: {0}" -f $operatorWorkspaces.Count)
    } catch {
        Write-Fail "/operator/workspaces failed: $($_.Exception.Message)"
        $failed = $true
    }

    try {
        $endpoints = As-List (Invoke-JsonGet "/operator/endpoints")
        $connectedEndpoints = @($endpoints | Where-Object { $_.connected -eq $true })
        Write-Ok ("/operator/endpoints ok, total: {0}, connected: {1}" -f $endpoints.Count, $connectedEndpoints.Count)
        foreach ($endpoint in $endpoints) {
            Write-Host ("  - {0} [{1}] status={2} connections={3} workspaces={4}" -f $endpoint.endpoint_id, $endpoint.provider_type, $endpoint.status, $endpoint.connection_count, (($endpoint.workspace_ids | ForEach-Object { $_ }) -join ","))
        }
    } catch {
        Write-Fail "/operator/endpoints failed: $($_.Exception.Message)"
        $failed = $true
    }

    if ($failed) {
        Write-Warn "At least one check failed. Keep fixing and record the V4 result in docs\v4\test-report.md"
        return 1
    }

    Write-Section "Done"
    Write-Host "API checks passed. Next, validate UI / procedure / operation flows and record docs\v4\test-report.md."
    return 0
}

switch ($Mode) {
    "help" {
        Show-Help
        exit 0
    }
    "start" {
        exit $(Start-ManualAcceptanceStack)
    }
    "check" {
        exit $(Run-ManualAcceptanceCheck)
    }
}
