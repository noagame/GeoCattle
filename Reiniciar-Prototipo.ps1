$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'Detener-Prototipo.ps1')
& (Join-Path $PSScriptRoot 'Iniciar-Prototipo.ps1')
Write-Host 'Prototipo iniciado; captura COM5 en segundo plano. Cierra Monitor Serie y Plotter.'
