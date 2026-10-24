$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'Cierra Monitor Serie y Plotter de Arduino IDE. Deja la placa conectada.'
& '.\.venv\Scripts\python.exe' -u -m adapters.lora_usb --port COM5
