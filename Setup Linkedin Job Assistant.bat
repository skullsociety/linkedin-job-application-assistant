@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where node.exe >nul 2>&1
if errorlevel 1 (
  echo Node.js 18 or newer is required for the portable setup command.
  echo Download it from https://nodejs.org/ and run this file again.
  pause
  exit /b 1
)

node "%~dp0bin\linkedin-job-assistant.js" setup
if errorlevel 1 (
  echo.
  echo Setup did not finish. Review the message above, then try again.
  pause
  exit /b 1
)

node "%~dp0bin\linkedin-job-assistant.js" install-chrome-host
if errorlevel 1 (
  echo.
  echo Application setup succeeded, but Chrome integration did not finish.
  echo Run this setup file again or review the error above.
  pause
  exit /b 1
)

echo.
echo Setup completed successfully. Chrome will start the companion automatically.
pause
