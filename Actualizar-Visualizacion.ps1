$ErrorActionPreference = 'Stop'
Write-Host '[1/4] Aplicando visualizacion de telemetria...'
Set-Location -LiteralPath $PSScriptRoot
$projectPath = [IO.Path]::GetFullPath($PSScriptRoot)
$pythonGeo = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonGeo)) { throw 'Falta Python del proyecto.' }
# Solo se reinicia esta API; PostgreSQL y la captura conservan sus datos.
$apiProcesses = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'geocattle\.local_app:app' -and
    ($_.CommandLine.IndexOf($projectPath,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($projectPath+'\',[StringComparison]::OrdinalIgnoreCase)))
})
foreach ($service in $apiProcesses) {
    Stop-Process -Id $service.ProcessId -ErrorAction SilentlyContinue
    Wait-Process -Id $service.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
}
Write-Host '[2/4] Iniciando API actualizada en localhost:8084...'
$code = @"
import sys,time,urllib.request
from scripts.prototype_windows import environment,spawn,listening
if listening(8084):
    raise SystemExit('El puerto 8084 sigue ocupado; no se confirma la actualizacion.')
spawn('prototype-api',[sys.executable,'-m','uvicorn','geocattle.local_app:app','--host','127.0.0.1','--port','8084'],environment())
for attempt in range(40):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8084/api/openapi.json',timeout=2) as response:
            import json
            if '/api/v1/hardware/overview' not in json.load(response)['paths']:
                raise SystemExit('La API no contiene la nueva vista de telemetria.')
        print('API actualizada y verificada.',flush=True)
        break
    except OSError:
        time.sleep(.5)
else:
    raise SystemExit('La API no responde; revisar .runtime/prototype-api.log')
"@
& $pythonGeo -u -c $code
if ($LASTEXITCODE -ne 0) { throw 'No se pudo verificar la nueva API.' }
Write-Host '[3/4] Abriendo Recepcion de collares...'
Start-Process 'http://localhost:8084/#hardware'
Write-Host '[4/4] Comprobando COM5. Captura en segundo plano; no abrir Monitor Serie.'
& $pythonGeo -u scripts/prototype_windows.py capture
if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar la captura.' }
Write-Host 'Visualizacion actualizada. Comprobando captura durante 12 segundos...'
Start-Sleep -Seconds 12
$statusPath = Join-Path $projectPath '.runtime\capture\status.json'
if (Test-Path -LiteralPath $statusPath) {
    $captureState = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $updated = [DateTimeOffset]::Parse($captureState.updated_at)
    if (([DateTimeOffset]::UtcNow - $updated).TotalSeconds -ge 30) {
        Write-Host 'Captura sin actualizar. Ejecuta Iniciar-Captura-COM5.ps1 y copia su salida.'
    } else {
        Write-Host ('COM5 conectado: {0} | Guardadas: {1} | Pendientes: {2} | Error: {3}' -f $captureState.connected,$captureState.delivered,$captureState.pending,$captureState.error)
    }
}
Write-Host 'Listo. En el navegador presiona Ctrl+F5 para cargar la interfaz nueva.'
