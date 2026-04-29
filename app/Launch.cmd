@echo off
setlocal
cd /d "%~dp0"

REM Delegate all real work to PowerShell to avoid cmd.exe quoting pitfalls.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Launch.ps1"
exit /b %errorlevel%
