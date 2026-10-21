# Migración de la base implementada a GeoCattle V3

Fecha: 21 de octubre de 2026. Motor: PostgreSQL 16 con PostGIS. La fuente ejecutable es `database/migrations/003_application_v3.sql`; `docs/especificacion-v3/MODELO_FISICO_V3.sql` sigue siendo el diseño independiente para revisión y no debe ejecutarse sobre la base existente.

## Aplicación y conservación

1. Crear un respaldo completo con `scripts/backup.sh` y verificar que corresponda al ambiente que se va a actualizar.
2. Ejecutar el migrador existente: `python -m geocattle.migrate`, con `DATABASE_URL` del usuario de migración y `APP_DATABASE_PASSWORD` suministrados por la configuración privada. En Docker se utiliza el servicio `migrate` de `compose.yaml`.
3. Si el predio y los usuarios se aprovisionaron con `seed` o `bootstrap` después de aplicar 003, ejecutar `python -m geocattle.seed_v3` para conciliar las referencias V3.
4. Iniciar la API y el worker con el usuario restringido `geocattle_app` y revisar la versión de migración y los paneles de los cuatro perfiles.

El migrador aplica todas las versiones pendientes en una transacción y utiliza un bloqueo asesor para serializar ejecuciones. `schema_migrations` evita repetir versiones ya aplicadas. La migración agrega columnas, tablas, índices, vistas y restricciones en `public`; no elimina tablas ni recrea la base. Mantiene las claves UUID, credenciales y registros históricos existentes. Si una restricción impide completar la migración, la transacción revierte el conjunto.

Para revertir una instalación ya confirmada se necesita restaurar el respaldo en una base separada y verificarlo antes de cambiar la conexión; no se incluye un `DROP` automático de las tablas V3 porque perdería datos creados después de la actualización.

## Cambios efectivos y compatibilidad

La base tiene 48 tablas de aplicación; este conteo excluye `schema_migrations` y `spatial_ref_sys`.

| Área | Cambios |
|---|---|
| Identidad | `users` conserva `username`, `role`, `active` y `farm_id`. Agrega `email`, `full_name`, `phone`, `version`, fechas de creación/actualización/verificación. `farm_id` admite NULL para administrador o dueño sin predio. |
| Roles | `admin`, `owner`, `worker`, `veterinarian`; se conservan `operator` y `viewer` para identidades V1. Catálogos `roles`, `permissions`, `role_permissions`. |
| Clientes y alcance | `owner_accounts`, `farm_memberships`, `invitations`; `farms.account_id`, RUP, dirección, región, comuna, límite espacial, estado y creación. |
| Seguridad | `mfa_factors`, `mfa_recovery_codes`, `auth_challenges`, `account_tokens`, `platform_admins`; sesiones con predio activo, fechas MFA/step-up, autenticación, actividad y revocación. |
| Bovinos | Datos de especie, raza, color, sexo, nacimiento, tipo productivo, estado vital y versión; `animal_holdings`, `animal_measurements`, `animal_reports`. |
| Sectores y geocercas | Uso de suelo, descripción y estado; nuevas geocercas requieren cuatro vértices distintos, cierre, sin huecos y geometría válida. Las coordenadas se modifican mediante una versión nueva. |
| Hardware | Inventario ampliado de collares; `gateways` y `telemetry_receptions` separan el collar de las antenas y sus recepciones. |
| Cambios revisables | `change_requests`, `change_decisions`, `change_applications`, `trust_grants`. La propuesta pendiente no modifica la ficha efectiva. |
| Salud | `health_events`, `health_treatments`, `health_schedules` inmutables, con corrección/anulación/completado por sucesor. |
| Avisos y trazas | Notificaciones admiten solicitud/agenda y destinatario; auditoría admite alcance global o cliente; `request_metrics` registra metadatos técnicos sin cuerpos ni secretos. |
| Módulos | `features`, `farm_features` distinguen módulos de software de collares físicos. |
| FMA | `sag_movements`, `movement_animals`, `movement_status_events` conservan el soporte de datos para la extensión de movimientos; la existencia de estas tablas no certifica conexión oficial con SIPEC. |

`health_events` y `health_schedules` identifican al bovino mediante `animal_holding_id`, que referencia `animal_holdings(animal_id,farm_id)`. No tienen una columna `animal_id` redundante. `maintenance` conserva la fecha `at`; `audit_log` conserva `at`, `object_type`, `object_id`, `before` y `after`. Estos nombres mantienen compatibles los servicios V1.

`auth_challenges` usa `session_token_hash`, porque la PK original de `login_sessions` es `token_hash`. Los tokens de invitación y retos se guardan con hash; `mfa_factors.protected_data` es `bytea` y recibe únicamente material cifrado por la aplicación con clave externa.

## Backfill

- Se normaliza el correo a partir de `username` cuando contiene `@` y no entra en conflicto con otra identidad; los duplicados por diferencias de mayúsculas conservan su `username` y dejan el nuevo `email` sin completar para revisión.
- Se crea una cuenta por dueño existente. Cada predio con dueño identificado se enlaza de forma determinista por nombre de usuario e ID. Si varios dueños estaban asociados al mismo predio legado, uno queda como titular de la cuenta y todos conservan membresía; se debe revisar ese caso antes de operar una organización compartida.
- Se crean membresías para usuarios del predio. El conciliador posterior nunca reabre ni recrea una membresía que ya tenga historia, aunque se encuentre revocada. `operator` se conserva en `users.role` y se representa como `worker` en la nueva membresía; `viewer` permanece de solo consulta.
- Se agrega una permanencia por animal desde el menor inicio conocido entre creación, asignaciones, pastoreo y telemetría; se enlazan las asignaciones históricas.
- Se habilitan por defecto únicamente los módulos `monitoring`, `health` y `approvals`; `fma` permanece como catálogo de extensión sin habilitación automática.
- Se conserva el tipo productivo derivado de la orientación ya registrada y el inventario de collares utiliza el identificador de hardware existente como número de serie inicial.
- Los predios sin un dueño identificable conservan `account_id=NULL`; el conciliador informa `farms_pending_owner`. El administrador debe resolver su titular antes de utilizarlos como una cuenta cliente V3.

Las nuevas altas V3 deben crear explícitamente la permanencia del animal y asociar las asignaciones de collar/pastoreo con ella. Los campos de permanencia en asignaciones admiten NULL para datos o integraciones V1; las exclusiones de intervalos y FK de predio originales siguen vigentes. La ruta V1 de mantenimiento conserva registros sin solicitud para compatibilidad; la nueva ruta revisable aporta `request_id`.

## Alta inicial del administrador

Ejecutar `python -m geocattle.seed_v3 --admin-email correo --admin-name nombre`, proporcionando `V3_ADMIN_PASSWORD` por el entorno privado. El comando exige al menos 12 caracteres, no muestra la contraseña, no la incluye en archivos generados y no modifica cuentas ya existentes. Una identidad existente con otro rol no se eleva automáticamente.

La cuenta administrativa se crea sin predio; debe completar el enrolamiento MFA de la aplicación antes de acceder al panel. El script no inventa factores TOTP ni genera usuarios de prueba en la instalación real.

## Integridad y pruebas reproducibles

- Una cuenta no excede su cupo de predios activos; se bloquea la cuenta al comprobarlo para serializar altas concurrentes.
- Membresías y asignaciones usan intervalos semiabiertos y exclusiones contra superposición.
- Una decisión es única por solicitud y una aplicación es única por decisión. Una restricción diferida exige que las decisiones aprobadas/directas tengan aplicación en la misma transacción; las rechazadas no pueden aplicarse.
- El veterinario puede aplicar ficha técnica, salud y agenda directamente; el trabajador necesita revisión o una concesión vigente para la acción precisa. La base comprueba actor, membresía, predio, alcance y decisión además de las comprobaciones HTTP.
- Un evento sanitario solo es efectivo si no fue sustituido; una anulación conserva el original. Los índices impiden dos sucesores para el mismo registro.
- Las tablas históricas tienen triggers de inmutabilidad y el rol de ejecución carece de `UPDATE` y `DELETE` en ellas. El usuario de ejecución no es dueño del esquema ni puede modificar las migraciones.

Prueba SQL de integridad, con una conexión exclusiva de prueba:

```bash
V3_TEST_DATABASE_URL=postgresql://usuario@localhost:puerto/base_pruebas \
  python database/tests/verify_v3_integrity.py
```

El verificador revierte todos sus datos. En un contenedor PostGIS 16 desechable se verificaron: actualización desde datos V1 conservando IDs/roles/credenciales y sus enlaces; instalación fresca e idempotencia del migrador; lectura ORM de campos V1/V3; dos conciliaciones consecutivas sin duplicados; 23 comprobaciones SQL positivas/negativas y permisos de inmutabilidad del rol runtime en 12 tablas representativas. Las pruebas HTTP se mantienen por separado en `backend/tests`.

La actualización no convierte telemetría a TimescaleDB: conserva las claves, deduplicación y referencias actuales. La tabla de métricas tampoco reemplaza un monitor externo de CPU, RAM y disco, ni demuestra por sí sola las metas de rendimiento/disponibilidad del piloto.
