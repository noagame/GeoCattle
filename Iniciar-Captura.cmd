@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "GEOCATTLE_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%GEOCATTLE_PYTHON%" (
  echo Falta el entorno Python .venv de GeoCattle.
  pause
  exit /b 1
)
if "%~1"=="" (
  "%GEOCATTLE_PYTHON%" -u "%~dp0scripts\start_capture.py" --select-mode
) else (
  "%GEOCATTLE_PYTHON%" -u "%~dp0scripts\start_capture.py" %*
)
if errorlevel 1 (
  pause
  exit /b 1
)
