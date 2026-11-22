# Pruebas del backend

## Propósito y alcance

Pytest cubre reglas, configuración, autenticación y API. `test_rules.py` es la comprobación de dominio sin PostgreSQL que usa CI. `test_integration.py` y las suites V3 ejercitan el esquema y las operaciones con una base migrada.

## Contratos locales

- Para pruebas con persistencia usa datos ficticios y verifica el destino antes de ejecutar fixtures. La base QA debe ser PostgreSQL/PostGIS dedicada, migrada y seleccionada de forma explícita.
- Si ejecutas pytest fuera de `local_backend.py`, apunta `TEST_DATABASE_URL` y `DATABASE_URL` a la misma base QA. Comprueba los tests omitidos antes de dar por cubierta la integración.
- `test_v3_animal_reports.py` comprueba que Excel y CSV respetan los filtros, permisos y topes. `test_report_exports.py` comprueba tipos y escape sin PostgreSQL. Ambos inspeccionan los libros con openpyxl (extra `test`).
- `test_v3_api.py` comprueba detección académica, reentrega, aprobación y descarte. Para los casos físicos cambia el entorno de los predios ficticios dentro de su transacción QA.
- Usa `development_v3` para casos que verifican una política exclusiva de desarrollo. En los casos que también se ejecutan en simulación, selecciona la fuente de telemetría por entorno y usa un entorno distinto del activo al probar el aislamiento.
- `test_invitation_mail.py` verifica el comando SMTP por STARTTLS y el envío desde la cola por TLS implícito, con un servidor efímero en loopback. `test_v3_account.py` verifica reemplazo, retiro y restablecimiento TOTP con PostgreSQL de QA.
- `test_seed_validation_data.py` comprueba conteos, autoría, idempotencia y acceso por API en dos predios ficticios. Verifica las restricciones diferidas y revierte los datos al terminar. La prueba externa de `pg_dump` y restauración se ejecuta por consola. [Verificación](../../docs/VERIFICACION.md#carga-de-un-rebaño-de-validación)

## Verificación

Desde `backend/`, `uv run pytest tests/test_rules.py -q`. Para integración usa `scripts/local_backend.py test --env-file RUTA_QA` desde la raíz con el intérprete de la plataforma. [Verificación](../../docs/VERIFICACION.md)
