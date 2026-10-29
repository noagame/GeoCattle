$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPath = [IO.Path]::GetFullPath($PSScriptRoot)
$remoteUrl = & git -C $projectPath remote get-url origin
if ($LASTEXITCODE -ne 0) { throw 'No se encontro el remoto origin.' }
if ($remoteUrl.Trim() -notin @('https://github.com/noagame/GeoCattle.git', 'https://github.com/noagame/GeoCattle', 'git@github.com:noagame/GeoCattle.git')) {
    throw 'El remoto origin no corresponde a noagame/GeoCattle; se conserva todo sin publicar.'
}
$refs = @('refs/heads/develop', 'refs/heads/dev/software', 'refs/heads/dev/hardware-captura', 'refs/tags/respaldo-2026-10-29')
foreach ($ref in $refs) {
    & git -C $projectPath show-ref --verify --quiet $ref
    if ($LASTEXITCODE -ne 0) { throw "Falta la referencia local: $ref" }
}
$pending = & git -C $projectPath status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'No se pudo revisar el estado de trabajo.' }
if ($pending) { throw 'Hay cambios sin guardar. Revisalos y haz commit en tu rama antes de publicar.' }
Write-Host 'Publicando ramas de software, hardware e integracion y etiqueta de respaldo...'
Write-Host 'Si GitHub pide iniciar sesion, utiliza BorBP. Se publican solo commits guardados.'
$refspecs = @($refs | ForEach-Object { $_ + ':' + $_ })
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& git -C $projectPath -c credential.username=BorBP push --atomic origin @refspecs
$pushCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference
if ($pushCode -ne 0) { throw 'La publicacion no termino. No se uso force ni se envio main. Conserva el mensaje de Git para revisarlo.' }
& git -C $projectPath fetch origin
if ($LASTEXITCODE -ne 0) { throw 'La subida termino, pero falta verificar las referencias remotas.' }
foreach ($branch in @('develop', 'dev/software', 'dev/hardware-captura')) {
    $localHash = & git -C $projectPath rev-parse ('refs/heads/' + $branch)
    $remoteHash = & git -C $projectPath rev-parse ('refs/remotes/origin/' + $branch)
    if ($localHash.Trim() -ne $remoteHash.Trim()) { throw "La rama $branch no coincide con el remoto; revisarla antes de continuar." }
    & git -C $projectPath branch ('--set-upstream-to=origin/' + $branch) $branch
    if ($LASTEXITCODE -ne 0) { throw "No se pudo configurar seguimiento para $branch" }
}
Write-Host 'Ramas publicadas y verificadas. Main no fue incluido en el push.' -ForegroundColor Green
Write-Host 'Fabian debe activar las protecciones de main y develop desde Settings / Rules de GitHub.'
