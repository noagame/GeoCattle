@echo off
setlocal
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -u "%~dp0scripts\prototype_windows.py" start --no-usb
if errorlevel 1 (
  echo No se pudo iniciar GeoCattle. Conserva esta salida para revisarla.
  pause
  exit /b 1
)
start "" "http://localhost:8084/"
