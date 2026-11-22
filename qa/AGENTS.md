# QA transversal

## Propósito y alcance

Pruebas de arranque, portabilidad, contratos seriales, adaptadores, ingesta y hardware API. Los scripts de humo y fixtures también viven aquí. `v3/` agrupa evidencias de la verificación V3 y su script de humo.

## Contratos locales

- Las pruebas de contrato usan entradas ficticias y servicios de prueba. Para una prueba con PostgreSQL usa una base QA aislada. `test_hardware_api.py` exige `GEOCATTLE_TEST_DATABASE=1`, `TEST_DATABASE_URL`, esquema migrado y fixtures.
- `test_register_collar_usb.py` comprueba la identificación y el POST de detección. `test_lora_usb.py` y `test_academic_bridge.py` verifican el recibo de candidato en las colas de captura.
- `test_mqtt_ingestion.py` requiere un broker local con autenticación y una API de simulación de QA. La lectura encolada precede a la lectura reciente y pertenece a la asignación vigente del bovino ficticio.
- Antes de ejecutar pruebas de humo o preparar usuarios, verifica a qué instancia apuntan. Conserva el origen y el alcance de las evidencias archivadas.

## Verificación

Ejecuta desde la raíz los módulos pertinentes con `python -m unittest` en el entorno de [CI](../.github/workflows/validacion.yml). Para comprobaciones que usan base sigue [Verificación](../docs/VERIFICACION.md).
