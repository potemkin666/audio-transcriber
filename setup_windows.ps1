$ErrorActionPreference = "Stop"

function Write-Info($msg) { Write-Host "[transcriber] $msg" }

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Info "Project: $ProjectRoot"

function Test-FFmpegAvailable {
  $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
  $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
  if ($ffmpeg -and $ffprobe) { return $true }

  $Bundled = Join-Path $ProjectRoot "tools\\ffmpeg\\bin\\ffmpeg.exe"
  $BundledProbe = Join-Path $ProjectRoot "tools\\ffmpeg\\bin\\ffprobe.exe"
  return ((Test-Path $Bundled) -and (Test-Path $BundledProbe))
}

function Ensure-BundledFFmpeg {
  if (Test-FFmpegAvailable) { return }

  Write-Info "FFmpeg not found. Downloading a local copy into tools\\ffmpeg ..."

  $ToolsDir = Join-Path $ProjectRoot "tools"
  $FfmpegDir = Join-Path $ToolsDir "ffmpeg"
  New-Item -ItemType Directory -Force -Path $FfmpegDir | Out-Null

  $ZipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
  $Tmp = New-Item -ItemType Directory -Force -Path (Join-Path ([System.IO.Path]::GetTempPath()) ("transcriber-ffmpeg-" + [guid]::NewGuid().ToString("N")))
  $ZipPath = Join-Path $Tmp.FullName "ffmpeg.zip"

  function Download-File($url, $dest) {
    $bits = Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue
    if ($bits) {
      Start-BitsTransfer -Source $url -Destination $dest -ErrorAction Stop | Out-Null
      return
    }

    try {
      Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -Headers @{ "User-Agent" = "Mozilla/5.0" } -ErrorAction Stop
      return
    } catch {
      $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
      if (-not $curl) { throw }
      & $curl.Source "-L" "--fail" "--retry" "3" "--retry-delay" "2" "--ssl-no-revoke" "-o" $dest $url | Out-Null
      return
    }
  }

  function Assert-ZipValid($path) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 4 -or $bytes[0] -ne 0x50 -or $bytes[1] -ne 0x4B) {
      throw "Downloaded file does not look like a ZIP archive."
    }
    $zip = [System.IO.Compression.ZipFile]::OpenRead($path)
    $zip.Dispose()
  }

  $attempts = 3
  $downloaded = $false
  for ($i = 1; $i -le $attempts; $i++) {
    try {
      if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath | Out-Null }
      Download-File $ZipUrl $ZipPath
      Assert-ZipValid $ZipPath
      $downloaded = $true
      break
    } catch {
      if ($i -eq $attempts) { throw }
      Start-Sleep -Seconds 2
    }
  }

  try {
    if (-not $downloaded -or -not (Test-Path $ZipPath)) {
      throw "Download step did not produce: $ZipPath"
    }
    $ExtractDir = Join-Path $Tmp.FullName "extract"
    New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractDir -Force

    $Found = Get-ChildItem -Path $ExtractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $Found) {
      throw "Could not find ffmpeg.exe inside downloaded archive."
    }

    $BinDir = Split-Path -Parent $Found.FullName

    if (Test-Path $FfmpegDir) {
      Remove-Item -Recurse -Force $FfmpegDir
    }
    New-Item -ItemType Directory -Force -Path $FfmpegDir | Out-Null

    $NormalizedBin = Join-Path $FfmpegDir "bin"
    New-Item -ItemType Directory -Force -Path $NormalizedBin | Out-Null
    Copy-Item -Force -Path (Join-Path $BinDir "ffmpeg.exe") -Destination (Join-Path $NormalizedBin "ffmpeg.exe")
    if (Test-Path (Join-Path $BinDir "ffprobe.exe")) {
      Copy-Item -Force -Path (Join-Path $BinDir "ffprobe.exe") -Destination (Join-Path $NormalizedBin "ffprobe.exe")
    } else {
      $FoundProbe = Get-ChildItem -Path $ExtractDir -Recurse -Filter "ffprobe.exe" | Select-Object -First 1
      if ($FoundProbe) {
        Copy-Item -Force -Path $FoundProbe.FullName -Destination (Join-Path $NormalizedBin "ffprobe.exe")
      }
    }

    if (-not (Test-FFmpegAvailable)) {
      throw "FFmpeg download completed, but ffmpeg.exe still isn't available."
    }

    Write-Info "FFmpeg ready."
  } finally {
    try { Remove-Item -Recurse -Force $Tmp.FullName | Out-Null } catch { }
  }
}

Ensure-BundledFFmpeg

if (-not (Test-Path ".\\.venv\\Scripts\\python.exe")) {
  Write-Info "Creating venv..."
  py -m venv .venv
}

Write-Info "Installing Python deps..."
& ".\\.venv\\Scripts\\python.exe" -m pip install -U pip | Out-Host
& ".\\.venv\\Scripts\\python.exe" -m pip install -r requirements.txt | Out-Host
Write-Info "Optional: run Setup-Speakers.cmd to enable speaker labels (beta)."

Write-Info "Generating icon..."
New-Item -ItemType Directory -Force -Path ".\\assets" | Out-Null
& ".\\.venv\\Scripts\\python.exe" ".\\scripts\\make_icon.py" --png ".\\assets\\mp3_transcriber.png" --ico ".\\assets\\mp3_transcriber.ico"

Write-Info "Creating Desktop shortcut..."
$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "TRANSCRIBER.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = (Join-Path $ProjectRoot "Launch.cmd")
$Shortcut.Arguments = ""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.IconLocation = (Resolve-Path ".\\assets\\mp3_transcriber.ico").Path
$Shortcut.Save()

Write-Info "Done."
Write-Host ""
Write-Host "Double-click the Desktop icon: TRANSCRIBER" -ForegroundColor Green
