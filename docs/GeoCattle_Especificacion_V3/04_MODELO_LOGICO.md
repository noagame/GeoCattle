# GeoCattle V3 — Modelo lógico

Propuesta del 20 de octubre de 2026. La definición completa y exacta de tipos, nulabilidad y restricciones está en `MODELO_FISICO_V3.sql`. Este diccionario y el DDL se generan desde el mismo catálogo. No describe la base implementada.

`?` indica atributo opcional; PK/FK/UQ conservan su significado relacional. Los IDs UUID no sustituyen la autorización. Las redundancias `farm_id` y `animal_id` permiten FK compuestas y consultas históricas; no se editan independientemente.

## Decisiones de normalización

- Administrador de plataforma en `platform_admins`; dueño principal en `owner_accounts`; trabajador/veterinario en `farm_memberships`. Una identidad puede tener varios alcances, con contexto de sesión explícito.
- `owner_accounts` agrupa uno o varios predios y limita su creación; no implica planes comerciales ni cobro.
- La edad se calcula; peso y altura son mediciones temporales; el estado técnico del sensor se separa del estado vital del animal.
- Los puntos se representan por un polígono versionado. Se requieren cuatro vértices distintos más cierre; no hay una tabla editable duplicando el polígono.
- Una propuesta del trabajador se guarda en `change_requests`. Solo una aplicación confirmada cambia los datos efectivos.
- Salud, reportes, mediciones y mantenimiento son históricos. Corregir/anular crea nuevos registros, con trazabilidad.
- Las recepciones por gateway se separan de la lectura única del collar. RSSI/SNR corresponden a esa recepción.
- Módulo físico = collar (`devices`); módulo funcional = característica de software (`features`). Los KPIs los distinguen.
- La extensión FMA se conserva por el alcance previo, fuera del MVP de los cuatro perfiles.

## Identidad

### `users`

Cuenta global; correo normalizado; no se duplica por predio.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `email` | `text` | NOT NULL UNIQUE CHECK(email=lower(btrim(email)) AND position('@' in email)>1) |
| `password_hash` | `text` | NOT NULL |
| `full_name` | `text` | NOT NULL |
| `phone` | `text` | Opcional |
| `status` | `text` | NOT NULL DEFAULT 'invited' CHECK(status IN ('invited','active','suspended','closed')) |
| `email_verified_at` | `timestamptz` | Opcional |
| `version` | `bigint` | NOT NULL DEFAULT 1 CHECK(version>0) |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() |

### `platform_admins`

Administradores globales, independientes de clientes y predios.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `user_id` | `uuid` | PRIMARY KEY REFERENCES users(id) |
| `active` | `boolean` | NOT NULL DEFAULT true |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

### `mfa_factors`

Factores MFA; secretos cifrados por la aplicación con clave externa.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `user_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `kind` | `text` | NOT NULL CHECK(kind IN ('totp','webauthn')) |
| `credential_id` | `text` | Opcional |
| `protected_data` | `bytea` | NOT NULL |
| `verified_at` | `timestamptz` | Opcional |
| `revoked_at` | `timestamptz` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

### `mfa_recovery_codes`

Códigos de recuperación de un solo uso almacenados con hash.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `user_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `code_hash` | `text` | NOT NULL UNIQUE |
| `used_at` | `timestamptz` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

### `login_sessions`

Sesiones emitidas solo después de completar autenticación requerida.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `user_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `token_hash` | `text` | NOT NULL UNIQUE |
| `csrf_hash` | `text` | NOT NULL |
| `authenticated_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `mfa_verified_at` | `timestamptz` | Opcional |
| `expires_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `revoked_at` | `timestamptz` | Opcional |

Restricciones de relación: `CHECK(expires_at>authenticated_at)`.

### `security_challenges`

Retos MFA/step-up vinculados a sesión, propósito y operación; no contienen OTP en claro.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `session_id` | `uuid` | NOT NULL REFERENCES login_sessions(id) |
| `purpose` | `text` | NOT NULL |
| `operation_digest` | `text` | NOT NULL |
| `expires_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `verified_at` | `timestamptz` | Opcional |
| `consumed_at` | `timestamptz` | Opcional |
| `attempts` | `integer` | NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5) |

### `account_tokens`

Enlaces de verificación de correo/recuperación sin sesión previa; token de un solo uso con hash.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `user_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `purpose` | `text` | NOT NULL CHECK(purpose IN ('verify_email','reset_password','close_account')) |
| `token_hash` | `text` | NOT NULL UNIQUE |
| `pending_email` | `text` | Opcional |
| `expires_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `consumed_at` | `timestamptz` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

### `roles`

Catálogo: platform_admin, owner, worker, veterinarian. El alcance se materializa en tablas distintas.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `code` | `text` | PRIMARY KEY |
| `name` | `text` | NOT NULL |
| `scope` | `text` | NOT NULL CHECK(scope IN ('platform','account','farm')) |

### `permissions`

Catálogo de acciones autorizables.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `code` | `text` | PRIMARY KEY |
| `description` | `text` | NOT NULL |

### `role_permissions`

Permisos por rol; la confianza no agrega permisos, solo elimina revisión en acciones permitidas.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `role_code` | `text` | NOT NULL REFERENCES roles(code) |
| `permission_code` | `text` | NOT NULL REFERENCES permissions(code) |

Restricciones de relación: `PRIMARY KEY(role_code,permission_code)`.

## Predios

### `owner_accounts`

Cliente del sistema, administrado por un dueño principal.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `owner_user_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `display_name` | `text` | NOT NULL |
| `max_farms` | `integer` | NOT NULL DEFAULT 1 CHECK(max_farms>0) |
| `active` | `boolean` | NOT NULL DEFAULT true |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `UNIQUE(owner_user_id)`.

### `farms`

Predio perteneciente a una cuenta cliente.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `account_id` | `uuid` | NOT NULL REFERENCES owner_accounts(id) |
| `name` | `text` | NOT NULL |
| `rup` | `text` | UNIQUE |
| `address` | `text` | Opcional |
| `region` | `text` | Opcional |
| `commune` | `text` | Opcional |
| `timezone` | `text` | NOT NULL DEFAULT 'America/Santiago' |
| `boundary` | `geometry(MultiPolygon,4326)` | Opcional |
| `active` | `boolean` | NOT NULL DEFAULT true |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `UNIQUE(id,account_id)`; `CHECK(boundary IS NULL OR (ST_IsValid(boundary) AND NOT ST_IsEmpty(boundary) AND ST_Area(boundary)>0))`.

### `farm_memberships`

Acceso temporal de trabajador/veterinario; el dueño accede mediante su cuenta.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `user_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `role_code` | `text` | NOT NULL REFERENCES roles(code) CHECK(role_code IN ('worker','veterinarian')) |
| `granted_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `valid_from` | `timestamptz` | NOT NULL DEFAULT now() |
| `valid_to` | `timestamptz` | Opcional |

Restricciones de relación: `UNIQUE(id,farm_id)`; `CHECK(valid_to IS NULL OR valid_to>valid_from)`; `EXCLUDE USING gist (user_id WITH =,farm_id WITH =,tstzrange(valid_from,valid_to,'[)') WITH &&)`.

### `invitations`

Invitación por predio y rol; acceso solo al aceptar y verificar correo.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `email` | `text` | NOT NULL CHECK(email=lower(btrim(email))) |
| `role_code` | `text` | NOT NULL REFERENCES roles(code) CHECK(role_code IN ('worker','veterinarian')) |
| `token_hash` | `text` | NOT NULL UNIQUE |
| `invited_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `expires_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `accepted_at` | `timestamptz` | Opcional |
| `accepted_user_id` | `uuid` | REFERENCES users(id) |
| `revoked_at` | `timestamptz` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `CHECK((accepted_at IS NULL)=(accepted_user_id IS NULL))`.

### `trust_grants`

Exención de aprobación por trabajador y acción, revocable y con vigencia.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `membership_id` | `uuid` | NOT NULL REFERENCES farm_memberships(id) |
| `action` | `text` | NOT NULL CHECK(action IN ('animal_status','animal_report','health_record','battery_replacement')) |
| `granted_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `valid_from` | `timestamptz` | NOT NULL DEFAULT now() |
| `valid_to` | `timestamptz` | Opcional |

Restricciones de relación: `UNIQUE(id,farm_id)`; `FOREIGN KEY (membership_id,farm_id) REFERENCES farm_memberships(id,farm_id)`; `CHECK(valid_to IS NULL OR valid_to>valid_from)`; `EXCLUDE USING gist(membership_id WITH =,action WITH =,tstzrange(valid_from,valid_to,'[)') WITH &&)`.

## Ganado y espacio

### `sectors`

Sector/potrero del predio y su uso actual.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `name` | `text` | NOT NULL |
| `land_use` | `text` | NOT NULL CHECK(land_use IN ('grazing','available','cropped','restricted','other')) |
| `description` | `text` | Opcional |
| `active` | `boolean` | NOT NULL DEFAULT true |

Restricciones de relación: `UNIQUE(id,farm_id)`; `UNIQUE(farm_id,name)`.

### `geofences`

Versiones inmutables de límites; se cierra vigencia sin cambiar coordenadas.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `sector_id` | `uuid` | NOT NULL REFERENCES sectors(id) |
| `version` | `integer` | NOT NULL CHECK(version>0) |
| `geometry` | `geometry(Polygon,4326)` | NOT NULL |
| `created_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `valid_from` | `timestamptz` | NOT NULL DEFAULT now() |
| `valid_to` | `timestamptz` | Opcional |

Restricciones de relación: `UNIQUE(id,farm_id)`; `UNIQUE(sector_id,version)`; `FOREIGN KEY (sector_id,farm_id) REFERENCES sectors(id,farm_id)`; `CHECK(ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry) AND ST_Area(geometry)>0 AND ST_NumInteriorRings(geometry)=0 AND ST_NPoints(ST_ExteriorRing(geometry))>=5)`; `CHECK(valid_to IS NULL OR valid_to>valid_from)`; `EXCLUDE USING gist (sector_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&)`.

### `animals`

Identidad global del bovino; edad derivada de fecha de nacimiento.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `diio` | `text` | NOT NULL UNIQUE |
| `name` | `text` | Opcional |
| `species` | `text` | NOT NULL DEFAULT 'bovine' CHECK(species='bovine') |
| `breed` | `text` | Opcional |
| `color` | `text` | Opcional |
| `sex` | `text` | NOT NULL CHECK(sex IN ('female','male','unknown')) |
| `birth_date` | `date` | Opcional |
| `birth_date_estimated` | `boolean` | NOT NULL DEFAULT false |
| `production_type` | `text` | NOT NULL CHECK(production_type IN ('milk','meat','dual','other')) |
| `status` | `text` | NOT NULL DEFAULT 'active' CHECK(status IN ('active','missing','dead','slaughtered','retired')) |
| `version` | `bigint` | NOT NULL DEFAULT 1 CHECK(version>0) |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

### `animal_holdings`

Permanencia histórica del animal en un predio.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `animal_id` | `uuid` | NOT NULL REFERENCES animals(id) |
| `valid_from` | `timestamptz` | NOT NULL DEFAULT now() |
| `valid_to` | `timestamptz` | Opcional |
| `reason` | `text` | NOT NULL |

Restricciones de relación: `UNIQUE(id,farm_id)`; `UNIQUE(id,animal_id,farm_id)`; `CHECK(valid_to IS NULL OR valid_to>valid_from)`; `EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&)`.

## IoT

### `gateways`

Inventario de gateways y su ubicación; no se confunde con collar.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `gateway_eui` | `text` | NOT NULL UNIQUE CHECK(gateway_eui ~ '^[0-9a-f]{16}$') |
| `name` | `text` | NOT NULL |
| `position` | `geometry(Point,4326)` | Opcional |
| `status` | `text` | NOT NULL CHECK(status IN ('installed','maintenance','retired')) |
| `installed_at` | `timestamptz` | Opcional |
| `last_seen_at` | `timestamptz` | Opcional |

Restricciones de relación: `UNIQUE(id,farm_id)`.

### `devices`

Módulos físicos/collares; inventario independiente de asignación activa.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `serial_number` | `text` | NOT NULL UNIQUE |
| `dev_eui` | `text` | UNIQUE CHECK(dev_eui IS NULL OR dev_eui ~ '^[0-9a-f]{16}$') |
| `transport` | `text` | NOT NULL CHECK(transport IN ('academic','lorawan')) |
| `hardware_revision` | `text` | Opcional |
| `firmware_version` | `text` | Opcional |
| `status` | `text` | NOT NULL CHECK(status IN ('available','installed','maintenance','retired')) |
| `interval_seconds` | `integer` | NOT NULL DEFAULT 300 CHECK(interval_seconds BETWEEN 30 AND 86400) |
| `config_version` | `integer` | NOT NULL DEFAULT 0 CHECK(config_version>=0) |
| `last_observed_at` | `timestamptz` | Opcional |
| `last_received_at` | `timestamptz` | Opcional |

Restricciones de relación: `UNIQUE(id,farm_id)`.

### `assignments`

Historial de animal/collar sin duplicidad temporal.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `animal_holding_id` | `uuid` | NOT NULL REFERENCES animal_holdings(id) |
| `animal_id` | `uuid` | NOT NULL REFERENCES animals(id) |
| `device_id` | `uuid` | NOT NULL REFERENCES devices(id) |
| `assigned_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `valid_from` | `timestamptz` | NOT NULL DEFAULT now() |
| `valid_to` | `timestamptz` | Opcional |
| `reason` | `text` | Opcional |

Restricciones de relación: `UNIQUE(id,farm_id)`; `UNIQUE(id,device_id,farm_id)`; `FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id)`; `FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id)`; `CHECK(valid_to IS NULL OR valid_to>valid_from)`; `EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&)`; `EXCLUDE USING gist(device_id WITH =,tstzrange(valid_from,valid_to,'[)') WITH &&)`.

## Ganado y espacio

### `pasture_assignments`

Pastoreo temporal del animal en una versión de geocerca.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `animal_holding_id` | `uuid` | NOT NULL REFERENCES animal_holdings(id) |
| `animal_id` | `uuid` | NOT NULL REFERENCES animals(id) |
| `geofence_id` | `uuid` | NOT NULL REFERENCES geofences(id) |
| `assigned_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `valid_from` | `timestamptz` | NOT NULL DEFAULT now() |
| `valid_to` | `timestamptz` | Opcional |

Restricciones de relación: `FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id)`; `FOREIGN KEY (geofence_id,farm_id) REFERENCES geofences(id,farm_id)`; `CHECK(valid_to IS NULL OR valid_to>valid_from)`; `EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&)`.

## IoT

### `telemetry`

Lectura inmutable y deduplicada; atribución por instante de captura.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `device_id` | `uuid` | NOT NULL REFERENCES devices(id) |
| `assignment_id` | `uuid` | REFERENCES assignments(id) |
| `animal_id` | `uuid` | REFERENCES animals(id) |
| `session_id` | `text` | NOT NULL |
| `seq` | `bigint` | NOT NULL CHECK(seq>=0) |
| `observed_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `received_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `point` | `geometry(Point,4326)` | Opcional |
| `gnss_valid` | `boolean` | NOT NULL |
| `surface_temperature_c` | `numeric` | CHECK(surface_temperature_c BETWEEN -60 AND 100) |
| `activity_index` | `numeric` | CHECK(activity_index>=0) |
| `battery_mv` | `integer` | CHECK(battery_mv BETWEEN 0 AND 20000) |
| `source` | `text` | NOT NULL CHECK(source IN ('sim','academic','lorawan')) |
| `quality` | `jsonb` | NOT NULL DEFAULT '{}'::jsonb |

Restricciones de relación: `UNIQUE(id,farm_id)`; `UNIQUE(device_id,session_id,seq)`; `FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id)`; `FOREIGN KEY(assignment_id,device_id,farm_id) REFERENCES assignments(id,device_id,farm_id)`; `CHECK((assignment_id IS NULL)=(animal_id IS NULL))`; `CHECK((gnss_valid AND point IS NOT NULL) OR (NOT gnss_valid AND point IS NULL))`; `CHECK(point IS NULL OR (ST_X(point) BETWEEN -180 AND 180 AND ST_Y(point) BETWEEN -90 AND 90))`; `CHECK(observed_at<=received_at+interval '5 minutes')`.

### `telemetry_receptions`

Recepción de una lectura por gateway; varias antenas no duplican telemetría.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `telemetry_id` | `uuid` | NOT NULL REFERENCES telemetry(id) |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `gateway_id` | `uuid` | NOT NULL REFERENCES gateways(id) |
| `received_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `rssi_dbm` | `numeric` | Opcional |
| `snr_db` | `numeric` | Opcional |

Restricciones de relación: `PRIMARY KEY(telemetry_id,gateway_id)`; `FOREIGN KEY (telemetry_id,farm_id) REFERENCES telemetry(id,farm_id)`; `FOREIGN KEY (gateway_id,farm_id) REFERENCES gateways(id,farm_id)`.

## Operación

### `animal_states`

Proyección reconstruible, no historial clínico.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `animal_id` | `uuid` | PRIMARY KEY REFERENCES animals(id) |
| `telemetry_id` | `uuid` | REFERENCES telemetry(id) |
| `position_telemetry_id` | `uuid` | REFERENCES telemetry(id) |
| `geofence_status` | `text` | NOT NULL DEFAULT 'unknown' CHECK(geofence_status IN ('unknown','inside','outside','pending')) |
| `outside_count` | `integer` | NOT NULL DEFAULT 0 CHECK(outside_count>=0) |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() |

### `rule_settings`

Reglas configuradas por predio y auditadas.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `farm_id` | `uuid` | PRIMARY KEY REFERENCES farms(id) |
| `version` | `integer` | NOT NULL DEFAULT 1 CHECK(version>0) |
| `battery_low_mv` | `integer` | NOT NULL DEFAULT 3300 CHECK(battery_low_mv BETWEEN 0 AND 20000) |
| `temperature_enabled` | `boolean` | NOT NULL DEFAULT false |
| `temperature_high_c` | `numeric` | Opcional |
| `activity_enabled` | `boolean` | NOT NULL DEFAULT false |
| `activity_low_threshold` | `numeric` | Opcional |
| `activity_window_minutes` | `integer` | NOT NULL DEFAULT 30 CHECK(activity_window_minutes>0) |
| `proximity_enabled` | `boolean` | NOT NULL DEFAULT false |
| `proximity_meters` | `numeric` | CHECK(proximity_meters>=0) |
| `updated_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `updated_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `CHECK(NOT temperature_enabled OR temperature_high_c IS NOT NULL)`; `CHECK(NOT activity_enabled OR activity_low_threshold IS NOT NULL)`; `CHECK(NOT proximity_enabled OR proximity_meters IS NOT NULL)`.

### `events`

Alerta técnica; atender no implica resolver su condición.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `device_id` | `uuid` | NOT NULL REFERENCES devices(id) |
| `animal_id` | `uuid` | REFERENCES animals(id) |
| `telemetry_id` | `uuid` | REFERENCES telemetry(id) |
| `geofence_id` | `uuid` | REFERENCES geofences(id) |
| `type` | `text` | NOT NULL CHECK(type IN ('escape','communication_timeout','low_battery','high_surface_temperature','low_activity','proximity','config_timeout')) |
| `severity` | `text` | NOT NULL CHECK(severity IN ('warning','critical')) |
| `condition` | `text` | NOT NULL CHECK(condition IN ('active','resolved')) |
| `attention` | `text` | NOT NULL DEFAULT 'pending' CHECK(attention IN ('pending','acknowledged','in_review','concluded')) |
| `opened_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `resolved_at` | `timestamptz` | Opcional |
| `detail` | `jsonb` | NOT NULL DEFAULT '{}'::jsonb |

Restricciones de relación: `UNIQUE(id,farm_id)`; `FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id)`; `FOREIGN KEY (telemetry_id,farm_id) REFERENCES telemetry(id,farm_id)`; `FOREIGN KEY (geofence_id,farm_id) REFERENCES geofences(id,farm_id)`; `CHECK((condition='active' AND resolved_at IS NULL) OR (condition='resolved' AND resolved_at IS NOT NULL AND resolved_at>=opened_at))`.

### `event_actions`

Historial inmutable de atención de alertas.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `event_id` | `uuid` | NOT NULL REFERENCES events(id) |
| `actor_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `action` | `text` | NOT NULL CHECK(action IN ('acknowledge','review','conclude','reopen')) |
| `note` | `text` | NOT NULL |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `FOREIGN KEY (event_id,farm_id) REFERENCES events(id,farm_id)`.

## IoT

### `device_configs`

Ciclo solicitud/envío/confirmación de configuración.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `device_id` | `uuid` | NOT NULL REFERENCES devices(id) |
| `version` | `integer` | NOT NULL CHECK(version>0) |
| `interval_seconds` | `integer` | NOT NULL CHECK(interval_seconds BETWEEN 30 AND 86400) |
| `status` | `text` | NOT NULL CHECK(status IN ('requested','sent','applied','failed')) |
| `requested_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `requested_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `sent_at` | `timestamptz` | Opcional |
| `applied_at` | `timestamptz` | Opcional |
| `error` | `text` | Opcional |

Restricciones de relación: `UNIQUE(device_id,version)`; `FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id)`.

## Aprobaciones

### `change_requests`

Propuesta inmutable; los datos efectivos no cambian mientras esté pendiente.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `requested_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `membership_id` | `uuid` | REFERENCES farm_memberships(id) |
| `action` | `text` | NOT NULL CHECK(action IN ('animal_profile','animal_status','animal_report','health_record','battery_replacement','health_schedule')) |
| `animal_holding_id` | `uuid` | REFERENCES animal_holdings(id) |
| `animal_id` | `uuid` | REFERENCES animals(id) |
| `device_id` | `uuid` | REFERENCES devices(id) |
| `expected_version` | `bigint` | CHECK(expected_version>0) |
| `payload` | `jsonb` | NOT NULL CHECK(jsonb_typeof(payload)='object') |
| `idempotency_key` | `uuid` | NOT NULL |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `UNIQUE(id,farm_id)`; `UNIQUE(requested_by,idempotency_key)`; `FOREIGN KEY (membership_id,farm_id) REFERENCES farm_memberships(id,farm_id)`; `FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id)`; `FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id)`; `CHECK((animal_holding_id IS NULL)=(animal_id IS NULL))`; `CHECK((action='battery_replacement' AND device_id IS NOT NULL) OR (action<>'battery_replacement' AND animal_id IS NOT NULL))`.

### `change_decisions`

Decisión única e inmutable: revisión del dueño o aplicación directa autorizada.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `request_id` | `uuid` | PRIMARY KEY REFERENCES change_requests(id) |
| `decided_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `decision` | `text` | NOT NULL CHECK(decision IN ('approved','rejected','direct')) |
| `trust_grant_id` | `uuid` | REFERENCES trust_grants(id) |
| `reason` | `text` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `CHECK(decision<>'rejected' OR nullif(btrim(reason),'') IS NOT NULL)`.

### `change_applications`

Prueba única de aplicación efectiva, misma transacción que decisión y mutación.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `request_id` | `uuid` | PRIMARY KEY REFERENCES change_decisions(request_id) |
| `entity_type` | `text` | NOT NULL |
| `entity_id` | `uuid` | NOT NULL |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

## Salud

### `animal_measurements`

Peso/altura históricos; correcciones referencian medición previa.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `animal_holding_id` | `uuid` | NOT NULL REFERENCES animal_holdings(id) |
| `animal_id` | `uuid` | NOT NULL REFERENCES animals(id) |
| `request_id` | `uuid` | NOT NULL REFERENCES change_requests(id) |
| `measured_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `weight_kg` | `numeric` | CHECK(weight_kg>0) |
| `height_cm` | `numeric` | CHECK(height_cm>0) |
| `corrects_id` | `uuid` | REFERENCES animal_measurements(id) |

Restricciones de relación: `UNIQUE(id,farm_id)`; `FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id)`; `FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)`; `CHECK(weight_kg IS NOT NULL OR height_cm IS NOT NULL)`.

### `animal_reports`

Reporte del animal aplicado por dueño o trabajador autorizado.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `animal_holding_id` | `uuid` | NOT NULL REFERENCES animal_holdings(id) |
| `request_id` | `uuid` | NOT NULL REFERENCES change_requests(id) |
| `description` | `text` | NOT NULL |
| `occurred_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `FOREIGN KEY (animal_holding_id,farm_id) REFERENCES animal_holdings(id,farm_id)`; `FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)`.

### `health_events`

Versión clínica inmutable; CRUD se expresa mediante registro, corrección y anulación.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `animal_holding_id` | `uuid` | NOT NULL REFERENCES animal_holdings(id) |
| `request_id` | `uuid` | NOT NULL REFERENCES change_requests(id) |
| `event_type` | `text` | NOT NULL CHECK(event_type IN ('examination','vaccination','antibiotic','pathology','diagnosis','procedure','injury','death','observation')) |
| `operation` | `text` | NOT NULL CHECK(operation IN ('record','correct','void')) |
| `target_event_id` | `uuid` | REFERENCES health_events(id) |
| `occurred_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `recorded_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `description` | `text` | NOT NULL |
| `diagnosis` | `text` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `UNIQUE(id,farm_id)`; `FOREIGN KEY (animal_holding_id,farm_id) REFERENCES animal_holdings(id,farm_id)`; `FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)`; `FOREIGN KEY (target_event_id,farm_id) REFERENCES health_events(id,farm_id)`; `CHECK((operation='record' AND target_event_id IS NULL) OR (operation IN ('correct','void') AND target_event_id IS NOT NULL))`.

### `health_treatments`

Uno o varios fármacos/vacunas por evento.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `health_event_id` | `uuid` | NOT NULL REFERENCES health_events(id) |
| `product_name` | `text` | NOT NULL |
| `product_registration` | `text` | Opcional |
| `batch_number` | `text` | Opcional |
| `dose_value` | `numeric` | NOT NULL CHECK(dose_value>0) |
| `dose_unit` | `text` | NOT NULL |
| `route` | `text` | NOT NULL |
| `administered_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `withdrawal_meat_until` | `date` | Opcional |
| `withdrawal_milk_until` | `date` | Opcional |
| `withdrawal_basis` | `text` | Opcional |

Restricciones de relación: `FOREIGN KEY (health_event_id,farm_id) REFERENCES health_events(id,farm_id)`.

### `health_schedules`

Próxima vacuna/control/antibiótico planificado; planificación no equivale a administración.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `animal_holding_id` | `uuid` | NOT NULL REFERENCES animal_holdings(id) |
| `request_id` | `uuid` | NOT NULL REFERENCES change_requests(id) |
| `kind` | `text` | NOT NULL CHECK(kind IN ('vaccination','antibiotic','checkup')) |
| `description` | `text` | NOT NULL |
| `due_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `operation` | `text` | NOT NULL CHECK(operation IN ('plan','replace','cancel','complete')) |
| `target_schedule_id` | `uuid` | REFERENCES health_schedules(id) |
| `completed_event_id` | `uuid` | REFERENCES health_events(id) |
| `created_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `UNIQUE(id,farm_id)`; `FOREIGN KEY (animal_holding_id,farm_id) REFERENCES animal_holdings(id,farm_id)`; `FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)`; `FOREIGN KEY (target_schedule_id,farm_id) REFERENCES health_schedules(id,farm_id)`; `FOREIGN KEY (completed_event_id,farm_id) REFERENCES health_events(id,farm_id)`; `CHECK((operation='plan' AND target_schedule_id IS NULL) OR (operation<>'plan' AND target_schedule_id IS NOT NULL))`; `CHECK((operation='complete')=(completed_event_id IS NOT NULL))`.

## IoT

### `maintenance`

Mantenimiento efectivo inmutable; solicitud pendiente no cambia batería confirmada.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `device_id` | `uuid` | NOT NULL REFERENCES devices(id) |
| `request_id` | `uuid` | REFERENCES change_requests(id) |
| `responsible_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `kind` | `text` | NOT NULL CHECK(kind IN ('inspection','recharge','replacement','retirement')) |
| `battery_id` | `text` | Opcional |
| `result` | `text` | NOT NULL |
| `occurred_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id)`; `FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)`.

## Operación

### `notifications`

Cola de avisos por alerta, solicitud o agenda, con destinatario explícito.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `recipient_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `event_id` | `uuid` | REFERENCES events(id) |
| `request_id` | `uuid` | REFERENCES change_requests(id) |
| `schedule_id` | `uuid` | REFERENCES health_schedules(id) |
| `channel` | `text` | NOT NULL CHECK(channel IN ('in_app','email','external')) |
| `recipient_address` | `text` | Opcional |
| `status` | `text` | NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','failed','expired','read')) |
| `message` | `text` | NOT NULL |
| `next_attempt_at` | `timestamptz` | NOT NULL DEFAULT now() |
| `read_at` | `timestamptz` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `FOREIGN KEY (event_id,farm_id) REFERENCES events(id,farm_id)`; `FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)`; `FOREIGN KEY (schedule_id,farm_id) REFERENCES health_schedules(id,farm_id)`.

### `notification_attempts`

Intentos inmutables; aceptación externa no prueba lectura.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `notification_id` | `uuid` | NOT NULL REFERENCES notifications(id) |
| `attempt` | `integer` | NOT NULL CHECK(attempt>0) |
| `status` | `text` | NOT NULL |
| `provider_id` | `text` | Opcional |
| `error` | `text` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `UNIQUE(notification_id,attempt)`.

## Administración

### `audit_log`

Auditoría global o predial, con identidad del actor y contexto de sesión.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `account_id` | `uuid` | REFERENCES owner_accounts(id) |
| `farm_id` | `uuid` | REFERENCES farms(id) |
| `actor_id` | `uuid` | REFERENCES users(id) |
| `session_id` | `uuid` | REFERENCES login_sessions(id) |
| `actor_kind` | `text` | NOT NULL CHECK(actor_kind IN ('user','service')) |
| `action` | `text` | NOT NULL |
| `entity_type` | `text` | NOT NULL |
| `entity_id` | `uuid` | Opcional |
| `before_data` | `jsonb` | Opcional |
| `after_data` | `jsonb` | Opcional |
| `ip_address` | `inet` | Opcional |
| `request_id` | `text` | Opcional |
| `occurred_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `FOREIGN KEY(farm_id,account_id) REFERENCES farms(id,account_id)`; `CHECK(farm_id IS NULL OR account_id IS NOT NULL)`; `CHECK(actor_kind<>'user' OR actor_id IS NOT NULL)`.

### `request_metrics`

Métricas técnicas por petición; sin body, secretos ni query string.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `account_id` | `uuid` | REFERENCES owner_accounts(id) |
| `farm_id` | `uuid` | REFERENCES farms(id) |
| `actor_id` | `uuid` | REFERENCES users(id) |
| `request_id` | `text` | NOT NULL |
| `method` | `text` | NOT NULL |
| `route_template` | `text` | NOT NULL |
| `status_code` | `integer` | NOT NULL CHECK(status_code BETWEEN 100 AND 599) |
| `duration_ms` | `numeric` | NOT NULL CHECK(duration_ms>=0) |
| `request_bytes` | `bigint` | NOT NULL CHECK(request_bytes>=0) |
| `response_bytes` | `bigint` | NOT NULL CHECK(response_bytes>=0) |
| `occurred_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `FOREIGN KEY(farm_id,account_id) REFERENCES farms(id,account_id)`; `CHECK(farm_id IS NULL OR account_id IS NOT NULL)`.

### `features`

Catálogo de módulos funcionales de software, separado del hardware.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `code` | `text` | PRIMARY KEY |
| `name` | `text` | NOT NULL |

### `farm_features`

Módulos de software habilitados por predio; no es facturación.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `feature_code` | `text` | NOT NULL REFERENCES features(code) |
| `enabled` | `boolean` | NOT NULL DEFAULT true |
| `enabled_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `PRIMARY KEY(farm_id,feature_code)`.

## Extensión FMA

### `sag_movements`

Documento de traslado opcional; estado oficial requiere evidencia externa.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `farm_id` | `uuid` | NOT NULL REFERENCES farms(id) |
| `fma_folio` | `text` | Opcional |
| `origin_rup` | `text` | NOT NULL |
| `destination_rup` | `text` | NOT NULL |
| `status` | `text` | NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','confirmed','submitted','externally_confirmed','executed','cancelled')) |
| `departure_at` | `timestamptz` | Opcional |
| `arrival_at` | `timestamptz` | Opcional |
| `external_evidence` | `text` | Opcional |
| `created_by` | `uuid` | NOT NULL REFERENCES users(id) |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

Restricciones de relación: `UNIQUE(id,farm_id)`; `UNIQUE(fma_folio)`; `CHECK(origin_rup<>destination_rup)`; `CHECK(arrival_at IS NULL OR (departure_at IS NOT NULL AND arrival_at>=departure_at))`.

### `movement_animals`

Detalle con DIIO preservado.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `movement_id` | `uuid` | NOT NULL REFERENCES sag_movements(id) |
| `animal_id` | `uuid` | NOT NULL REFERENCES animals(id) |
| `diio_snapshot` | `text` | NOT NULL |

Restricciones de relación: `PRIMARY KEY(movement_id,animal_id)`.

### `movement_status_events`

Historial inmutable de transición del documento.

| Atributo | Dominio físico de referencia | Clave / obligatoriedad / validación |
|---|---|---|
| `id` | `uuid` | PRIMARY KEY DEFAULT gen_random_uuid() |
| `movement_id` | `uuid` | NOT NULL REFERENCES sag_movements(id) |
| `status` | `text` | NOT NULL |
| `actor_id` | `uuid` | NOT NULL REFERENCES users(id) |
| `reason` | `text` | Opcional |
| `created_at` | `timestamptz` | NOT NULL DEFAULT now() |

