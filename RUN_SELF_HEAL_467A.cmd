@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "RELEASE=467a46a78ba785a97366fa000b4ad3c005bfa46d"

call :download start.py f4164b17e9adec9e39706f4a998df578279f441841c5da4bf5a125fad0b729f2
if errorlevel 1 goto failed
call :download factory.py d5813e44511c3c121705505b300e5b0f6fa511ae31e4e3414b54298da7741008
if errorlevel 1 goto failed
call :download warm.py ca00b9d42e88b8ef90220c9db76565bc992808e2af02d6b33e5dba14be69926c
if errorlevel 1 goto failed

where python >nul 2>nul
if errorlevel 1 goto failed
echo Verified self-healing release %RELEASE%.
python start.py
goto finished

:download
set "TARGET=%~1"
set "EXPECTED=%~2"
curl.exe -fsSL "https://raw.githubusercontent.com/RPTS741/Multilogin-API/%RELEASE%/%TARGET%" -o "%TARGET%.download"
if errorlevel 1 exit /b 1
for /f %%H in ('powershell.exe -NoProfile -Command "(Get-FileHash -LiteralPath '%TARGET%.download' -Algorithm SHA256).Hash.ToLowerInvariant()"') do set "ACTUAL=%%H"
if /I not "%ACTUAL%"=="%EXPECTED%" (
  del /q "%TARGET%.download" >nul 2>nul
  echo Checksum verification failed for %TARGET%.
  exit /b 1
)
move /Y "%TARGET%.download" "%TARGET%" >nul
exit /b 0

:failed
echo Verified setup failed before execution. Nothing was changed in Multilogin.

:finished
pause
