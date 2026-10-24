$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPath = [IO.Path]::GetFullPath($PSScriptRoot)
$markers = 'adapters\.lora_usb|geocattle\.local_app|geocattle\.worker|prototype_windows\.py'

# Solo procesos Python de este proyecto y de sus cuatro servicios conocidos.
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and
    $_.CommandLine -match $markers -and
    ($_.CommandLine.IndexOf($projectPath, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
     ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($projectPath + '\', [StringComparison]::OrdinalIgnoreCase)))
})
foreach ($process in $processes) {
    try {
        Stop-Process -Id $process.ProcessId -ErrorAction Stop
        Write-Host "Servicio GeoCattle detenido: PID $($process.ProcessId)"
    } catch {
        if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) { throw }
    }
}

$pgCtl = Join-Path $projectPath '.runtime\postgres16\pgsql\bin\pg_ctl.exe'
$pgData = Join-Path $projectPath '.runtime\pgdata-academic'
if (Test-Path -LiteralPath $pgCtl) {
    & $pgCtl status -D $pgData
    if ($LASTEXITCODE -eq 0) {
        & $pgCtl stop -D $pgData -m fast -w -t 30
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo confirmar el cierre de PostgreSQL.' }
    }
}

$statusPath = Join-Path $projectPath '.runtime\capture\status.json'
if (Test-Path -LiteralPath $statusPath) {
    $captureStatus = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $captureStatus.connected = $false
    $captureStatus.error = 'Captura detenida por el usuario'
    $captureStatus.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
    $captureStatus | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

$stillOpen = @()
foreach ($port in @(8084,55434)) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $port)
        $stillOpen += $port
    } catch { } finally { $client.Dispose() }
}
if ($stillOpen.Count) { throw "Siguen activos estos puertos: $($stillOpen -join ', ')." }
Write-Host 'GeoCattle y PostgreSQL cerrados. Datos conservados. Puedes desconectar las placas.'
