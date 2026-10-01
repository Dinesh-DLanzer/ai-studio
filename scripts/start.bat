@echo off
rem One command to run AI Studio on Windows (needs Python 3.10+ from python.org; "py" is its launcher)
cd /d "%~dp0.."
py scripts\start.py
if errorlevel 1 pause
