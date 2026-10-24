# Desarrollo local de GeoCattle

Estado de referencia: 23 de octubre de 2026. Esta carpeta queda dedicada al
software, la recepción de telemetría, sus pruebas y la documentación del proyecto.

## Ejecutar y detener

Abrir PowerShell en la raíz del proyecto y ejecutar:

```powershell
.\Iniciar-Prototipo.ps1
```

La instancia física usa http://localhost:8084/#hardware y PostgreSQL/PostGIS
local en el puerto 55434. La configuración privada está en `.env.academic` y
el acceso del prototipo en `.runtime/acceso_prototipo.json`. No incorporarlos a Git.

La T3 receptora utiliza COM5. Cerrar Monitor Serie/Plotter antes de abrir la
captura. Los datos del emisor llegan por LoRa; no es necesario conectar la
T-Beam al puerto de datos del PC.

```powershell
# Solo si la captura no está ya activa, para verla en primer plano:
.\Iniciar-Captura-COM5.ps1

# Liberar COM5 sin apagar la aplicación:
.\Pausar-Captura-COM5.ps1

# Reiniciar API y comprobar captura después de actualizar software:
.\Actualizar-Visualizacion.ps1

# Reiniciar todos los servicios del prototipo:
.\Reiniciar-Prototipo.ps1

# Cerrar conservando base y capturas:
.\Detener-Prototipo.ps1
```

La instancia Docker de simulación documentada en el README es otro entorno.
No ejecutar su seed sobre la base física ni reemplazar `.env.academic` por
credenciales de simulación.

## Dónde agregar funcionalidades

| Área | Ubicación |
|---|---|
| Interfaz del prototipo | `frontend/src/HardwarePage.tsx` |
| Detalle de sensores | `frontend/src/TelemetryView.tsx` |
| Mapa | `frontend/src/Map.tsx` |
| API de hardware | `backend/geocattle/hardware_api.py` |
| Reglas de dominio e ingestión | `backend/geocattle/domain.py` |
| Modelos y validaciones API | `backend/geocattle/models.py`, `schemas.py` |
| Migraciones | `database/migrations/` |
| Decodificación JSON y captura COM5 | `adapters/lora_json.py`, `lora_usb.py` |
| Arranque local Windows | `scripts/prototype_windows.py` |
| Pruebas del contrato y puente | `qa/test_lora_json.py`, `test_lora_usb.py`, `test_esp32_contract.py` |
| Pruebas de consultas de hardware | `qa/test_hardware_api.py` |

El [contrato de integración](CONTRATO_API.md#captura-radio-json-v5) especifica los
campos del collar. El estado y las limitaciones de la demostración están en
[VISUALIZACION_TELEMETRIA.md](VISUALIZACION_TELEMETRIA.md). Conservar el aislamiento
por predio, la identidad collar/sesión/secuencia y el historial inmutable.

## Comprobar cambios

Las dependencias de aplicación se conservaron: `.venv/` y
`frontend/node_modules/`. También se conservó `frontend/dist/`, que sirve la
aplicación local.

```powershell
# Desde la raíz: pruebas sin necesitar placas ni escribir datos reales.
.\.venv\Scripts\python.exe -m unittest qa.test_lora_json qa.test_lora_usb qa.test_esp32_contract qa.test_academic_bridge

# Desde frontend: comprobar TypeScript y compilar la interfaz.
Set-Location frontend
npm run build
Set-Location ..
```

Si Node/npm no están en PATH, usar la instalación disponible en el equipo.
No se necesita reinstalar ni compilar firmware para ejecutar estas pruebas.
Después de compilar la interfaz, recargar el navegador con Ctrl+F5. Después de
cambiar Python de la API, ejecutar `Actualizar-Visualizacion.ps1`.

Las pruebas de `qa/test_hardware_api.py` se omiten por defecto: necesitan una
base PostgreSQL explícita y `GEOCATTLE_TEST_DATABASE=1`. Sus fixtures se revierten;
no sustituir esa reversión por borrados de capturas reales. Las pruebas generales
de integración del backend se deben ejecutar contra una base de simulación
separada, según `docs/VERIFICACION.md`.

## Datos y evidencia conservados

- `.runtime/capture/`: archivo diario JSONL, cola SQLite, confirmaciones y estado USB.
- `.runtime/pgdata-academic/`: datos PostgreSQL; `.runtime/postgres16/`: binarios activos.
- Logs de servicios, diagnósticos GPS, registros de compilación/carga y manifiestos históricos en `.runtime/`.
- Documentación, diagramas y fuentes canónicas en `docs/especificacion-v3/`.
- Informes de integración, almacenamiento, implementación, planificación y visualización.
- Código de aplicación y pruebas automatizadas; configuración, migraciones y herramientas de operación.

Respaldar PostgreSQL con `pg_dump`; no copiar su directorio de datos mientras
está escribiendo. No borrar toda `.runtime/`: contiene información del proyecto
y servicios necesarios. Los archivos privados y datos locales siguen excluidos
por `.gitignore`.

## Limpieza del 23 de octubre de 2026

Se retiraron del árbol del proyecto aproximadamente 939 MB de archivos:

- Sketches y utilidades de compilación, carga y diagnóstico de placas.
- Compilaciones de emisor y receptor, biblioteca Arduino local y cachés de herramientas.
- Instaladores PostgreSQL/PostGIS ya extraídos. Los binarios en uso permanecen.
Se conservaron **todos los archivos originales de GitHub**, incluidas las copias
documentales y el archivo de referencia `docs/planificacion/node_modules`. La
verificación final contra `origin/main` y el inventario Git no detectó archivos
originales ausentes. Solo se retiraron agregados locales posteriores al clonado.

La revisión automática rechazó el borrado directo, por lo que la retirada es
reversible. No se afirma haber liberado espacio del disco: los archivos se
movieron fuera de esta carpeta a:

```text
<carpeta-local-de-respaldo>\GeoCattle-retirados-2026-10-23
```

Los fuentes, scripts y documentos retirados también tienen un respaldo ZIP
verificado por SHA-256, sin credenciales ni base de datos:

```text
<carpeta-local-de-respaldo>\GeoCattle-respaldo-limpieza-2026-10-23.zip
```

El inventario y los hashes están en `.runtime/limpieza-2026-10-23.json` y en
`GeoCattle-limpieza-2026-10-23.json` junto a ese respaldo. Estos códigos son
históricos: no acreditan coincidir con la última versión cargada manualmente
en las placas. No restaurarlos ni volver a cargarlos como parte del arranque
del software. Si se retoma la programación del hardware, recuperar solo lo
necesario y validar primero la versión y las dependencias de Arduino.
