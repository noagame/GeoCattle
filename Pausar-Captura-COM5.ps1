$ErrorActionPreference='Stop'
$projectPath=[IO.Path]::GetFullPath($PSScriptRoot)
$readers=@(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and
    $_.CommandLine -match 'adapters\.lora_usb' -and
    ($_.CommandLine.IndexOf($projectPath,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
     ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($projectPath+'\',[StringComparison]::OrdinalIgnoreCase)))
})
foreach($reader in $readers){
    try{Stop-Process -Id $reader.ProcessId -ErrorAction Stop}
    catch{if(Get-Process -Id $reader.ProcessId -ErrorAction SilentlyContinue){throw}}
}
$statusPath=Join-Path $PSScriptRoot '.runtime\capture\status.json'
if(Test-Path -LiteralPath $statusPath){
    $captureState=Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $captureState.connected=$false
    $captureState.error='Captura pausada para cargar firmware'
    $captureState.updated_at=[DateTimeOffset]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($statusPath,($captureState | ConvertTo-Json),(New-Object Text.UTF8Encoding $false))
}
Write-Host 'Captura pausada. COM5 queda disponible para Arduino IDE. GeoCattle y PostgreSQL siguen activos.'
