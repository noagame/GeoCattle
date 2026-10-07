# Backend GeoCattle

Python 3.11+, FastAPI, SQLAlchemy/psycopg y PostgreSQL/PostGIS. La cola MQTT usa SQLite **sólo como spool**, nunca como base de aplicación. Las migraciones versionadas viven en `../database/migrations`; el comando usa transacción y bloqueo asesor. No hay sustituto SQLite para desarrollo/pruebas.

```sh
uv sync --extra test
uv run python -m geocattle.migrate
uv run python -m geocattle.bootstrap --username propietario@example.cl --farm "Mi predio"
uv run uvicorn geocattle.main:app --host 0.0.0.0 --port 8000
uv run python -m geocattle.worker
uv run python -m geocattle.ingestor
uv run pytest
```

El bootstrap exige `ADMIN_PASSWORD` con 12 caracteres o más. La demo exige `APP_ENV=simulation`, `SIMULATION_ENABLED=true`, `DEMO_PASSWORD` único de 12 caracteres y `python -m geocattle.seed`. Crea 70 animales con DIIO `SIM-*`, origen `sim`, 7 h de historia sintética; no equivale a prueba de campo ni a historial acumulado de 30 días. Usuario: `demo@geocattle.local`. Es idempotente y no cambia credenciales de una cuenta existente.

Variables: `DATABASE_URL` (postgresql+psycopg), `APP_ENV`, `SIMULATION_ENABLED`, `SESSION_SECRET`, `INGEST_KEY`, `COOKIE_SECURE`, `ALLOWED_ORIGINS` (coma), `SESSION_HOURS`, `DEMO_PASSWORD` (sólo simulation), `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPIC` (coma), `MQTT_ACK_TOPIC`, `MQTT_CLIENT_ID`, `MQTT_TLS`, `MQTT_SPOOL_PATH` (`/data/mqtt-spool.sqlite3`), `WORKER_INTERVAL_SECONDS`, `CONFIG_TIMEOUT_SECONDS`, `PREVENTIVE_RULES_VALIDATED` (false por defecto), `NOTIFICATION_WEBHOOK_URL`, `NOTIFICATION_WEBHOOK_TOKEN`, `NOTIFICATION_MAX_ATTEMPTS`, `NOTIFICATION_EXPIRY_HOURS`. No se registra ni muestra el secreto de ingestión o las contraseñas. Producción rechaza secretos de desarrollo, cookie sin Secure y DEMO_PASSWORD. Cada base debe contener predios de un solo entorno; simulation admite sólo sim y rechaza fuentes academic/lorawan.

API `/api/v1`, documentación `/api/docs`. Cookie HttpOnly, SameSite Lax y CSRF independiente. `owner` configura identidad/geocercas/reglas, `operator` y `owner` atienden eventos y registran mantenimiento, `viewer` consulta. Predio se obtiene del usuario. IDs ajenos responden 403. Ingestión `/ingest/telemetry` exige `X-Ingest-Key`. Los rangos de consulta requieren zona horaria y fin posterior al inicio.

Reglas: posición vigente ≤ 2T+30 s; comunicación reciente ≤ 3T+30 s. `worker` vigila silencio sin esperar nuevo paquete. ST_Covers incluye el borde; dos posiciones válidas consecutivas fuera generan salida, sin fix rompe la secuencia y nunca demuestra regreso. Datos atrasados completan historia sin retroceder estado ni renovar comunicación. Se preserva última posición válida con su hora. Condición técnica y atención humana son independientes; concluir atención no resuelve una salida activa. Toda acción y configuración relevante se audita. Las restricciones de la BD bloquean vigencias solapadas, asociación entre predios y mutación de telemetría/acciones/auditoría/mantenimiento.

Configuración guarda `requested`; no se presenta `sent` sin un downlink realmente transmitido. Este prototipo incluye un publicador opcional de downlinks: CONFIG_DOWNLINK_ENABLED=false por defecto. Activar requiere CONFIG_CODEC_VALIDATED=true, CHIRPSTACK_APPLICATION_ID y CONFIG_FPORT (10 por defecto), sólo fuera de simulation. PUBACK al broker registra sent y sent_at como envío a cola de red, nunca aplicación del módulo. Requiere codec externo y firmware físico validado. Contrato oficial: https://www.chirpstack.io/docs/chirpstack/integrations/mqtt.html. Sólo una telemetría nueva del módulo con `config_version` registrado confirma `applied`. El plazo sin confirmación abre `config_timeout`. Los sensores preventivos están deshabilitados por defecto; en ambientes reales, habilitarlos exige `PREVENTIVE_RULES_VALIDATED=true` después de validar montaje térmico y línea base/algoritmo de actividad. No diagnostican enfermedad. Proximidad usa geography en metros.

MQTT académico recibe el mismo objeto JSON v1 que HTTP. ChirpStack topic `application/+/device/+/event/up` requiere codec que produzca `object` con `schema_version`, `session_id`, `seq`, `observed_at` zonado y variables. DevEUI del envoltorio se cruza con el módulo; no se inventan tiempos ni sesiones a partir de la llegada. Habilite ambos tópicos con `MQTT_TOPIC`. El paquete se guarda con fsync/WAL antes de procesar. Acuse de aplicación `{status:"committed"}` y ack MQTT sólo tras commit PostgreSQL; fallo conserva cola. Datos inválidos quedan en cuarentena en el spool y no reciben acuse committed. QoS 1 y deduplicación BD toleran reentregas; un ack LoRaWAN no demuestra persistencia de aplicación. Integración física XBee/serial requiere el adaptador productor; no se simula como hardware real.

Avisos: outbox local transaccional y hasta tres intentos por defecto, backoff y expiración 24 h. Sin webhook no se llama a proveedores y se registra disabled. Una aceptación externa no prueba lectura humana. Configure URL HTTPS, credenciales y destinatario únicamente tras contratar y validar el canal. Ninguna prueba incluida envía un aviso real.

Informes: `/reports` resume capturas por período; `/reports/telemetry.csv` exporta hasta 50.000 observaciones por petición y explicita el límite. Historia paginada no borra datos. Política inicial del informe propone revisar retención de 30 días: no se automatiza borrado ni se promete acumulación inexistente.
