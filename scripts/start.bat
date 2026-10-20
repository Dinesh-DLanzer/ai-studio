@echo off
setlocal enabledelayedexpansion
rem Unified start script for Windows: checks requirements, installs missing dependencies, and runs AI Studio.
cd /d "%~dp0.."

rem 1. Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [AI Studio] Python was not found on your system.
        echo Attempting to install Python via winget...
        where winget >nul 2>&1
        if %errorlevel% equ 0 (
            winget install --id Python.Python.3.11 --exact --accept-package-agreements --accept-source-agreements
            echo [AI Studio] Python installed. Please restart your terminal if it is not immediately recognized.
        ) else (
            echo winget is not available. Please install Python 3.10+ manually from https://python.org
            pause
            exit /b 1
        )
    )
)

rem 2. Check Node / npm
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [AI Studio] Node.js / npm not found.
    where winget >nul 2>&1
    if %errorlevel% equ 0 (
        echo Attempting to install Node.js via winget...
        winget install --id OpenJS.NodeJS.LTS --exact --accept-package-agreements --accept-source-agreements
    ) else (
        echo Please install Node.js (v18+) from https://nodejs.org
    )
)

rem 3. Check FFmpeg
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [AI Studio] ffmpeg not found.
    where winget >nul 2>&1
    if %errorlevel% equ 0 (
        echo Attempting to install FFmpeg via winget...
        winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements
    )
)

rem Prefer py or python to run start.py
where py >nul 2>&1
if %errorlevel% equ 0 (
    py scripts\start.py %*
) else (
    python scripts\start.py %*
)

if errorlevel 1 pause
