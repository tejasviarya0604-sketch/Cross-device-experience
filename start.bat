@echo off
setlocal

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "PYTHONW=%PROJECT_DIR%\venv\Scripts\pythonw.exe"
set "SERVER=%PROJECT_DIR%\server.py"

if not exist "%PYTHONW%" (
    echo ERROR: Virtual environment not found.
    echo Run setup.bat first.
    pause
    exit /b 1
)

:: pythonw.exe runs without a console window (silent background process)
start "" "%PYTHONW%" "%SERVER%"
