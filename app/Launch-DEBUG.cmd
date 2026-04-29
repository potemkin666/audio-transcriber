@echo off
setlocal
cd /d "%~dp0"

echo [TRANSCRIBER] Debug launch (foreground)
echo If it errors, copy/paste this window text to me.
echo.

if not exist ".\.venv\Scripts\python.exe" (
  echo Venv not found. Run Setup.cmd first.
  pause
  exit /b 1
)

REM Run in the foreground so errors stay visible.
".\.venv\Scripts\python.exe" -m streamlit run "%~dp0streamlit_app.py" --server.port 8501 --browser.gatherUsageStats false
echo.
echo [TRANSCRIBER] Streamlit exited.
pause

