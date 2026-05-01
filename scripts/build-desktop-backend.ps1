param(
    [string]$Python = "",
    [string]$OutputDir = "meetyou-ui\resources\desktop-backend",
    [switch]$SkipInstall,
    [string]$RuntimeConfigFile = "",
    [string]$RuntimeEnvFile = "",
    [switch]$IncludeLocalRuntimeConfig,
    [switch]$IncludeLocalEnv
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
    & $Python -m pip install -r requirements-desktop-client.txt
    & $Python -m pip install -r requirements-build-desktop.txt
}

& $Python scripts/generate_build_info.py

$ResolvedOutput = Join-Path $RepoRoot $OutputDir
$RuntimeTemplateDir = Join-Path $RepoRoot "meetyou-ui\resources\runtime-template"
$WorkPath = Join-Path $RepoRoot "build\pyinstaller-desktop-client"
$SpecPath = Join-Path $RepoRoot "packaging\desktop-client\desktop_client.spec"

if (Test-Path $ResolvedOutput) {
    Remove-Item -LiteralPath $ResolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ResolvedOutput | Out-Null

& $Python -m PyInstaller --noconfirm --clean --distpath $ResolvedOutput --workpath $WorkPath $SpecPath

$ExeName = if ($IsWindows -or $env:OS -eq "Windows_NT") { "desktop_client.exe" } else { "desktop_client" }
$ExePath = Join-Path $ResolvedOutput "desktop_client\$ExeName"
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

function Resolve-RepoPath {
    param([string] $Value)
    if (-not $Value) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }
    return (Join-Path $RepoRoot $Value)
}

function Test-LoopbackUrl {
    param([string] $Value)
    return $Value -match "^https?://(127\.0\.0\.1|localhost)(:\d+)?/?$"
}

function Get-ReleaseCoreBaseUrl {
    $Explicit = [string] $env:MEETYOU_DESKTOP_RELEASE_CORE_BASE_URL
    if ($Explicit.Trim()) {
        return $Explicit.Trim()
    }
    $Fallback = [string] $env:MEETYOU_CORE_BASE_URL
    if ($Fallback.Trim() -and -not (Test-LoopbackUrl $Fallback.Trim())) {
        return $Fallback.Trim()
    }
    return ""
}

$ExplicitRuntimeConfigFile = $RuntimeConfigFile
if (-not $ExplicitRuntimeConfigFile) {
    $ExplicitRuntimeConfigFile = [string] $env:MEETYOU_DESKTOP_RUNTIME_CONFIG_FILE
}

if ($ExplicitRuntimeConfigFile) {
    $DesktopConfigSource = Resolve-RepoPath $ExplicitRuntimeConfigFile
} elseif ($IncludeLocalRuntimeConfig -and (Test-Path (Join-Path $RepoRoot "user\desktop_client.json"))) {
    $DesktopConfigSource = Join-Path $RepoRoot "user\desktop_client.json"
} else {
    $DesktopConfigSource = Join-Path $RepoRoot "user\desktop_client.example.json"
}
if (-not (Test-Path $DesktopConfigSource)) {
    throw "Desktop runtime config template was not found: $DesktopConfigSource"
}
$DesktopConfig = Get-Content $DesktopConfigSource -Raw | ConvertFrom-Json
Set-JsonProperty -Object $DesktopConfig -Name "core_access_token" -Value ""
Set-JsonProperty -Object $DesktopConfig -Name "gateway_access_token" -Value ""
Set-JsonProperty -Object $DesktopConfig -Name "local_bridge_access_token" -Value ""
$ReleaseCoreBaseUrl = Get-ReleaseCoreBaseUrl
if ($ReleaseCoreBaseUrl -and -not (Test-LoopbackUrl $ReleaseCoreBaseUrl)) {
    Set-JsonProperty -Object $DesktopConfig -Name "core_base_url" -Value $ReleaseCoreBaseUrl.TrimEnd("/")
}
if (-not $DesktopConfig.local_bridge_host) {
    Set-JsonProperty -Object $DesktopConfig -Name "local_bridge_host" -Value "127.0.0.1"
}
if (-not $DesktopConfig.local_bridge_port) {
    Set-JsonProperty -Object $DesktopConfig -Name "local_bridge_port" -Value 38951
}
Write-Utf8NoBomFile `
    -Path (Join-Path $RuntimeUserDir "desktop_client.json") `
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
    "MEETYOU_CLIENT_ACCESS_TOKEN",
    "MEETYOU_CREDENTIAL_SECRET",
    "MEETYOU_CORE_BASE_URL"
)

$ExplicitRuntimeEnvFile = $RuntimeEnvFile
if (-not $ExplicitRuntimeEnvFile) {
    $ExplicitRuntimeEnvFile = [string] $env:MEETYOU_DESKTOP_RUNTIME_ENV_FILE
}
$RuntimeEnvSource = ""
if ($ExplicitRuntimeEnvFile) {
    $RuntimeEnvSource = Resolve-RepoPath $ExplicitRuntimeEnvFile
} elseif ($IncludeLocalEnv) {
    $RuntimeEnvSource = Join-Path $RepoRoot ".env"
}

$RuntimeEnvLines = @()
if ($RuntimeEnvSource) {
    if (-not (Test-Path $RuntimeEnvSource)) {
        throw "Desktop runtime env template was not found: $RuntimeEnvSource"
    }
    foreach ($Line in Get-Content $RuntimeEnvSource) {
        foreach ($Key in $RuntimeEnvKeys) {
            if ($Line -match ("^\s*" + [regex]::Escape($Key) + "\s*=")) {
                $RuntimeEnvLines += $Line
                break
            }
        }
    }
} elseif ($ReleaseCoreBaseUrl -and -not (Test-LoopbackUrl $ReleaseCoreBaseUrl)) {
    $RuntimeEnvLines += "MEETYOU_CORE_BASE_URL=$ReleaseCoreBaseUrl"
}

if ($RuntimeEnvLines.Count -gt 0) {
    Write-Utf8NoBomFile `
        -Path (Join-Path $RuntimeTemplateDir ".env") `
        -Content (($RuntimeEnvLines -join "`n") + "`n")
}

Write-Host "Desktop backend built: $ExePath"
Write-Host "Desktop runtime template prepared: $RuntimeTemplateDir"
Write-Host "Desktop runtime config template source: $DesktopConfigSource"
if ($RuntimeEnvSource) {
    Write-Host "Desktop runtime env template source: $RuntimeEnvSource"
} elseif ($RuntimeEnvLines.Count -gt 0) {
    Write-Host "Desktop runtime env template source: build environment"
} else {
    Write-Host "Desktop runtime env template source: none"
}
