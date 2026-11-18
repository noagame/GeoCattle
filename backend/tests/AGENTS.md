# Pruebas del backend

## Propósito y alcance

Pytest cubre reglas, configuración, autenticación y API. `test_rules.py` es la comprobación de dominio sin PostgreSQL que usa CI. `test_integration.py` y las suites V3 ejercitan el esquema y las operaciones con una base migrada.

## Contratos locales

- Para pruebas con persistencia usa datos ficticios y verifica el destino antes de ejecutar fixtures. La base QA debe ser PostgreSQL/PostGIS dedicada, migrada y seleccionada de forma explícita.
- Si ejecutas pytest fuera de `local_backend.py`, apunta `TEST_DATABASE_URL` y `DATABASE_URL` a la misma base QA. Comprueba los tests omitidos antes de dar por cubierta la integración.

## Verificación

Desde `backend/`, `uv run pytest tests/test_rules.py -q`. Para integración usa `scripts/local_backend.py test --env-file RUTA_QA` desde la raíz con el intérprete de la plataforma. [Verificación](../../docs/VERIFICACION.md)
