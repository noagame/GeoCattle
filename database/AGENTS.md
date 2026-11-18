# Base de datos

## Propósito y alcance

`migrations/` define el esquema PostgreSQL/PostGIS que aplica [`migrate.py`](../backend/geocattle/migrate.py). `tests/verify_v3_integrity.py` comprueba invariantes de persistencia V3.

## Contratos locales

- Las migraciones se ordenan por nombre y quedan registradas en `schema_migrations`. Añade un SQL numerado con nombre único y conserva las migraciones desplegadas.
- Al cambiar tablas o relaciones revisa restricciones, índices, privilegios de `geocattle_app`, historial y compatibilidad con filas existentes. Los modelos del backend y los diagramas documentan el esquema que aplican las migraciones.

## Verificación

Desde la raíz, ejecuta `python database/tests/verify_v3_integrity.py` con `V3_TEST_DATABASE_URL` apuntando a una base QA migrada. Repite las pruebas de [integración](../backend/tests/AGENTS.md) que cubran el cambio.
