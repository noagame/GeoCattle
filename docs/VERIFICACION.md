# Verificación de software de GeoCattle

Fecha de publicación: 24 de octubre de 2026, America/Santiago.

## Resultados de esta actualización

| Comprobación | Resultado |
|---|---|
| Backend: reglas, API, roles, MFA, asociaciones, invitaciones y parámetros | 109 pruebas correctas |
| Contratos y adaptadores JSON/CSV, cola y entrega HTTP | 26 pruebas correctas |
| TypeScript y construcción Vite | Correctos |
| Diff Git y enlaces locales de README/resumen | Revisados |
| Navegador en base QA aislada | Dueño, trabajador, veterinario, administrador y configuración de alertas |

La suite de backend se ejecutó en PostgreSQL/PostGIS de QA separado de la base de telemetría real. Las pruebas visuales usaron identidades y registros ficticios. Los informes de consola se conservan localmente en `.runtime/review/`; esa carpeta no se publica.

La infraestructura de pruebas emitió una advertencia de deprecación de Starlette/TestClient/httpx. Vite señaló un bloque JavaScript superior a 500 kB. Ninguna advertencia impidió aprobar pruebas o construir la aplicación.

## Contrato y adaptadores sin placas

Con las dependencias de backend, pytest y `adapters/requirements.txt` instaladas, desde la raíz:

```powershell
python -m unittest qa.test_lora_json qa.test_lora_usb qa.test_esp32_contract qa.test_academic_bridge
```

Estas pruebas emplean datos de ejemplo y un servidor HTTP local de prueba. No requieren COM5 ni escriben en PostgreSQL. En un entorno restringido de Windows se puede necesitar un directorio temporal local con permisos de escritura para SQLite y su limpieza.

## Backend con base aislada

Las suites necesitan PostgreSQL/PostGIS y el esquema migrado. `TEST_DATABASE_URL` debe apuntar a una base QA dedicada, con credencial de preparación. No usar la base física para esta ejecución. `DATABASE_URL` debe seleccionar esa misma base durante el proceso de prueba.

La ruta de desarrollo en simulación está encapsulada por:

```bash
# Preparar dependencias dentro de backend con uv sync --extra test.
# La configuración privada elegida debe pertenecer a una instancia de simulación separada.
python3 scripts/local_backend.py test --env-file RUTA_QA
```

El wrapper conserva la prohibición de probar mediante esa ruta sobre development/production. La ejecución de publicación usó una base QA previamente preparada y variables exclusivas de ese proceso. No se cambió la configuración del servidor operativo.

`qa/test_hardware_api.py` es una suite adicional de cinco comprobaciones que se omite por defecto. Requiere `GEOCATTLE_TEST_DATABASE=1` y `TEST_DATABASE_URL` apuntando a PostgreSQL/PostGIS de QA con el esquema migrado. La suite crea y revierte sus propias cuentas, predios y lecturas ficticias. Sus verificaciones anteriores están documentadas en [Visualización de telemetría](VISUALIZACION_TELEMETRIA.md).

### Recorrido HTTP, carga y recuperación en QA

Usa un PostgreSQL/PostGIS de loopback con una base descartable `geocattle_qa_*`, las migraciones aplicadas y una API de desarrollo en otro puerto. Ajusta `DATABASE_URL`, `APP_ENV=development`, `SIMULATION_ENABLED=false`, `INGEST_KEY` y `PYTHONPATH=backend` en el proceso QA. Si varias bases de QA comparten clúster, usa la misma contraseña de `geocattle_app` al migrarlas y evita aplicar migraciones durante la medición. El rol y su contraseña pertenecen al clúster.

- `python -m qa.smoke_capture_http --url https://127.0.0.1:PUERTO --ca RUTA_CA --output RUTA_JSON` prueba las cuatro funciones sobre HTTPS. Define `QA_SMOKE_PASSWORD` como contraseña ficticia y usa `COOKIE_SECURE=true`, `ADMIN_LOGIN_MFA=true` y el origen HTTPS exacto. Para `--smtp`, apunta API y worker al mismo SMTP local con TLS y configura una misma `INVITATION_BASE_URL`.
- `python -m qa.benchmark_capture --url http://127.0.0.1:PUERTO --output RUTA_JSON` ejecuta 70 collares durante 600 s y ráfagas de 70 y 320. Define `QA_BENCH_PASSWORD` y añade `psutil` al entorno QA. Puedes indicar los PID de la API, el worker y el postmaster con `--api-pid`, `--worker-pid` y `--postgres-pid` para registrar CPU y memoria.
- `python -m qa.smoke_capture_recovery --directory RUTA_TEMPORAL_NUEVA` inicia su propia API de loopback, comprueba los reintentos, reabre SQLite y reconcilia 1.000 secuencias con PostgreSQL después de un corte de 1.800 s. Usa la misma configuración que la carga y omite cualquier capturador físico.
- Para ejecutar pytest en desarrollo, después de verificar la base aislada, configura `TEST_DATABASE_URL` con la misma URL que `DATABASE_URL` y usa `python -m pytest backend/tests -q -rs` desde la raíz.

[Campaña QA del 22 de noviembre de 2026](evidencias/QA_2026-11-22.md)

### Exportaciones de Excel y CSV

En el entorno del backend con el extra `test`, `python -m pytest backend/tests/test_report_exports.py -q` desde la raíz comprueba los tipos y el escape con openpyxl y el lector CSV. En QA, `backend/tests/test_v3_animal_reports.py` comprueba además filtros de predio y zona horaria, roles, límites y concordancia con la vista previa. Para una revisión manual con el rebaño ficticio, descarga sanidad y telemetría (esta última requiere el seed de simulación o lecturas sintéticas) y abre el `.xlsx` en Excel. Comprueba las columnas, los tipos y la hoja `Metadatos`. El CSV de la interfaz usa `;` y coma decimal; el de integración usa `,` por defecto y puede requerir importación manual. [Contrato](CONTRATO_API.md#exportaciones-tabulares)

## Carga de un rebaño de validación

`scripts/seed_validation_data.py` carga 40 bovinos ficticios de Temuco con aretes `VAL-09-…`, 120 pesajes, 96 eventos sanitarios, 88 productos aplicados, 40 atenciones futuras y 50 observaciones. Entre los eventos hay 40 vacunaciones, 40 procedimientos antiparasitarios, 8 tratamientos antibióticos y 8 exámenes. Las fichas de productos, los lotes, las dosis y los resguardos son ficticios. El script registra la categoría y 10 pares madre–cría por nombre y DIIO en las observaciones. Los pesajes, las observaciones y los eventos sanitarios usan fechas de los últimos 18 meses.

La base debe estar migrada y el actor debe ser un dueño o administrador activo. El destino predeterminado es **Predio de validación**, identificado por actor y entorno y marcado como datos de prueba. Para crear ese predio, la cuenta dueña existente necesita un cupo disponible. El administrador puede usar su propio predio de validación mediante su acceso de plataforma. `--farm-id UUID --allow-existing-farm` permite dirigir el lote a un predio activo del mismo entorno que el actor administra o posee. Si ese predio ya cuenta con geocercas vigentes de sectores activos, se crea un pastoreo por bovino. Los conteos de collares, asignaciones de collar y telemetría de la carga son cero.

Cuando el entorno físico contiene varios predios activos, `INGEST_FARM_ID` identifica el predio físico para la detección de collares. [Desarrollo local](DESARROLLO_LOCAL.md#incorporar-un-collar-por-usb-o-lora)

Usa un archivo privado del entorno objetivo y el Python con dependencias del backend. Como `local_backend.py`, el script conecta a `127.0.0.1` con `DB_PORT`, `POSTGRES_DB`, `POSTGRES_USER` y `POSTGRES_PASSWORD` del archivo. `--dry-run` consulta la base en modo de solo lectura. La carga genera su propio respaldo `backups/geocattle-validacion-*.dump` mediante `pg_dump` antes de escribir y confirma todo el lote en una transacción. Repetir el mismo destino y `--seed` informa cero cambios. Otra semilla carga otro lote de 40. Usa el `pg_dump` incluido en el prototipo Windows o un cliente local compatible con la versión del servidor. [Operación y respaldos](OPERACION.md#respaldo-y-recuperación)

### Windows nativo

Ejecuta desde la raíz. Sustituye el correo ficticio por el de un dueño con cupo o administrador de la base elegida. Para QA, apunta `$cfg` al archivo de la base aislada en lugar de `.env.academic`.

```powershell
$cfg = '.env.academic'
$autor = 'dueno@example.test'
$seedTool = 'scripts/seed_validation_data.py'
$seedPython = '.\.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $seedPython)) { $seedPython = '.\backend\.venv\Scripts\python.exe' }
& $seedPython -X utf8 $seedTool --env-file $cfg --backup-only
& $seedPython -X utf8 $seedTool --env-file $cfg --actor-email $autor --dry-run
& $seedPython -X utf8 $seedTool --env-file $cfg --actor-email $autor
```

Para limpiar la carga completa, recupera el respaldo anterior a la carga en una base nueva. El historial V3 es inmutable. Usa el archivo `.dump` que indicó la carga, en el mismo servidor y con el mismo archivo de configuración.

```powershell
$dump = 'backups/geocattle-validacion-REEMPLAZAR.dump'
$destino = 'geocattle_restore_validacion_' + [Guid]::NewGuid().ToString('N').Substring(0,12)
$pg = '.runtime/postgres16/pgsql/bin'
$pgConfig = @{}
Get-Content -LiteralPath $cfg | ForEach-Object {
    if ($_ -match '^(DB_PORT|POSTGRES_USER|POSTGRES_PASSWORD)=(.*)$') {
        $pgConfig[$Matches[1]] = $Matches[2]
    }
}
$conexion = @('-h', '127.0.0.1', '-p', $pgConfig.DB_PORT, '-U', $pgConfig.POSTGRES_USER)
$env:PGPASSWORD = $pgConfig.POSTGRES_PASSWORD
try {
    & "$pg/createdb.exe" @conexion $destino
    if ($LASTEXITCODE) { throw 'No se creó la base de restauración' }
    & "$pg/pg_restore.exe" @conexion --dbname $destino --exit-on-error --single-transaction $dump
    if ($LASTEXITCODE) { throw 'Falló la restauración' }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
```

### Docker Compose

Ejecuta desde el anfitrión con el servicio `database` levantado. El puerto publicado por Compose se toma de `DB_PORT` en el mismo archivo usado para arrancar el proyecto. El ejemplo usa el entorno de desarrollo `.env.docker`. En simulación usa su archivo privado y solo `compose.yaml`. En Windows puedes ejecutar los comandos PowerShell anteriores cambiando `$cfg` al archivo de Compose.

```bash
geocattle_cfg=.env.docker
geocattle_actor=dueno@example.test
backend/.venv/bin/python scripts/seed_validation_data.py --env-file "$geocattle_cfg" --backup-only
backend/.venv/bin/python scripts/seed_validation_data.py --env-file "$geocattle_cfg" --actor-email "$geocattle_actor" --dry-run
backend/.venv/bin/python scripts/seed_validation_data.py --env-file "$geocattle_cfg" --actor-email "$geocattle_actor"
```

Para recuperar la base previa desde el contenedor, usa el `.dump` que indicó la carga.

```bash
geocattle_dump=backups/geocattle-validacion-REEMPLAZAR.dump
geocattle_restore="geocattle_restore_validacion_$(date -u +%Y%m%d%H%M%S)_${RANDOM}"
docker compose --env-file "$geocattle_cfg" -f compose.yaml -f compose.usb.yaml exec -T database sh -c '
  export PGPASSWORD="$POSTGRES_PASSWORD"
  createdb --username="$POSTGRES_USER" "$1" &&
  pg_restore --username="$POSTGRES_USER" --dbname="$1" --exit-on-error --single-transaction
' sh "$geocattle_restore" < "$geocattle_dump"
```

La copia representa el instante del respaldo. Verifica sus conteos y los datos preexistentes antes de utilizarla como base de reemplazo. [Operación y recuperación](OPERACION.md#respaldo-y-recuperación)

### Prueba automatizada

Con `DATABASE_URL` y `TEST_DATABASE_URL` apuntando a la misma base QA migrada, ejecuta `python -m pytest backend/tests/test_seed_validation_data.py -q` desde la raíz y en el entorno Python del backend. También puedes usar la suite de `scripts/local_backend.py test --env-file RUTA_QA`. Las pruebas comprueban el listado, la ficha y los reportes por API y revierten sus datos al finalizar. Incluyen el destino con y sin geocerca, la protección ante destinos no autorizados y fallos del respaldo, y la repetición de la carga.

## Interfaz

```bash
cd frontend
npm ci
npm run build
```

La comprobación TypeScript forma parte de `build`. Los archivos de `frontend/dist/` y las dependencias se generan localmente y no se incluyen en esta publicación.

## Evidencia visual y funcional

- [Mapas, asociaciones y perfiles](REVISION_MAPAS_ASOCIACIONES_PERFILES.md): permisos, vigencias, reasignación y geocercas.
- [Registro mediante el dueño](USUARIOS_Y_REGISTRO.md): cuenta nueva, cuenta existente y enlace inválido.
- [Parámetros de alertas](CONFIGURACION_ALERTAS.md): dueño/administrador, persistencia, conflicto 409 y recarga sin sobrescritura.
- [Implementación V3](IMPLEMENTACION_V3.md): comprobaciones históricas y alcance previo; sus cifras corresponden a su fecha, no sustituyen la suite actual.

## Límites

Pasar las pruebas de software no acredita cobertura radio, GPS continuo, autonomía, calibración sanitaria, capacidad de 70 collares, disponibilidad prolongada ni aceptación del productor. La captura física probada es LoRa punto a punto y no certifica LoRaWAN.

La simulación y los datos físicos siguen separados. Los registros originales, secretos y lecturas reales se conservan localmente y quedan excluidos de Git.
