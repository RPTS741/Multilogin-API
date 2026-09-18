@echo off
cd /d "%~dp0"
py -3 start.py
if errorlevel 1 echo Setup or execution stopped. Python 3.10+ and the Multilogin launcher must be available.
pause
