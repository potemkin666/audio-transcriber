@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
set "APP=%ROOT%app"

if not exist "%APP%\Launch.cmd" (
  echo TRANSCRIBER app files are missing.
  echo Expected: %APP%\Launch.cmd
  pause
  exit /b 1
)

if not exist "%APP%\.venv\Scripts\python.exe" (
  echo First run: installing TRANSCRIBER.
  echo This can take a few minutes.
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\setup_windows.ps1"
  if errorlevel 1 (
    echo.
    echo Setup failed.
    pause
    exit /b 1
  )
)

cd /d "%ROOT%"
call "%APP%\Launch.cmd"
