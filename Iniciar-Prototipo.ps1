$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonGeoCattle = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonGeoCattle)) {
    throw 'Falta el entorno Python .venv del proyecto.'
}
& $pythonGeoCattle scripts/prototype_windows.py start
if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar GeoCattle. Revisar la salida anterior.' }
Start-Process 'http://localhost:8084/#hardware'
