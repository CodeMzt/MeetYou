param(
    [ValidateSet("start", "check", "help")]
    [string]$Mode = "start",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$SkipService,
    [switch]$SkipDesktopAgent,
    [switch]$SkipUi
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$MainPy = Join-Path $RepoRoot "main.py"
$UiDir = Join-Path $RepoRoot "meetyou-ui"
$DesktopAgentConfig = Join-Path $RepoRoot "user\desktop_agent.json"
$UserConfig = Join-Path $RepoRoot "user\config.json"
$DotEnvPath = Join-Path $RepoRoot ".env"

function Write-Section([string]$Text) {
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Write-Ok([string]$Text) {
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warn([string]$Text) {
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}

function Write-Fail([string]$Text) {
    Write-Host "[FAIL] $Text" -ForegroundColor Red
}

function Import-DotEnv {
    if (-not (Test-Path $DotEnvPath)) {
        return
    }
    Get-Content $DotEnvPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            return
        }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (-not $name) {
            return
        }
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

function Get-DesktopBackendBaseUrl {
    $host = if ($env:MEETYOU_DESKTOP_LOCAL_HOST) { $env:MEETYOU_DESKTOP_LOCAL_HOST } else { "127.0.0.1" }
    $port = if ($env:MEETYOU_DESKTOP_LOCAL_PORT) { $env:MEETYOU_DESKTOP_LOCAL_PORT } else { "38951" }
    if (Test-Path $DesktopAgentConfig) {
        try {
            $payload = Get-Content $DesktopAgentConfig -Raw | ConvertFrom-Json
            if ($payload.local_bridge_host) {
                $host = [string]$payload.local_bridge_host
            }
            if ($payload.local_bridge_port) {
                $port = [string]$payload.local_bridge_port
            }
        } catch {
        }
    }
    return "http://$host`:$port"
}

function Wait-Health([int]$TimeoutSeconds = 60) {
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

function Start-ComponentWindow([string]$Title, [string]$WorkingDirectory, [string]$CommandText) {
    $wrapped = "title $Title && cd /d `"$WorkingDirectory`" && $CommandText"
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", $wrapped) -WorkingDirectory $WorkingDirectory | Out-Null
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
    Write-Host "  -SkipDesktopAgent"
    Write-Host "  -SkipUi"
    Write-Host ""
    Write-Host "Notes:"
    Write-Host "  - 对于非 Core 改动，优先让桌面端直接连接已运行的远程 Core："
    Write-Host "    scripts\manual-acceptance.cmd check -BaseUrl https://your-remote-core.example"
    Write-Host "  - scripts\manual-acceptance.cmd start 主要用于仓库内全链路本地联调，会尝试在本机拉起 service"
}

function Validate-Environment {
    Write-Section "Environment"
    Import-DotEnv

    if (-not (Test-Path $PythonExe)) {
        throw "Python virtual environment not found: $PythonExe"
    }
    Write-Ok ".venv found"

    if (-not (Test-Path $MainPy)) {
        throw "main.py not found: $MainPy"
    }
    Write-Ok "main entry found"

    if (-not (Test-Path $UiDir)) {
        throw "meetyou-ui directory not found: $UiDir"
    }
    Write-Ok "frontend directory found"

    if (-not (Test-Path $UserConfig)) {
        Write-Warn "user\config.json not found; service may fail to start"
    } else {
        Write-Ok "user\config.json found"
    }

    if (-not (Test-Path $DesktopAgentConfig)) {
        Write-Warn "user\desktop_agent.json not found; desktop-agent may fail to start"
    } else {
        Write-Ok "user\desktop_agent.json found"
    }
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
        $serviceCommand = '"' + $PythonExe + '" "' + $MainPy + '" service'
        Start-ComponentWindow -Title "MeetYou Service" -WorkingDirectory $RepoRoot -CommandText $serviceCommand
        if ($(Wait-Health)) {
            Write-Ok "service health check passed"
        } else {
            Write-Fail "service health check timed out; inspect service window"
            return 1
        }
    }

    if (-not $SkipDesktopAgent -and $SkipUi) {
        Write-Section "Start desktop-agent"
        $agentCommand = '"' + $PythonExe + '" "' + $MainPy + '" desktop-agent'
        Start-ComponentWindow -Title "MeetYou Desktop Agent" -WorkingDirectory $RepoRoot -CommandText $agentCommand
        Write-Ok "desktop-agent launched; use check mode to confirm online state"
    } elseif (-not $SkipDesktopAgent) {
        Write-Section "Desktop backend"
        Write-Ok "desktop backend will be launched by Electron UI"
    } else {
        Write-Warn "desktop-agent start skipped"
    }

    if (-not $SkipUi) {
        Write-Section "Start Electron / Vite"
        Start-ComponentWindow -Title "MeetYou UI" -WorkingDirectory $UiDir -CommandText "npm run dev"
        Write-Ok "UI window launched"
    } else {
        Write-Warn "UI start skipped"
    }

    Write-Section "Next steps"
    Write-Host "1. Wait 10-20 seconds for desktop backend / Electron to connect"
    Write-Host "2. Run: scripts\manual-acceptance.cmd check"
    Write-Host "3. Follow docs\v3\operations\desktop-unified-acceptance.md"
    return 0
}

function Run-ManualAcceptanceCheck {
    Validate-Environment
    Write-Section "API checks"

    $failed = $false

    try {
        $health = Invoke-JsonGet "/health"
        Write-Ok "/health ok"
    } catch {
        Write-Fail "/health failed: $($_.Exception.Message)"
        return 1
    }

    try {
        $desktopStatus = Invoke-RestMethod -Uri ((Get-DesktopBackendBaseUrl) + "/desktop/status") -Method Get -TimeoutSec 5
        Write-Ok ("/desktop/status ok, api_prefix: {0}" -f $desktopStatus.api_prefix)
    } catch {
        Write-Warn "/desktop/status not reachable yet (this is expected before Electron starts desktop backend)"
    }

    try {
        $workspaces = @(Invoke-JsonGet "/client/workspaces")
        Write-Ok ("/client/workspaces ok, count: {0}" -f $workspaces.Count)
        if ($workspaces.Count -gt 0) {
            Write-Host ("  workspaces: " + (($workspaces | ForEach-Object { $_.workspace_id }) -join ", "))
        }
    } catch {
        Write-Fail "/client/workspaces failed: $($_.Exception.Message)"
        $failed = $true
    }

    try {
        $procedures = @(Invoke-JsonGet "/client/procedures")
        Write-Ok ("/client/procedures ok, count: {0}" -f $procedures.Count)
        if ($procedures.Count -gt 0) {
            Write-Host ("  procedures: " + (($procedures | Select-Object -First 6 | ForEach-Object { $_.procedure_id }) -join ", "))
        }
    } catch {
        Write-Fail "/client/procedures failed: $($_.Exception.Message)"
        $failed = $true
    }

    try {
        $agents = @(Invoke-JsonGet "/operator/agents")
        $onlineAgents = @($agents | Where-Object { $_.status -eq "online" })
        Write-Ok ("/operator/agents ok, total: {0}, online: {1}" -f $agents.Count, $onlineAgents.Count)
        if ($agents.Count -gt 0) {
            foreach ($agent in $agents) {
                Write-Host ("  - {0} [{1}] status={2} workspaces={3}" -f $agent.agent_id, $agent.agent_type, $agent.status, (($agent.workspace_ids | ForEach-Object { $_ }) -join ","))
            }
        }
    } catch {
        Write-Fail "/operator/agents failed: $($_.Exception.Message)"
        $failed = $true
    }

    if ($failed) {
        Write-Warn "At least one check failed. See docs\v3\operations\desktop-unified-acceptance.md"
        return 1
    }

    Write-Section "Done"
    Write-Host "API checks passed. Next, follow docs\v3\operations\desktop-unified-acceptance.md for UI / procedure / operation validation."
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
