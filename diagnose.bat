@echo off
setlocal

set "DIR=%~dp0"

echo.
echo ============================================================
echo   Photo OCR — Diagnostics
echo ============================================================
echo.

:: 1. Check if pythonw.exe is running
echo [1] Checking for running server process...
tasklist /FI "IMAGENAME eq pythonw.exe" 2>nul | find /I "pythonw.exe" >nul
if %ERRORLEVEL% == 0 (
    echo     STATUS: RUNNING ^(pythonw.exe found^)
) else (
    echo     STATUS: NOT RUNNING ^(no pythonw.exe process^)
    echo     TIP: Run start.bat to launch the server.
)
echo.

:: 2. Show last 20 lines of server.log
echo [2] Last 20 lines of server.log:
if exist "%DIR%server.log" (
    echo     Log file: %DIR%server.log
    echo     ---
    powershell -NoProfile -Command "Get-Content '%DIR%server.log' -Tail 20 | ForEach-Object { '    ' + $_ }"
) else (
    echo     server.log not found — server may not have started yet.
)
echo.

:: 3. Check iCloud Photos candidate paths
echo [3] Checking iCloud Photos folder candidates:
set "FOUND=0"

set "P1=%USERPROFILE%\Pictures\iCloud Photos\Photos"
set "P2=%USERPROFILE%\Pictures\iCloud Photos"
set "P3=%USERPROFILE%\iCloudDrive\iCloud Photos\Photos"
set "P4=%USERPROFILE%\iCloudDrive\iCloud Photos"

for %%P in ("%P1%" "%P2%" "%P3%" "%P4%") do (
    if exist %%P (
        echo     FOUND:   %%~P
        set "FOUND=1"
    ) else (
        echo     missing: %%~P
    )
)

if "%FOUND%"=="0" (
    echo.
    echo     WARNING: No iCloud Photos folder found at any candidate path.
    echo     Make sure iCloud for Windows is installed and Photos sync is enabled.
)
echo.

echo ============================================================
echo   Done.
echo ============================================================
echo.
pause
