# Pruebas del backend

## Propósito y alcance

Pytest cubre reglas, configuración, autenticación y API. `test_rules.py` es la comprobación de dominio sin PostgreSQL que usa CI. `test_integration.py` y las suites V3 ejercitan el esquema y las operaciones con una base migrada.

## Contratos locales

- Para pruebas con persistencia usa datos ficticios y verifica el destino antes de ejecutar fixtures. La base QA debe ser PostgreSQL/PostGIS dedicada, migrada y seleccionada de forma explícita.
- Si ejecutas pytest fuera de `local_backend.py`, apunta `TEST_DATABASE_URL` y `DATABASE_URL` a la misma base QA. Comprueba los tests omitidos antes de dar por cubierta la integración.
- `test_v3_animal_reports.py` comprueba que Excel y CSV respetan los filtros, permisos y topes. `test_report_exports.py` comprueba tipos y escape sin PostgreSQL. Ambos inspeccionan los libros con openpyxl (extra `test`).
- `test_owner_exports.py` verifica sin PostgreSQL el cálculo de K01–K12, fechas, roles y formatos de la exportación del dueño.
- `test_v3_api.py` comprueba detección académica, reentrega, aprobación y descarte, y la auditoría de la primera detección y del origen del alta. `test_v3_admin_filters.py` cubre los filtros de auditoría y su exportación Excel/CSV por ámbito. Para los casos físicos cambia el entorno de los predios ficticios dentro de su transacción QA.
- `test_auth_headers.py` comprueba el rechazo de credenciales de captura y CSRF ausentes o inválidas, incluidos bytes no ASCII, y el límite de intentos de inicio de sesión. `test_rules.py` verifica que la calidad de las lecturas sea JSON finito y acotado.
- Usa `development_v3` para casos que verifican una política exclusiva de desarrollo. En los casos que también se ejecutan en simulación, selecciona la fuente de telemetría por entorno y usa un entorno distinto del activo al probar el aislamiento.
- `test_invitation_mail.py` verifica el comando SMTP por STARTTLS y el envío desde la cola por TLS implícito, con un servidor efímero en loopback. `test_v3_account.py` verifica reemplazo, retiro y restablecimiento TOTP con PostgreSQL de QA.
- `test_seed_validation_data.py` comprueba conteos, autoría, idempotencia y acceso por API en dos predios ficticios. Verifica las restricciones diferidas y revierte los datos al terminar. La prueba externa de `pg_dump` y restauración se ejecuta por consola. [Verificación](../../docs/VERIFICACION.md#carga-de-un-rebaño-de-validación)
- `test_v3_platform_metrics.py` comprueba la autorización del predio de demostración desde desarrollo, su exclusión de los KPI agregados y el cupo de predios, y el acceso explícito a sus métricas.
- `test_gateway_candidates.py` verifica detecciones USB y por radio, reserva y confirmación de nodo, conflictos de EUI y nodo, permisos y la atribución de recepciones al gateway vinculado.
- `test_mirror_policy.py` verifica configuración, lista de rutas y aislamiento de identidad sin PostgreSQL. `test_mirror_mode.py` usa el rol restringido y una transacción de QA para probar MFA, bandeja, reproducción, autoría y conflictos encadenados. Su migrador requiere permisos para gestionar `geocattle_app` en la instancia aislada.
- `test_usb_receiver_mirror.py` comprueba la publicación USB por predio, la idempotencia del snapshot y su vigencia en la API del espejo con PostGIS de QA. Los casos de archivo ausente o ilegible y del worker en réplica se pueden ejecutar sin base.
- Para soporte del espejo, `test_mirror_mode.py` verifica sesión, CSRF, MFA de administrador, privacidad, autoría y reentrega del mismo folio.
- `test_production_security.py` verifica documentación, CORS y dependencias de autenticación sin base. Con PostgreSQL de QA verifica la cookie segura, CSRF al cerrar sesión, vencimiento y protección de la bandeja y la auditoría del espejo. `test_v3_account.py` verifica que cambiar o restablecer la contraseña consume los desafíos pendientes.

## Verificación

`test_collar_lifecycle.py` comprueba desvinculación y bordes temporales, autorización, la cantidad de consultas SQL del inventario, retiro/reactivación y eliminación sin historial, incluida la deduplicación de candidatos. Usa PostgreSQL/PostGIS de QA.

Desde `backend/`, `uv run pytest tests/test_rules.py -q`. Para integración usa `scripts/local_backend.py test --env-file RUTA_QA` desde la raíz con el intérprete de la plataforma. [Verificación](../../docs/VERIFICACION.md)
