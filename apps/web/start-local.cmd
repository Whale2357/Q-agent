@echo off
setlocal

title Q-Agent Launcher
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local.ps1"

if errorlevel 1 (
  echo.
  echo [Q-Agent] Startup failed. Read the message above, then press any key.
  pause >nul
)

endlocal
