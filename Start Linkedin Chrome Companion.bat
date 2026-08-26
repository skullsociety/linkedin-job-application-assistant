@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  where node.exe >nul 2>&1
  if errorlevel 1 (
    echo This project has not been set up yet.
    echo Install Node.js 18+ and run "Setup Linkedin Job Assistant.bat".
    pause
    exit /b 1
  )
  node "%~dp0bin\linkedin-job-assistant.js" start
) else (
  "%PYTHON%" -m companion.server
)
pause
