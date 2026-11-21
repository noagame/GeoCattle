@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Falta el entorno Python .venv de GeoCattle.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0scripts\register_collar_usb.py"
set "GEOCATTLE_RESULT=%ERRORLEVEL%"
pause
exit /b %GEOCATTLE_RESULT%
