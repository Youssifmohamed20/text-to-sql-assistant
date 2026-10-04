@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment missing. Follow the setup steps in README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u app.py
if errorlevel 1 pause
