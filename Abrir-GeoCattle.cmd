@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "GEOCATTLE_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%GEOCATTLE_PYTHON%" (
  echo Falta el entorno Python .venv de GeoCattle.
  pause
  exit /b 1
)
"%GEOCATTLE_PYTHON%" -u "%~dp0scripts\prototype_windows.py" start --no-usb
if errorlevel 1 (
  echo No se pudo iniciar GeoCattle. Revisa la salida anterior.
  pause
  exit /b 1
)
start "" "http://localhost:8084/"
