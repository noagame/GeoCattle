@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo No se encontro Python local. Consulta docs\REVISION_DOCKER_PORTABILIDAD.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -u "qa\docker_portability.py"
set "qa_exit=%errorlevel%"
pause
exit /b %qa_exit%
