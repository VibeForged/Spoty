param(
    [string]$AppVersion = "1.0.0",
    [string]$JreDir = $env:SPOTY_JRE_DIR,
    [string]$FfmpegDir = $env:SPOTY_FFMPEG_DIR,
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistDir = Join-Path $Root "dist"
$BuildDir = Join-Path $Root "build"
$ReleaseDir = Join-Path $Root "release\windows"
$AppDir = Join-Path $DistDir "SpotyDiscordBot"

function Stop-AppDirProcesses {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetDir
    )

    $ResolvedTarget = (Resolve-Path -LiteralPath $TargetDir -ErrorAction SilentlyContinue)
    if (-not $ResolvedTarget) {
        return
    }

    $TargetPrefix = $ResolvedTarget.Path.ToLowerInvariant()
    $ProcessNames = @("SpotyDiscordBot", "java")

    foreach ($Name in $ProcessNames) {
        $Candidates = Get-Process -Name $Name -ErrorAction SilentlyContinue
        foreach ($Proc in $Candidates) {
            try {
                $ExePath = $Proc.Path
                if (-not $ExePath) {
                    continue
                }
                $ExePathLower = $ExePath.ToLowerInvariant()
                if ($ExePathLower.StartsWith($TargetPrefix)) {
                    Stop-Process -Id $Proc.Id -Force -ErrorAction Stop
                }
            } catch {
                # Ignore access/path lookup failures and continue cleanup attempts.
            }
        }
    }
}

if (-not $JreDir) {
    $JreDir = "C:\Program Files\Microsoft\jdk-17.0.18.8-hotspot"
    # throw "Set SPOTY_JRE_DIR or pass -JreDir with a Windows JRE directory."
}
if (-not $FfmpegDir) {
    $FfmpegDir = "C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg"
    # throw "Set SPOTY_FFMPEG_DIR or pass -FfmpegDir with a Windows FFmpeg directory."
}

function Copy-Runtime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Target,
        [Parameter(Mandatory = $true)]
        [string]$ExecutableName
    )

    $ResolvedSource = Resolve-Path $Source
    $SourceItem = Get-Item $ResolvedSource

    if ($SourceItem.PSIsContainer) {
        Copy-Item -Recurse -Force $SourceItem.FullName $Target
        return
    }

    $BinDir = Join-Path $Target "bin"
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    Copy-Item -Force $SourceItem.FullName (Join-Path $BinDir $ExecutableName)
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

python -m pip install --upgrade pip
python -m pip install -r (Join-Path $Root "requirements.txt")
python -m pip install pyinstaller ruff pytest pytest-asyncio

if (-not $SkipTests) {
    python -m ruff check $Root
    python -m pytest --tb=short
}

if (Test-Path $AppDir) {
    Stop-AppDirProcesses -TargetDir $AppDir
    Start-Sleep -Milliseconds 500
    try {
        Remove-Item -Recurse -Force $AppDir -ErrorAction Stop
    } catch {
        throw "Could not remove '$AppDir'. Close any running SpotyDiscordBot or Java processes using this folder, then retry. Original error: $($_.Exception.Message)"
    }
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name SpotyDiscordBot `
    --collect-submodules core `
    --collect-submodules cogs `
    --hidden-import aiosqlite `
    --hidden-import logging.config `
    --add-data "$Root\.env.example;." `
    --add-data "$Root\LavaLink;Lavalink" `
    --add-data "$Root\migrations;migrations" `
    --add-data "$Root\alembic.ini;." `
    (Join-Path $Root "launcher.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE. Please check the logs."
}

$RuntimeDir = Join-Path $AppDir "runtime"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
Copy-Runtime -Source $JreDir -Target (Join-Path $RuntimeDir "jre") -ExecutableName "java.exe"
Copy-Runtime -Source $FfmpegDir -Target (Join-Path $RuntimeDir "ffmpeg") -ExecutableName "ffmpeg.exe"

$Version = @{
    bot_version = $AppVersion
    lavalink_version = "bundled"
    java_runtime = "bundled"
    ffmpeg = "bundled"
    build_platform = "windows-x64"
    build_time_utc = (Get-Date).ToUniversalTime().ToString("o")
}
$Version | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $AppDir "version.json")

Copy-Item -Force (Join-Path $Root "README.md") (Join-Path $AppDir "README.md")
Copy-Item -Force (Join-Path $Root "LICENSE") (Join-Path $AppDir "LICENSE")

if (-not $SkipInstaller) {
    $env:SPOTY_APP_SOURCE = $AppDir
    $env:SPOTY_INSTALLER_OUTPUT = $ReleaseDir
    $env:SPOTY_APP_VERSION = $AppVersion

    $Iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $Iscc) {
        $DefaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (Test-Path $DefaultIscc) {
            $Iscc = @{ Source = $DefaultIscc }
        }
    }
    if (-not $Iscc) {
        throw "Inno Setup ISCC.exe not found. Install Inno Setup 6 or pass -SkipInstaller."
    }

    & $Iscc.Source (Join-Path $Root "installer\windows\Spoty.iss")
}

Write-Host "Windows app directory: $AppDir"
Write-Host "Windows release output: $ReleaseDir"

