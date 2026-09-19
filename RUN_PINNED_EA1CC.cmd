@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Immutable, checksum-verified release. Never downloads moving main-branch files.
set "RELEASE=ea1cce211e3c65887e8219da4a03481ac90b8edd"

call :download start.py 1d2039e3b2830ecb863e19b805178809df8e71237203f9f284ccb90c9ad27959
if errorlevel 1 goto failed
call :download factory.py 90da0582e70694e9d62f4d7578a166978e2f3f52857e55accc1f45ad84da3a61
if errorlevel 1 goto failed
call :download warm.py 5c6c0b4160d2642e6387427df505630f0b06bbae6d734095994076b7e478da76
if errorlevel 1 goto failed

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not available.
  goto failed
)

echo Verified release %RELEASE%.
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
