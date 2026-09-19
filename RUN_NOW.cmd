@echo off
setlocal
cd /d "%~dp0"
for %%F in (start.py factory.py warm.py) do (
  curl.exe -fsSL "https://raw.githubusercontent.com/RPTS741/Multilogin-API/main/%%F" -o "%%F.download"
  if errorlevel 1 goto download_failed
  move /Y "%%F.download" "%%F" >nul
)
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not available.
  goto stopped
)
python start.py
goto finished

:download_failed
echo Update download failed. Nothing has been started.
goto stopped

:stopped
echo Setup or execution stopped. Send a screenshot of this window.

:finished
pause
