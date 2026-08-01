@echo off
REM ============================================================
REM  FileShare one-step setup for Windows (Python version)
REM  Installs Python if needed, then runs the FileShare GUI app.
REM  No Docker required.
REM
REM  Run it: just double-click this file.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title FileShare (Python)

set "PY="

REM ---------- 1. Look for an existing Python 3 ----------
REM Try the py launcher first (installed by python.org / winget installs)
py -3 --version >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
    goto :have_python
)

REM Try plain "python" (skip the fake Microsoft Store stub, which errors out)
python --version >nul 2>&1
if %errorlevel%==0 (
    set "PY=python"
    goto :have_python
)

REM ---------- 2. Install Python via winget ----------
echo Python is not installed. Installing Python 3.12...
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo.
    echo Automatic install failed. Please install Python manually from:
    echo   https://www.python.org/downloads/
    echo IMPORTANT: tick "Add python.exe to PATH" during setup.
    echo Then run this script again.
    pause
    exit /b 1
)

REM The new install isn't on this window's PATH yet, so find it directly.
py -3 --version >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
    goto :have_python
)
for /d %%d in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%d\python.exe" set "PY="%%d\python.exe""
)
if not defined PY (
    echo.
    echo Python was installed but could not be located automatically.
    echo Please close this window and run the script again.
    pause
    exit /b 1
)

:have_python
echo Using Python:
%PY% --version

REM ---------- 3. Run FileShare ----------
if not exist "fileshare.py" (
    echo.
    echo fileshare.py was not found next to this script.
    echo Keep this .bat file in the same folder as fileshare.py.
    pause
    exit /b 1
)

echo Starting FileShare...
%PY% fileshare.py
if errorlevel 1 (
    echo.
    echo FileShare exited with an error. See the messages above.
    pause
    exit /b 1
)
