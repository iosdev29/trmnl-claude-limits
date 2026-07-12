# Claude UNLMTD — one-command installer for Windows.
#
#   irm https://raw.githubusercontent.com/iosdev29/trmnl-claude-limits/main/scripts/bootstrap.ps1 | iex
#
# Downloads the repo into %LOCALAPPDATA%\trmnl-claude-limits, drops a
# `trmnl-claude-limits.cmd` shim into a folder on your user PATH, then runs
# the interactive installer (which prompts for your TRMNL webhook URL and
# schedules the push job via Task Scheduler).
#
# Override the source repo (for forks): $env:REPO = "you/your-fork"; then run.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo   = if ($env:REPO)   { $env:REPO }   else { 'iosdev29/trmnl-claude-limits' }
$branch = if ($env:BRANCH) { $env:BRANCH } else { 'main' }
$prefix = if ($env:PREFIX) { $env:PREFIX } else { Join-Path $env:LOCALAPPDATA 'trmnl-claude-limits' }
$binDir = if ($env:BIN_DIR) { $env:BIN_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\trmnl-claude-limits\bin' }

function Info($msg) { Write-Host "-> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "!  $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "x  $msg" -ForegroundColor Red; exit 1 }

# Refuse to run if PREFIX/BIN_DIR points anywhere outside the user's own
# directories — we mirror files into $prefix and would otherwise be able to
# wipe (say) C:\ if someone set $env:PREFIX = "C:\".
$allowedRoots = @($env:LOCALAPPDATA, $env:USERPROFILE) | Where-Object { $_ }
function Assert-UnderUserRoot($path, $name) {
    $full = [IO.Path]::GetFullPath($path)
    foreach ($root in $allowedRoots) {
        $rootFull = [IO.Path]::GetFullPath($root).TrimEnd('\')
        if ($full.StartsWith("$rootFull\", [StringComparison]::OrdinalIgnoreCase) -or
            $full -ieq $rootFull) { return }
    }
    Die "refusing: $name=$path must be inside `$env:LOCALAPPDATA or `$env:USERPROFILE."
}
Assert-UnderUserRoot $prefix 'PREFIX'
Assert-UnderUserRoot $binDir 'BIN_DIR'

# --- prerequisites -------------------------------------------------------- #
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) {
    Die "Python 3 not found. Install Python 3.8+ from https://python.org and retry."
}

# --- download ------------------------------------------------------------- #
Info "downloading $repo@$branch -> $prefix"
New-Item -ItemType Directory -Force -Path $prefix | Out-Null
$tmpZip = Join-Path ([System.IO.Path]::GetTempPath()) "trmnl-claude-limits-$branch.zip"
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "trmnl-claude-limits-$branch"
if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir }

Invoke-WebRequest -UseBasicParsing `
    -Uri "https://codeload.github.com/$repo/zip/refs/heads/$branch" `
    -OutFile $tmpZip

Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
$src = Get-ChildItem -Path $tmpDir -Directory | Select-Object -First 1
if (-not $src) { Die "extraction failed" }

# Mirror files into $prefix (overwrite in place).
Get-ChildItem -Path $prefix -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Copy-Item -Path (Join-Path $src.FullName '*') -Destination $prefix -Recurse -Force
Remove-Item -Recurse -Force $tmpZip, $tmpDir

# --- shim ----------------------------------------------------------------- #
Info "installing shim -> $binDir\trmnl-claude-limits.cmd"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

$shim = @"
@echo off
setlocal
set "PREFIX=$prefix"
set "PYTHON=$($python.Source)"
rem cmd.exe: %* ignores shift, so we forward %1..%9 explicitly in the push branch.
if /I "%~1"=="push" (
    shift
    "%PYTHON%" "%PREFIX%\scripts\push_usage.py" %1 %2 %3 %4 %5 %6 %7 %8 %9
) else (
    "%PYTHON%" "%PREFIX%\scripts\install.py" %*
)
"@
Set-Content -Path (Join-Path $binDir 'trmnl-claude-limits.cmd') -Value $shim -Encoding ASCII

# --- PATH ----------------------------------------------------------------- #
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not ($userPath -split ';' | Where-Object { $_ -eq $binDir })) {
    Info "adding $binDir to your user PATH"
    # Append (not prepend) so this shim can't shadow anything installed later.
    $newPath = if ([string]::IsNullOrEmpty($userPath)) { $binDir } else { "$userPath;$binDir" }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    $env:Path = "$env:Path;$binDir"
    Warn "restart your terminal for the PATH change to take effect in new shells."
}

# --- run installer -------------------------------------------------------- #
Info "starting interactive setup..."
Write-Host ""
& (Join-Path $binDir 'trmnl-claude-limits.cmd')
