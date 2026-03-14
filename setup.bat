@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
:: Remove trailing backslash
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "VENV_DIR=%PROJECT_DIR%\venv"
set "TASK_NAME=PhotoOCRServer"

echo.
echo ================================================
echo   Photo OCR - One-Time Setup
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found.
    echo Install Python 3.10+ from https://python.org and ensure it is on your PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v

echo.

:: Create virtual environment
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo Virtual environment already exists, skipping creation.
) else (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Done.
)

echo.

:: Upgrade pip
echo Upgrading pip...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip --quiet
echo Done.

echo.

:: Install dependencies
echo Installing dependencies (this may take a minute)...
"%VENV_DIR%\Scripts\pip.exe" install -r "%PROJECT_DIR%\requirements.txt"
if errorlevel 1 (
    echo ERROR: pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo Done.

echo.

:: Task Scheduler - auto-start on login
echo Registering auto-start task...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%PROJECT_DIR%\start.bat\"" ^
    /sc ONLOGON ^
    /ru "%USERNAME%" ^
    /rl HIGHEST ^
    /f ^
    /delay 0000:30 >nul 2>&1

if errorlevel 1 (
    echo WARNING: Could not register startup task.
    echo Run setup.bat as Administrator to enable auto-start on login.
) else (
    echo Auto-start task registered. Watcher will start 30 seconds after login.
)

echo.
echo ================================================
echo   Setup complete!
echo ================================================
echo.
echo   Next steps:
echo   1. Install iCloud for Windows from the Microsoft Store (if not already installed).
echo   2. Sign in and enable iCloud Photos sync in the iCloud app.
echo   3. Double-click start.bat to launch the watcher now.
echo.
pause
