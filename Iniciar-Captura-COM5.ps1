param([string]$Puerto = 'auto')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' -u scripts/start_capture.py --port $Puerto
