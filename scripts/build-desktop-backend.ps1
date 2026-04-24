param(
    [string]$Python = "",
    [string]$OutputDir = "meetyou-ui\resources\desktop-backend",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if (-not $Python) {
    $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $Python = $VenvPython
    } else {
        $Python = "python"
    }
}

if (-not $SkipInstall) {
    & $Python -m pip install -r requirements-desktop-agent.txt
    & $Python -m pip install -r requirements-build-desktop.txt
}

& $Python scripts/generate_build_info.py

$ResolvedOutput = Join-Path $RepoRoot $OutputDir
$RuntimeTemplateDir = Join-Path $RepoRoot "meetyou-ui\resources\runtime-template"
$WorkPath = Join-Path $RepoRoot "build\pyinstaller-desktop-agent"
$SpecPath = Join-Path $RepoRoot "packaging\desktop-agent\desktop_agent.spec"

if (Test-Path $ResolvedOutput) {
    Remove-Item -LiteralPath $ResolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ResolvedOutput | Out-Null

& $Python -m PyInstaller --noconfirm --clean --distpath $ResolvedOutput --workpath $WorkPath $SpecPath

$ExeName = if ($IsWindows -or $env:OS -eq "Windows_NT") { "desktop_agent.exe" } else { "desktop_agent" }
$ExePath = Join-Path $ResolvedOutput "desktop_agent\$ExeName"
if (-not (Test-Path $ExePath)) {
    throw "Desktop backend executable was not produced: $ExePath"
}

if (Test-Path $RuntimeTemplateDir) {
    Remove-Item -LiteralPath $RuntimeTemplateDir -Recurse -Force
}
$RuntimeUserDir = Join-Path $RuntimeTemplateDir "user"
New-Item -ItemType Directory -Force -Path $RuntimeUserDir | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $RuntimeTemplateDir ".gitkeep") | Out-Null

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)] $Object,
        [Parameter(Mandatory = $true)] [string] $Name,
        [AllowNull()] $Value
    )
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [Parameter(Mandatory = $true)] [string] $Content
    )
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

$DesktopConfigSource = Join-Path $RepoRoot "user\desktop_agent.json"
if (-not (Test-Path $DesktopConfigSource)) {
    $DesktopConfigSource = Join-Path $RepoRoot "user\desktop_agent.example.json"
}
$DesktopConfig = Get-Content $DesktopConfigSource -Raw | ConvertFrom-Json
Set-JsonProperty -Object $DesktopConfig -Name "agent_access_token" -Value ""
Set-JsonProperty -Object $DesktopConfig -Name "gateway_access_token" -Value ""
Set-JsonProperty -Object $DesktopConfig -Name "local_bridge_access_token" -Value ""
if (-not $DesktopConfig.local_bridge_host) {
    Set-JsonProperty -Object $DesktopConfig -Name "local_bridge_host" -Value "127.0.0.1"
}
if (-not $DesktopConfig.local_bridge_port) {
    Set-JsonProperty -Object $DesktopConfig -Name "local_bridge_port" -Value 38951
}
Write-Utf8NoBomFile `
    -Path (Join-Path $RuntimeUserDir "desktop_agent.json") `
    -Content (($DesktopConfig | ConvertTo-Json -Depth 12) + "`n")

$CmdPolicySource = Join-Path $RepoRoot "user\cmd_policy.example.json"
if (Test-Path $CmdPolicySource) {
    Copy-Item -LiteralPath $CmdPolicySource -Destination (Join-Path $RuntimeUserDir "cmd_policy.json") -Force
}
$McpServersSource = Join-Path $RepoRoot "user\mcp_servers.example.json"
if (Test-Path $McpServersSource) {
    Copy-Item -LiteralPath $McpServersSource -Destination (Join-Path $RuntimeUserDir "mcp_servers.json") -Force
}

$RuntimeEnvKeys = @(
    "MEETYOU_GATEWAY_ACCESS_TOKEN",
    "MEETYOU_AGENT_WS_ACCESS_TOKEN",
    "MEETYOU_AGENT_ACCESS_TOKEN",
    "MEETYOU_CREDENTIAL_SECRET",
    "MEETYOU_AGENT_BASE_URL",
    "MEETYOU_CORE_BASE_URL"
)
$RuntimeEnvSource = Join-Path $RepoRoot ".env"
if (Test-Path $RuntimeEnvSource) {
    $RuntimeEnvLines = @()
    foreach ($Line in Get-Content $RuntimeEnvSource) {
        foreach ($Key in $RuntimeEnvKeys) {
            if ($Line -match ("^\s*" + [regex]::Escape($Key) + "\s*=")) {
                $RuntimeEnvLines += $Line
                break
            }
        }
    }
    if ($RuntimeEnvLines.Count -gt 0) {
        Write-Utf8NoBomFile `
            -Path (Join-Path $RuntimeTemplateDir ".env") `
            -Content (($RuntimeEnvLines -join "`n") + "`n")
    }
}

Write-Host "Desktop backend built: $ExePath"
Write-Host "Desktop runtime template prepared: $RuntimeTemplateDir"
