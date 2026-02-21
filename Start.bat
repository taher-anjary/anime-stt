@echo off
title Anime STT
echo.
echo  =============================================
echo    Anime STT - Starting...
echo  =============================================
echo.

:: Change to the directory where this script lives
cd /d "%~dp0"

:: ── Check / install uv ─────────────────────────────────────────────────────
where uv >nul 2>&1
if %errorlevel% equ 0 goto :uv_ready

echo  uv not found. Installing via PowerShell...
powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Failed to install uv.
    echo  Visit https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

:: Try the known install path in case PATH hasn't refreshed
set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV_EXE%" set "UV_EXE=uv"
goto :sync

:uv_ready
set "UV_EXE=uv"

:: ── Sync dependencies ──────────────────────────────────────────────────────
:sync
echo  Syncing dependencies (first run may take a minute)...
"%UV_EXE%" sync
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Dependency sync failed. See above for details.
    pause
    exit /b 1
)

:: ── Launch app ─────────────────────────────────────────────────────────────
echo.
echo  Launching app — your browser will open automatically.
echo  Press Ctrl+C here to stop the server.
echo.
"%UV_EXE%" run app.py

echo.
echo  App exited.
pause
