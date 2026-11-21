@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "GEOCATTLE_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%GEOCATTLE_PYTHON%" (
  echo Falta el entorno Python .venv de GeoCattle.
  pause
  exit /b 1
)
"%GEOCATTLE_PYTHON%" -u "%~dp0scripts\serve_lan_windows.py" %*
set "GEOCATTLE_RESULT=%ERRORLEVEL%"
if not "%GEOCATTLE_RESULT%"=="0" pause
exit /b %GEOCATTLE_RESULT%
