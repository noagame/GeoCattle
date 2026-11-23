# Base de datos

## Propósito y alcance

`migrations/` define el esquema PostgreSQL/PostGIS que aplica [`migrate.py`](../backend/geocattle/migrate.py). `tests/verify_v3_integrity.py` comprueba invariantes de persistencia V3.

## Contratos locales

- Las migraciones se ordenan por nombre y quedan registradas en `schema_migrations`. Añade un SQL numerado con nombre único y conserva las migraciones desplegadas.
- Al cambiar tablas o relaciones revisa restricciones, índices, privilegios de `geocattle_app`, historial y compatibilidad con filas existentes. Los modelos del backend y los diagramas documentan el esquema que aplican las migraciones.
- `support_requests` conserva casos privados por cuenta, con respuesta, estado y lectura del solicitante. La migración 007 recupera los folios de cierre pendientes y sus motivos a partir de los registros históricos.
- `invitation_mail` registra hasta un correo de cada tipo por invitación. El token cifrado pertenece al correo de invitación pendiente y se retira al finalizar su procesamiento.
- `011_gateway_candidates.sql` agrega `node_id` y `node_linked_at` a `gateways` (nodo único por predio entre gateways vigentes; EUI o nodo obligatorio), la tabla `gateway_candidates` con una sola reserva de nodo por predio, y `gateway_bus_receipts` para deduplicar detecciones por radio.
- `device_candidates` mantiene una detección pendiente por hardware y predio. Sus resoluciones conservan el actor y vinculan las aprobaciones con un dispositivo del mismo predio. `device_candidate_captures` conserva los recibos de deduplicación de las tramas detectadas.
- La migración 010 vincula los desafíos TOTP al factor que les corresponde y permite exigir una inscripción antes de abrir sesión tras una recuperación o un retiro obligatorio. Los cambios conservan los factores activos y cierran los desafíos de acceso e inscripción emitidos antes de la migración.

## Verificación

Desde la raíz, ejecuta `python database/tests/verify_v3_integrity.py` con `V3_TEST_DATABASE_URL` apuntando a una base QA migrada. Repite las pruebas de [integración](../backend/tests/AGENTS.md) que cubran el cambio.
