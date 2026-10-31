@echo off
rem Starts the News Scraper Platform and opens the dashboard in your browser.
rem The first start creates a private Python environment in the .venv folder.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First start: setting up the Python environment. This takes a minute or two...
    where python >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python was not found. Install Python 3.11 or newer, or start this file from an Anaconda Prompt.
        pause
        exit /b 1
    )
    python -m venv .venv
    if errorlevel 1 ( pause & exit /b 1 )
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
)

".venv\Scripts\python.exe" run.py %*
if errorlevel 1 pause
