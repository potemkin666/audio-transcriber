@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. See message above.
  pause
  exit /b 1
)
echo.
echo Setup complete. You can now double-click the Desktop icon: TRANSCRIBER
echo Optional: run Setup-Speakers.cmd (speaker labels) or install hot-folder watch: pip install -r requirements-hotfolder.txt
pause
