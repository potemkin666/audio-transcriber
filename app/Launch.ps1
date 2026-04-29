param(
  [switch]$Lan
)

$ErrorActionPreference = "Stop"

function Get-ListenerPid([int]$port) {
  try {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $c) { return $null }
    return [int]$c.OwningProcess
  } catch {
    return $null
  }
}

function Get-ProcessCommandLine([int]$pid) {
  try {
    return (Get-CimInstance Win32_Process -Filter "ProcessId=$pid").CommandLine
  } catch {
    return $null
  }
}

function Wait-ForPort([int]$port, [int]$seconds) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    if (Get-ListenerPid -port $port) { return $true }
    Start-Sleep -Milliseconds 750
  }
  return $false
}

$root = $PSScriptRoot
$py = Join-Path $root ".venv\\Scripts\\python.exe"
$app = Join-Path $root "streamlit_app.py"

if (!(Test-Path -LiteralPath $py)) {
  Write-Host "Venv not found. Run Setup.cmd first." -ForegroundColor Red
  Read-Host "Press Enter to exit" | Out-Null
  exit 1
}

$logDir = Join-Path $root "logs"
try {
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
} catch {
  $logDir = Join-Path $env:TEMP "transcriber-logs"
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

$outLog = Join-Path $logDir "streamlit.out.log"
$errLog = Join-Path $logDir "streamlit.err.log"

$port = 8501
$existingPid = Get-ListenerPid -port $port
if ($existingPid) {
  $cmd = Get-ProcessCommandLine -pid $existingPid
  $isOurs = $false
  if ($cmd) {
    $isOurs = $cmd.ToLower().Contains($app.ToLower())
  }

  if ($isOurs) {
    Start-Process "http://localhost:$port" | Out-Null
    exit 0
  }

  Write-Host "Port $port is already in use by another process (PID $existingPid)." -ForegroundColor Yellow
  Write-Host "This usually happens if a previous run crashed or you moved folders."
  $ans = Read-Host "Kill the conflicting process and re-launch? (Y/N)"
  if ($ans -notin @("Y","y","Yes","yes")) {
    exit 1
  }
  try { Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue } catch {}
  Start-Sleep -Seconds 1
}

$addressArgs = ""
if ($Lan) {
  $addressArgs = "--server.address 0.0.0.0"
}

# IMPORTANT: Start-Process joins ArgumentList and does not auto-quote paths with spaces.
$argLine = "-m streamlit run `"$app`" --server.headless true --server.port $port $addressArgs --browser.gatherUsageStats false"
Start-Process -FilePath $py -ArgumentList $argLine -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog | Out-Null

if (!(Wait-ForPort -port $port -seconds 12)) {
  Write-Host "Failed to start the app." -ForegroundColor Red
  Write-Host "Logs:"
  Write-Host "  $errLog"
  Write-Host "  $outLog"
  try { if (Test-Path $errLog) { notepad $errLog } } catch {}
  try { if (Test-Path $outLog) { notepad $outLog } } catch {}
  Read-Host "Press Enter to exit" | Out-Null
  exit 1
}

Start-Process "http://localhost:$port" | Out-Null
exit 0

