@echo off
setlocal
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -u "%~dp0scripts\start_capture.py"
pause
