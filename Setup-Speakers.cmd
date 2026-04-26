@echo off
setlocal
cd /d "%~dp0"

if not exist ".\.venv\Scripts\python.exe" (
  echo Venv not found. Run Setup.cmd first.
  pause
  exit /b 1
)

echo Installing optional speaker-labeling deps...
".\.venv\Scripts\python.exe" -m pip install -r requirements-speakers.txt
if errorlevel 1 (
  echo.
  echo Speaker deps install failed. See output above.
  pause
  exit /b 1
)

echo.
echo Done. Re-launch TRANSCRIBER.
pause

