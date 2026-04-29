@echo off
setlocal
cd /d "%~dp0"

if not exist ".\.venv\Scripts\python.exe" (
  echo Venv not found. Run Setup.cmd first.
  pause
  exit /b 1
)

REM If already running, just open the browser.
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8501 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
  start "" "http://localhost:8501"
  exit /b 0
)

if not exist ".\logs" mkdir ".\logs" >nul 2>&1
set "LOGOUT=%~dp0logs\streamlit.out.log"
set "LOGERR=%~dp0logs\streamlit.err.log"

REM Start Streamlit in the background (robust quoting via PowerShell).
powershell -NoProfile -Command ^
  "$root = (Get-Location).Path; " ^
  "$py = Join-Path $root '.venv\\Scripts\\python.exe'; " ^
  "$app = Join-Path $root 'streamlit_app.py'; " ^
  "$out = Join-Path $root 'logs\\streamlit.out.log'; " ^
  "$err = Join-Path $root 'logs\\streamlit.err.log'; " ^
  "$args = @('-m','streamlit','run',$app,'--server.headless','true','--server.port','8501','--browser.gatherUsageStats','false'); " ^
  "Start-Process -FilePath $py -ArgumentList $args -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err | Out-Null"

REM Give it a moment to boot, then open the UI.
set "READY=0"
for /L %%i in (1,1,12) do (
  powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8501 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
  if %errorlevel%==0 (
    set "READY=1"
    goto :openui
  )
  ping 127.0.0.1 -n 2 >nul
)

if "%READY%"=="0" (
  echo Failed to start the app. Opening logs...
  if exist "%LOGERR%" notepad "%LOGERR%"
  if exist "%LOGOUT%" notepad "%LOGOUT%"
  pause
  exit /b 1
)

:openui
start "" "http://localhost:8501"
exit /b 0
