@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not available. Install Python 3.10 or newer, then run this file again.
  pause
  exit /b 1
)
python start.py
if errorlevel 1 echo Setup or execution stopped. Python 3.10+ and the Multilogin launcher must be available.
pause
