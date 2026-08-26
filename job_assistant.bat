@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo This project has not been set up yet.
  echo Run "Setup Linkedin Job Assistant.bat" first.
  pause
  exit /b 1
)

:menu
cls
echo ======================================
echo   Linkedin Job Application Assistant
echo ======================================
echo  1. Log in to LinkedIn manually
echo  2. Auto-capture, match, and tailor LinkedIn jobs while you browse
echo  3. List saved jobs
echo  4. Match newest resume in resumes folder (70 percent or higher)
echo  5. Manual application using links
echo  6. Remove all saved job data and generated outputs
echo  7. Exit
echo.
set /p "choice=Choose an option (1-7): "

if "%choice%"=="1" goto login
if "%choice%"=="2" goto capture
if "%choice%"=="3" goto list
if "%choice%"=="4" goto match
if "%choice%"=="5" goto apply
if "%choice%"=="6" goto clear_data
if "%choice%"=="7" goto end
echo Invalid choice.
pause
goto menu

:login
"%PYTHON%" -m job_assistant login
pause
goto menu

:capture
"%PYTHON%" -m job_assistant capture
pause
goto menu

:list
"%PYTHON%" -m job_assistant list
pause
goto menu

:match
"%PYTHON%" -m job_assistant match-latest-resume
pause
goto menu

:apply
set "JOB_ID="
set /p "JOB_ID=Enter the job ID to prepare: "
if "%JOB_ID%"=="" (
  echo No job ID entered.
  pause
  goto menu
)
"%PYTHON%" -m job_assistant apply %JOB_ID%
pause
goto menu

:clear_data
"%PYTHON%" -m job_assistant clear-data
pause
goto menu

:end
endlocal
