param(
  [string]$Version = "dev",
  [switch]$SkipBundledTools
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistRoot = Join-Path $ProjectRoot "dist"
$PackageName = if ($Version -eq "dev") { "TRANSCRIBER-Windows" } else { "TRANSCRIBER-Windows-$Version" }
$PackageRoot = Join-Path $DistRoot $PackageName
$AppRoot = Join-Path $PackageRoot "app"
$ZipPath = Join-Path $DistRoot "$PackageName.zip"

function Write-Info($msg) { Write-Host "[package] $msg" }

function Copy-ProjectItem($relativePath) {
  $src = Join-Path $ProjectRoot $relativePath
  if (-not (Test-Path $src)) { return }

  $dest = Join-Path $AppRoot $relativePath
  $destParent = Split-Path -Parent $dest
  if ($destParent -and -not (Test-Path $destParent)) {
    New-Item -ItemType Directory -Force -Path $destParent | Out-Null
  }

  Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force
}

function New-Launcher($name, $target) {
  $path = Join-Path $PackageRoot $name
  $content = @"
@echo off
cd /d "%~dp0app"
call "$target"
"@
  Set-Content -LiteralPath $path -Value $content -Encoding ASCII
}

Write-Info "Building $PackageName"

if (Test-Path $PackageRoot) {
  Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
if (Test-Path $ZipPath) {
  Remove-Item -LiteralPath $ZipPath -Force
}
New-Item -ItemType Directory -Force -Path $AppRoot | Out-Null

$items = @(
  "START_HERE.md",
  "README.md",
  "LICENSE",
  "Setup.cmd",
  "Launch.cmd",
  "Launch-LAN.cmd",
  "Setup-Speakers.cmd",
  "setup_windows.ps1",
  "streamlit_app.py",
  "transcribe_cli.py",
  "watch_hotfolder.py",
  "requirements.txt",
  "requirements-speakers.txt",
  "requirements-hotfolder.txt",
  "pyproject.toml",
  "assets",
  "docs",
  "scripts\make_icon.py",
  "transcriber"
)

foreach ($item in $items) {
  Copy-ProjectItem $item
}

if (-not $SkipBundledTools -and (Test-Path (Join-Path $ProjectRoot "tools\ffmpeg\bin\ffmpeg.exe"))) {
  Copy-ProjectItem "tools\ffmpeg"
}

New-Launcher "1 Install TRANSCRIBER.cmd" "Setup.cmd"
New-Launcher "2 Start TRANSCRIBER.cmd" "Launch.cmd"
New-Launcher "Start TRANSCRIBER on Wi-Fi.cmd" "Launch-LAN.cmd"
New-Launcher "Optional - Install Speaker Labels.cmd" "Setup-Speakers.cmd"

Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination (Join-Path $PackageRoot "README.md") -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "START_HERE.md") -Destination (Join-Path $PackageRoot "START_HERE.md") -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Destination (Join-Path $PackageRoot "LICENSE") -Force

$releaseNote = @"
# TRANSCRIBER Windows Release

1. Double-click `1 Install TRANSCRIBER.cmd`.
2. Wait for setup to finish.
3. Double-click `2 Start TRANSCRIBER.cmd` or use the Desktop shortcut.

Keep this folder somewhere permanent, such as Documents or Desktop. The app stores its local Python environment inside the `app` folder after setup.
"@
Set-Content -LiteralPath (Join-Path $PackageRoot "START_HERE_FIRST.md") -Value $releaseNote -Encoding UTF8

$archiveItems = Get-ChildItem -LiteralPath $PackageRoot -Force | ForEach-Object { $_.FullName }
Compress-Archive -Path $archiveItems -DestinationPath $ZipPath -Force

$appItem = Get-Item -LiteralPath $AppRoot -Force
$appItem.Attributes = $appItem.Attributes -bor [System.IO.FileAttributes]::Hidden

Write-Info "Release folder: $PackageRoot"
Write-Info "Release ZIP:    $ZipPath"
