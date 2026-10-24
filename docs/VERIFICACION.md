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
python3 scripts/local_backend.py test
```

El wrapper conserva la prohibición de probar mediante esa ruta sobre development/production. La ejecución de publicación usó una base QA previamente preparada y variables exclusivas de ese proceso. No se cambió la configuración del servidor operativo.

`qa/test_hardware_api.py` es una suite adicional de cuatro comprobaciones PostgreSQL que se omite por defecto. Requiere `GEOCATTLE_TEST_DATABASE=1`, esquema y cuenta de fixture preparados. Sus verificaciones anteriores están documentadas en [Visualización de telemetría](VISUALIZACION_TELEMETRIA.md); no forman parte de las 26 pruebas de adaptadores indicadas arriba.

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
