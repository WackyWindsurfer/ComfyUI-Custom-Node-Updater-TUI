@echo off
REM ============================================================================
REM  ComfyUI-Custom-Node-Updater-TUI - headless manual runner
REM
REM  Scans every git repo in the active custom_nodes dirs and fast-forwards
REM  the safe ones (same safety gate as the TUI: ff-only, never merges/
REM  rebases/forces, skips diverged/detached/overlap, autostash on).
REM
REM  Usage:
REM     ComfyUI-Custom-Node-Updater-TUI-headless.bat            real run (pulls)
REM     ComfyUI-Custom-Node-Updater-TUI-headless.bat dry        dry run (report only)
REM     ComfyUI-Custom-Node-Updater-TUI-headless.bat nofetch    no network fetch
REM
REM  Report: %APPDATA%\ComfyUI-Custom-Node-Updater-TUI\activity.log
REM          %APPDATA%\ComfyUI-Custom-Node-Updater-TUI\last-headless-run.json
REM ============================================================================
setlocal
set "REPO=%~dp0"
set "PY=%REPO%.venv\Scripts\python.exe"
set "SCRIPT=%REPO%ComfyUI-Custom-Node-Updater-TUI-headless.py"

set "EXTRA="
if /I "%~1"=="dry"     set "EXTRA=--no-pull"
if /I "%~1"=="nofetch" set "EXTRA=--no-fetch"

if not exist "%PY%" (
    echo [ERROR] venv python not found: %PY%
    echo         Run:  "C:\Program Files\Python311\python.exe" -m venv .venv
    echo         then:  "%PY%" -m pip install textual rich
    exit /b 1
)

echo.
echo === ComfyUI custom-node updater (headless) - %date% %time% ===
echo     mode: %EXTRA% (blank = real pull)
echo.
"%PY%" -X utf8 "%SCRIPT%" %EXTRA%
set "RC=%ERRORLEVEL%"
echo.
echo === done (exit %RC%) - report in %APPDATA%\ComfyUI-Custom-Node-Updater-TUI\activity.log ===
pause
exit /b %RC%
