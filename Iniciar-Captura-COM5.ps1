param(
    [string]$Puerto = 'auto',
    [ValidateSet('preguntar','direct','gateways')][string]$Metodo = 'preguntar'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$captureArguments = @('-u', 'scripts/start_capture.py', '--port', $Puerto)
if ($Metodo -eq 'preguntar') { $captureArguments += '--select-mode' }
else { $captureArguments += @('--receiver-mode', $Metodo) }
& '.\.venv\Scripts\python.exe' @captureArguments
