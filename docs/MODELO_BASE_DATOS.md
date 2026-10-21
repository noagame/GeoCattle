# GeoCattle — Base de datos implementada V3

Esquema operativo extraído de PostgreSQL local el 21 de octubre de 2026, después de aplicar `003_application_v3.sql`. Incluye 48 tablas de negocio/soporte; `schema_migrations` es una tabla técnica adicional. Se preservan IDs e historia de V1.

La propuesta de `especificacion-v3/` es la referencia funcional. Esta extracción documenta los nombres y tipos realmente instalados. Compatibilidad: `users.farm_id` es contexto legado; `owner_accounts` y `farm_memberships` determinan el alcance; `auth_challenges` implementa los retos llamados `security_challenges` en el diseño. `animals.farm_id`, `audit_log.at/object_type` y `maintenance.at` se conservan por compatibilidad. No se cambió a TimescaleDB.

La API aplica MFA TOTP, permisos por contexto y solicitudes; el esquema por sí solo no acredita las metas de campo ni todos los RNF. FMA conserva tablas de extensión, deshabilitadas por defecto.

## Tablas, atributos y restricciones

### `account_tokens`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `user_id` | `uuid` | No |
| `purpose` | `text` | No |
| `token_hash` | `text` | No |
| `pending_email` | `text` | Sí |
| `expires_at` | `timestamp with time zone` | No |
| `consumed_at` | `timestamp with time zone` | Sí |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (user_id) REFERENCES users(id)`.
- `UNIQUE (token_hash)`.
- `PRIMARY KEY (id)`.
- `CHECK ((purpose = ANY (ARRAY['verify_email'::text, 'reset_password'::text, 'close_account'::text])))`.

### `animal_holdings`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_id` | `uuid` | No |
| `valid_from` | `timestamp with time zone` | No |
| `valid_to` | `timestamp with time zone` | Sí |
| `reason` | `text` | No |

Restricciones:

- `FOREIGN KEY (animal_id) REFERENCES animals(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from, valid_to, '[)'::text) WITH &&)`.
- `UNIQUE (id, animal_id, farm_id)`.
- `UNIQUE (id, farm_id)`.
- `PRIMARY KEY (id)`.
- `CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))`.

### `animal_measurements`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_holding_id` | `uuid` | No |
| `animal_id` | `uuid` | No |
| `request_id` | `uuid` | No |
| `measured_at` | `timestamp with time zone` | No |
| `weight_kg` | `numeric` | Sí |
| `height_cm` | `numeric` | Sí |
| `corrects_id` | `uuid` | Sí |

Restricciones:

- `FOREIGN KEY (request_id, farm_id) REFERENCES change_requests(id, farm_id)`.
- `FOREIGN KEY (animal_holding_id, animal_id, farm_id) REFERENCES animal_holdings(id, animal_id, farm_id)`.
- `FOREIGN KEY (corrects_id) REFERENCES animal_measurements(id)`.
- `FOREIGN KEY (request_id) REFERENCES change_requests(id)`.
- `FOREIGN KEY (animal_id) REFERENCES animals(id)`.
- `FOREIGN KEY (animal_holding_id) REFERENCES animal_holdings(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `PRIMARY KEY (id)`.
- `CHECK (((weight_kg IS NOT NULL) OR (height_cm IS NOT NULL)))`.
- `CHECK ((height_cm > (0)::numeric))`.
- `CHECK ((weight_kg > (0)::numeric))`.

### `animal_reports`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_holding_id` | `uuid` | No |
| `request_id` | `uuid` | No |
| `description` | `text` | No |
| `occurred_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (request_id) REFERENCES change_requests(id)`.
- `FOREIGN KEY (animal_holding_id) REFERENCES animal_holdings(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `PRIMARY KEY (id)`.
- `FOREIGN KEY (request_id, farm_id) REFERENCES change_requests(id, farm_id)`.
- `FOREIGN KEY (animal_holding_id, farm_id) REFERENCES animal_holdings(id, farm_id)`.

### `animal_states`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `animal_id` | `uuid` | No |
| `telemetry_id` | `uuid` | Sí |
| `observed_at` | `timestamp with time zone` | Sí |
| `position_telemetry_id` | `uuid` | Sí |
| `outside_count` | `integer` | No |
| `geofence_status` | `text` | No |

Restricciones:

- `FOREIGN KEY (position_telemetry_id) REFERENCES telemetry(id)`.
- `FOREIGN KEY (telemetry_id) REFERENCES telemetry(id)`.
- `FOREIGN KEY (animal_id) REFERENCES animals(id)`.
- `PRIMARY KEY (animal_id)`.
- `CHECK ((geofence_status = ANY (ARRAY['unknown'::text, 'inside'::text, 'outside'::text, 'pending'::text])))`.
- `CHECK ((outside_count >= 0))`.

### `animals`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `diio` | `text` | No |
| `name` | `text` | No |
| `orientation` | `text` | No |
| `enabled` | `boolean` | No |
| `sector_id` | `uuid` | Sí |
| `species` | `text` | No |
| `breed` | `text` | Sí |
| `color` | `text` | Sí |
| `sex` | `text` | No |
| `birth_date` | `date` | Sí |
| `birth_date_estimated` | `boolean` | No |
| `production_type` | `text` | No |
| `status` | `text` | No |
| `version` | `bigint` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `CHECK ((version > 0))`.
- `CHECK ((status = ANY (ARRAY['active'::text, 'missing'::text, 'dead'::text, 'slaughtered'::text, 'retired'::text])))`.
- `CHECK ((production_type = ANY (ARRAY['milk'::text, 'meat'::text, 'dual'::text, 'other'::text])))`.
- `CHECK ((sex = ANY (ARRAY['female'::text, 'male'::text, 'unknown'::text])))`.
- `CHECK ((species = 'bovine'::text))`.
- `FOREIGN KEY (sector_id, farm_id) REFERENCES sectors(id, farm_id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `UNIQUE (diio)`.
- `PRIMARY KEY (id)`.
- `CHECK ((orientation = ANY (ARRAY['meat'::text, 'milk'::text])))`.

### `assignments`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_id` | `uuid` | No |
| `device_id` | `uuid` | No |
| `valid_from` | `timestamp with time zone` | No |
| `valid_to` | `timestamp with time zone` | Sí |
| `animal_holding_id` | `uuid` | Sí |
| `assigned_by` | `uuid` | Sí |
| `reason` | `text` | Sí |

Restricciones:

- `FOREIGN KEY (animal_holding_id, animal_id, farm_id) REFERENCES animal_holdings(id, animal_id, farm_id)`.
- `FOREIGN KEY (assigned_by) REFERENCES users(id)`.
- `FOREIGN KEY (device_id, farm_id) REFERENCES devices(id, farm_id)`.
- `FOREIGN KEY (animal_id, farm_id) REFERENCES animals(id, farm_id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `EXCLUDE USING gist (device_id WITH =, tstzrange(valid_from, valid_to, '[)'::text) WITH &&)`.
- `EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from, valid_to, '[)'::text) WITH &&)`.
- `PRIMARY KEY (id)`.
- `CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))`.

### `audit_log`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | Sí |
| `actor_id` | `uuid` | Sí |
| `object_type` | `text` | No |
| `object_id` | `text` | No |
| `action` | `text` | No |
| `at` | `timestamp with time zone` | No |
| `before` | `jsonb` | Sí |
| `after` | `jsonb` | Sí |
| `account_id` | `uuid` | Sí |
| `session_token_hash` | `text` | Sí |
| `actor_kind` | `text` | No |
| `ip_address` | `inet` | Sí |
| `request_id` | `text` | Sí |

Restricciones:

- `FOREIGN KEY (farm_id, account_id) REFERENCES farms(id, account_id)`.
- `CHECK ((actor_kind = ANY (ARRAY['user'::text, 'service'::text])))`.
- `FOREIGN KEY (account_id) REFERENCES owner_accounts(id)`.
- `FOREIGN KEY (session_token_hash) REFERENCES login_sessions(token_hash)`.
- `FOREIGN KEY (actor_id) REFERENCES users(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `PRIMARY KEY (id)`.

### `auth_challenges`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `user_id` | `uuid` | No |
| `token_hash` | `text` | No |
| `purpose` | `text` | No |
| `session_token_hash` | `text` | Sí |
| `operation_digest` | `text` | Sí |
| `expires_at` | `timestamp with time zone` | No |
| `verified_at` | `timestamp with time zone` | Sí |
| `consumed_at` | `timestamp with time zone` | Sí |
| `attempts` | `integer` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (session_token_hash) REFERENCES login_sessions(token_hash)`.
- `FOREIGN KEY (user_id) REFERENCES users(id)`.
- `UNIQUE (token_hash)`.
- `PRIMARY KEY (id)`.
- `CHECK (((attempts >= 0) AND (attempts <= 5)))`.
- `CHECK ((purpose = ANY (ARRAY['login'::text, 'step_up'::text, 'mfa_setup'::text, 'verify_email'::text, 'reset_password'::text, 'close_account'::text])))`.

### `change_applications`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `request_id` | `uuid` | No |
| `entity_type` | `text` | No |
| `entity_id` | `uuid` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (request_id) REFERENCES change_decisions(request_id)`.
- `PRIMARY KEY (request_id)`.

### `change_decisions`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `request_id` | `uuid` | No |
| `decided_by` | `uuid` | No |
| `decision` | `text` | No |
| `trust_grant_id` | `uuid` | Sí |
| `reason` | `text` | Sí |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `TRIGGER DEFERRABLE INITIALLY DEFERRED`.
- `FOREIGN KEY (trust_grant_id) REFERENCES trust_grants(id)`.
- `FOREIGN KEY (decided_by) REFERENCES users(id)`.
- `FOREIGN KEY (request_id) REFERENCES change_requests(id)`.
- `PRIMARY KEY (request_id)`.
- `CHECK (((decision <> 'rejected'::text) OR (NULLIF(btrim(reason), ''::text) IS NOT NULL)))`.
- `CHECK ((decision = ANY (ARRAY['approved'::text, 'rejected'::text, 'direct'::text])))`.

### `change_requests`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `requested_by` | `uuid` | No |
| `membership_id` | `uuid` | Sí |
| `action` | `text` | No |
| `animal_holding_id` | `uuid` | Sí |
| `animal_id` | `uuid` | Sí |
| `device_id` | `uuid` | Sí |
| `expected_version` | `bigint` | Sí |
| `payload` | `jsonb` | No |
| `idempotency_key` | `uuid` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (device_id, farm_id) REFERENCES devices(id, farm_id)`.
- `FOREIGN KEY (animal_holding_id, animal_id, farm_id) REFERENCES animal_holdings(id, animal_id, farm_id)`.
- `FOREIGN KEY (membership_id, farm_id) REFERENCES farm_memberships(id, farm_id)`.
- `FOREIGN KEY (device_id) REFERENCES devices(id)`.
- `FOREIGN KEY (animal_id) REFERENCES animals(id)`.
- `FOREIGN KEY (animal_holding_id) REFERENCES animal_holdings(id)`.
- `FOREIGN KEY (membership_id) REFERENCES farm_memberships(id)`.
- `FOREIGN KEY (requested_by) REFERENCES users(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (requested_by, idempotency_key)`.
- `UNIQUE (id, farm_id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((((action = 'battery_replacement'::text) AND (device_id IS NOT NULL)) OR ((action <> 'battery_replacement'::text) AND (animal_id IS NOT NULL))))`.
- `CHECK (((animal_holding_id IS NULL) = (animal_id IS NULL)))`.
- `CHECK ((jsonb_typeof(payload) = 'object'::text))`.
- `CHECK ((expected_version > 0))`.
- `CHECK ((action = ANY (ARRAY['animal_profile'::text, 'animal_status'::text, 'animal_report'::text, 'health_record'::text, 'battery_replacement'::text, 'health_schedule'::text])))`.

### `device_configs`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `device_id` | `uuid` | No |
| `version` | `integer` | No |
| `interval_seconds` | `integer` | No |
| `status` | `text` | No |
| `requested_at` | `timestamp with time zone` | No |
| `sent_at` | `timestamp with time zone` | Sí |
| `applied_at` | `timestamp with time zone` | Sí |
| `error` | `text` | Sí |

Restricciones:

- `FOREIGN KEY (device_id) REFERENCES devices(id)`.
- `UNIQUE (device_id, version)`.
- `PRIMARY KEY (id)`.
- `CHECK ((status = ANY (ARRAY['requested'::text, 'sent'::text, 'applied'::text, 'failed'::text])))`.
- `CHECK (((interval_seconds >= 30) AND (interval_seconds <= 86400)))`.
- `CHECK ((version > 0))`.

### `devices`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `hardware_id` | `text` | No |
| `dev_eui` | `text` | Sí |
| `name` | `text` | No |
| `transport` | `text` | No |
| `enabled` | `boolean` | No |
| `interval_seconds` | `integer` | No |
| `config_version` | `integer` | No |
| `installed_at` | `timestamp with time zone` | No |
| `last_observed_at` | `timestamp with time zone` | Sí |
| `last_received_at` | `timestamp with time zone` | Sí |
| `last_telemetry_id` | `uuid` | Sí |
| `serial_number` | `text` | Sí |
| `hardware_revision` | `text` | Sí |
| `firmware_version` | `text` | Sí |
| `status` | `text` | No |

Restricciones:

- `CHECK ((status = ANY (ARRAY['available'::text, 'installed'::text, 'maintenance'::text, 'retired'::text])))`.
- `UNIQUE (serial_number)`.
- `FOREIGN KEY (last_telemetry_id) REFERENCES telemetry(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `UNIQUE (dev_eui)`.
- `UNIQUE (hardware_id)`.
- `PRIMARY KEY (id)`.
- `CHECK (((interval_seconds >= 30) AND (interval_seconds <= 86400)))`.
- `CHECK ((transport = ANY (ARRAY['academic'::text, 'lorawan'::text])))`.
- `CHECK (((dev_eui IS NULL) OR (dev_eui ~ '^[0-9a-f]{16}$'::text)))`.

### `event_actions`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `event_id` | `uuid` | No |
| `actor_id` | `uuid` | No |
| `action` | `text` | No |
| `at` | `timestamp with time zone` | No |
| `note` | `text` | No |

Restricciones:

- `FOREIGN KEY (actor_id) REFERENCES users(id)`.
- `FOREIGN KEY (event_id) REFERENCES events(id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((action = ANY (ARRAY['acknowledge'::text, 'review'::text, 'conclude'::text, 'reopen'::text])))`.

### `events`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_id` | `uuid` | Sí |
| `device_id` | `uuid` | No |
| `telemetry_id` | `uuid` | Sí |
| `geofence_id` | `uuid` | Sí |
| `type` | `text` | No |
| `severity` | `text` | No |
| `condition` | `text` | No |
| `attention` | `text` | No |
| `opened_at` | `timestamp with time zone` | No |
| `resolved_at` | `timestamp with time zone` | Sí |
| `detail` | `jsonb` | No |

Restricciones:

- `FOREIGN KEY (geofence_id, farm_id) REFERENCES geofences(id, farm_id)`.
- `FOREIGN KEY (telemetry_id, farm_id) REFERENCES telemetry(id, farm_id)`.
- `FOREIGN KEY (animal_id, farm_id) REFERENCES animals(id, farm_id)`.
- `FOREIGN KEY (device_id, farm_id) REFERENCES devices(id, farm_id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((((condition = 'active'::text) AND (resolved_at IS NULL)) OR ((condition = 'resolved'::text) AND (resolved_at IS NOT NULL))))`.
- `CHECK ((attention = ANY (ARRAY['pending'::text, 'acknowledged'::text, 'in_review'::text, 'concluded'::text])))`.
- `CHECK ((condition = ANY (ARRAY['active'::text, 'resolved'::text])))`.
- `CHECK ((severity = ANY (ARRAY['warning'::text, 'critical'::text])))`.
- `CHECK ((type = ANY (ARRAY['escape'::text, 'communication_timeout'::text, 'low_battery'::text, 'high_surface_temperature'::text, 'low_activity'::text, 'proximity'::text, 'config_timeout'::text])))`.

### `farm_features`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `farm_id` | `uuid` | No |
| `feature_code` | `text` | No |
| `enabled` | `boolean` | No |
| `enabled_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (feature_code) REFERENCES features(code)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `PRIMARY KEY (farm_id, feature_code)`.

### `farm_memberships`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `user_id` | `uuid` | No |
| `role_code` | `text` | No |
| `granted_by` | `uuid` | No |
| `valid_from` | `timestamp with time zone` | No |
| `valid_to` | `timestamp with time zone` | Sí |

Restricciones:

- `PRIMARY KEY (id)`.
- `CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))`.
- `CHECK ((role_code = ANY (ARRAY['owner'::text, 'worker'::text, 'veterinarian'::text, 'operator'::text, 'viewer'::text])))`.
- `FOREIGN KEY (role_code) REFERENCES roles(code)`.
- `FOREIGN KEY (user_id) REFERENCES users(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `EXCLUDE USING gist (user_id WITH =, farm_id WITH =, tstzrange(valid_from, valid_to, '[)'::text) WITH &&)`.
- `UNIQUE (id, farm_id)`.
- `FOREIGN KEY (granted_by) REFERENCES users(id)`.

### `farms`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `name` | `text` | No |
| `environment` | `text` | No |
| `timezone` | `text` | No |
| `account_id` | `uuid` | Sí |
| `rup` | `text` | Sí |
| `address` | `text` | Sí |
| `region` | `text` | Sí |
| `commune` | `text` | Sí |
| `boundary` | `geometry(MultiPolygon,4326)` | Sí |
| `active` | `boolean` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `CHECK (((boundary IS NULL) OR (st_isvalid(boundary) AND (NOT st_isempty(boundary)) AND (st_area(boundary) > (0)::double precision))))`.
- `UNIQUE (id, account_id)`.
- `UNIQUE (rup)`.
- `FOREIGN KEY (account_id) REFERENCES owner_accounts(id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((environment = ANY (ARRAY['simulation'::text, 'development'::text, 'production'::text])))`.

### `features`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `code` | `text` | No |
| `name` | `text` | No |

Restricciones:

- `PRIMARY KEY (code)`.

### `gateways`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `gateway_eui` | `text` | No |
| `name` | `text` | No |
| `position` | `geometry(Point,4326)` | Sí |
| `status` | `text` | No |
| `installed_at` | `timestamp with time zone` | Sí |
| `last_seen_at` | `timestamp with time zone` | Sí |

Restricciones:

- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `UNIQUE (gateway_eui)`.
- `PRIMARY KEY (id)`.
- `CHECK ((status = ANY (ARRAY['installed'::text, 'maintenance'::text, 'retired'::text])))`.
- `CHECK ((gateway_eui ~ '^[0-9a-f]{16}$'::text))`.

### `geofences`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `sector_id` | `uuid` | No |
| `name` | `text` | No |
| `version` | `integer` | No |
| `geometry` | `geometry(Polygon,4326)` | No |
| `active` | `boolean` | No |
| `created_at` | `timestamp with time zone` | No |
| `valid_to` | `timestamp with time zone` | Sí |
| `created_by` | `uuid` | Sí |

Restricciones:

- `FOREIGN KEY (created_by) REFERENCES users(id)`.
- `FOREIGN KEY (sector_id, farm_id) REFERENCES sectors(id, farm_id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `UNIQUE (sector_id, version)`.
- `PRIMARY KEY (id)`.
- `CHECK (((valid_to IS NULL) OR (valid_to > created_at)))`.
- `CHECK ((st_isvalid(geometry) AND (NOT st_isempty(geometry)) AND (st_area(geometry) > (0)::double precision)))`.
- `CHECK ((version > 0))`.

### `health_events`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_holding_id` | `uuid` | No |
| `request_id` | `uuid` | No |
| `event_type` | `text` | No |
| `operation` | `text` | No |
| `target_event_id` | `uuid` | Sí |
| `occurred_at` | `timestamp with time zone` | No |
| `recorded_by` | `uuid` | No |
| `description` | `text` | No |
| `diagnosis` | `text` | Sí |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (target_event_id, farm_id) REFERENCES health_events(id, farm_id)`.
- `FOREIGN KEY (request_id, farm_id) REFERENCES change_requests(id, farm_id)`.
- `FOREIGN KEY (animal_holding_id, farm_id) REFERENCES animal_holdings(id, farm_id)`.
- `FOREIGN KEY (recorded_by) REFERENCES users(id)`.
- `FOREIGN KEY (target_event_id) REFERENCES health_events(id)`.
- `FOREIGN KEY (request_id) REFERENCES change_requests(id)`.
- `FOREIGN KEY (animal_holding_id) REFERENCES animal_holdings(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((((operation = 'record'::text) AND (target_event_id IS NULL)) OR ((operation = ANY (ARRAY['correct'::text, 'void'::text])) AND (target_event_id IS NOT NULL))))`.
- `CHECK ((operation = ANY (ARRAY['record'::text, 'correct'::text, 'void'::text])))`.
- `CHECK ((event_type = ANY (ARRAY['examination'::text, 'vaccination'::text, 'antibiotic'::text, 'pathology'::text, 'diagnosis'::text, 'procedure'::text, 'injury'::text, 'death'::text, 'observation'::text])))`.

### `health_schedules`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_holding_id` | `uuid` | No |
| `request_id` | `uuid` | No |
| `kind` | `text` | No |
| `description` | `text` | No |
| `due_at` | `timestamp with time zone` | No |
| `operation` | `text` | No |
| `target_schedule_id` | `uuid` | Sí |
| `completed_event_id` | `uuid` | Sí |
| `created_by` | `uuid` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (completed_event_id, farm_id) REFERENCES health_events(id, farm_id)`.
- `FOREIGN KEY (target_schedule_id, farm_id) REFERENCES health_schedules(id, farm_id)`.
- `FOREIGN KEY (request_id, farm_id) REFERENCES change_requests(id, farm_id)`.
- `FOREIGN KEY (animal_holding_id, farm_id) REFERENCES animal_holdings(id, farm_id)`.
- `FOREIGN KEY (created_by) REFERENCES users(id)`.
- `FOREIGN KEY (completed_event_id) REFERENCES health_events(id)`.
- `FOREIGN KEY (target_schedule_id) REFERENCES health_schedules(id)`.
- `FOREIGN KEY (request_id) REFERENCES change_requests(id)`.
- `FOREIGN KEY (animal_holding_id) REFERENCES animal_holdings(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `PRIMARY KEY (id)`.
- `CHECK (((operation = 'complete'::text) = (completed_event_id IS NOT NULL)))`.
- `CHECK ((((operation = 'plan'::text) AND (target_schedule_id IS NULL)) OR ((operation <> 'plan'::text) AND (target_schedule_id IS NOT NULL))))`.
- `CHECK ((operation = ANY (ARRAY['plan'::text, 'replace'::text, 'cancel'::text, 'complete'::text])))`.
- `CHECK ((kind = ANY (ARRAY['vaccination'::text, 'antibiotic'::text, 'checkup'::text])))`.

### `health_treatments`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `health_event_id` | `uuid` | No |
| `product_name` | `text` | No |
| `product_registration` | `text` | Sí |
| `batch_number` | `text` | Sí |
| `dose_value` | `numeric` | No |
| `dose_unit` | `text` | No |
| `route` | `text` | No |
| `administered_at` | `timestamp with time zone` | No |
| `withdrawal_meat_until` | `date` | Sí |
| `withdrawal_milk_until` | `date` | Sí |
| `withdrawal_basis` | `text` | Sí |

Restricciones:

- `FOREIGN KEY (health_event_id, farm_id) REFERENCES health_events(id, farm_id)`.
- `FOREIGN KEY (health_event_id) REFERENCES health_events(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((dose_value > (0)::numeric))`.

### `invitations`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `email` | `text` | No |
| `role_code` | `text` | No |
| `token_hash` | `text` | No |
| `invited_by` | `uuid` | No |
| `expires_at` | `timestamp with time zone` | No |
| `accepted_at` | `timestamp with time zone` | Sí |
| `accepted_user_id` | `uuid` | Sí |
| `revoked_at` | `timestamp with time zone` | Sí |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (accepted_user_id) REFERENCES users(id)`.
- `FOREIGN KEY (invited_by) REFERENCES users(id)`.
- `FOREIGN KEY (role_code) REFERENCES roles(code)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (token_hash)`.
- `PRIMARY KEY (id)`.
- `CHECK (((accepted_at IS NULL) = (accepted_user_id IS NULL)))`.
- `CHECK ((role_code = ANY (ARRAY['worker'::text, 'veterinarian'::text])))`.
- `CHECK ((email = lower(btrim(email))))`.

### `login_sessions`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `token_hash` | `text` | No |
| `user_id` | `uuid` | No |
| `csrf_token` | `text` | No |
| `expires_at` | `timestamp with time zone` | No |
| `active_farm_id` | `uuid` | Sí |
| `mfa_verified_at` | `timestamp with time zone` | Sí |
| `step_up_at` | `timestamp with time zone` | Sí |
| `authenticated_at` | `timestamp with time zone` | No |
| `last_seen_at` | `timestamp with time zone` | No |
| `revoked_at` | `timestamp with time zone` | Sí |

Restricciones:

- `FOREIGN KEY (active_farm_id) REFERENCES farms(id)`.
- `FOREIGN KEY (user_id) REFERENCES users(id)`.
- `PRIMARY KEY (token_hash)`.

### `maintenance`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `device_id` | `uuid` | No |
| `battery_id` | `text` | Sí |
| `kind` | `text` | No |
| `at` | `timestamp with time zone` | No |
| `responsible_id` | `uuid` | No |
| `result` | `text` | No |
| `request_id` | `uuid` | Sí |

Restricciones:

- `FOREIGN KEY (request_id, farm_id) REFERENCES change_requests(id, farm_id)`.
- `FOREIGN KEY (device_id, farm_id) REFERENCES devices(id, farm_id)`.
- `FOREIGN KEY (responsible_id) REFERENCES users(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((kind = ANY (ARRAY['inspection'::text, 'recharge'::text, 'replacement'::text, 'retirement'::text])))`.

### `mfa_factors`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `user_id` | `uuid` | No |
| `kind` | `text` | No |
| `credential_id` | `text` | Sí |
| `protected_data` | `bytea` | No |
| `verified_at` | `timestamp with time zone` | Sí |
| `revoked_at` | `timestamp with time zone` | Sí |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (user_id) REFERENCES users(id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((kind = ANY (ARRAY['totp'::text, 'webauthn'::text])))`.

### `mfa_recovery_codes`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `user_id` | `uuid` | No |
| `code_hash` | `text` | No |
| `used_at` | `timestamp with time zone` | Sí |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (user_id) REFERENCES users(id)`.
- `UNIQUE (code_hash)`.
- `PRIMARY KEY (id)`.

### `movement_animals`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `movement_id` | `uuid` | No |
| `animal_id` | `uuid` | No |
| `diio_snapshot` | `text` | No |

Restricciones:

- `FOREIGN KEY (animal_id) REFERENCES animals(id)`.
- `FOREIGN KEY (movement_id) REFERENCES sag_movements(id)`.
- `PRIMARY KEY (movement_id, animal_id)`.

### `movement_status_events`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `movement_id` | `uuid` | No |
| `status` | `text` | No |
| `actor_id` | `uuid` | No |
| `reason` | `text` | Sí |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (actor_id) REFERENCES users(id)`.
- `FOREIGN KEY (movement_id) REFERENCES sag_movements(id)`.
- `PRIMARY KEY (id)`.

### `notification_attempts`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `notification_id` | `uuid` | No |
| `attempt` | `integer` | No |
| `at` | `timestamp with time zone` | No |
| `status` | `text` | No |
| `provider_id` | `text` | Sí |
| `error` | `text` | Sí |

Restricciones:

- `FOREIGN KEY (notification_id) REFERENCES notifications(id)`.
- `UNIQUE (notification_id, attempt)`.
- `PRIMARY KEY (id)`.
- `CHECK ((status = ANY (ARRAY['accepted'::text, 'failed'::text, 'expired'::text, 'disabled'::text])))`.
- `CHECK ((attempt > 0))`.

### `notifications`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `event_id` | `uuid` | Sí |
| `status` | `text` | No |
| `channel` | `text` | No |
| `requested_at` | `timestamp with time zone` | Sí |
| `created_at` | `timestamp with time zone` | No |
| `next_attempt_at` | `timestamp with time zone` | No |
| `farm_id` | `uuid` | Sí |
| `recipient_id` | `uuid` | Sí |
| `request_id` | `uuid` | Sí |
| `schedule_id` | `uuid` | Sí |
| `recipient_address` | `text` | Sí |
| `message` | `text` | No |
| `read_at` | `timestamp with time zone` | Sí |

Restricciones:

- `CHECK ((status = ANY (ARRAY['pending'::text, 'accepted'::text, 'failed'::text, 'expired'::text, 'disabled'::text, 'read'::text])))`.
- `FOREIGN KEY (schedule_id, farm_id) REFERENCES health_schedules(id, farm_id)`.
- `FOREIGN KEY (request_id, farm_id) REFERENCES change_requests(id, farm_id)`.
- `FOREIGN KEY (recipient_id) REFERENCES users(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `FOREIGN KEY (event_id) REFERENCES events(id)`.
- `PRIMARY KEY (id)`.

### `owner_accounts`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `owner_user_id` | `uuid` | No |
| `display_name` | `text` | No |
| `max_farms` | `integer` | No |
| `active` | `boolean` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (owner_user_id) REFERENCES users(id)`.
- `UNIQUE (owner_user_id)`.
- `PRIMARY KEY (id)`.
- `CHECK ((max_farms > 0))`.

### `pasture_assignments`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `animal_id` | `uuid` | No |
| `geofence_id` | `uuid` | No |
| `valid_from` | `timestamp with time zone` | No |
| `valid_to` | `timestamp with time zone` | Sí |
| `animal_holding_id` | `uuid` | Sí |
| `assigned_by` | `uuid` | Sí |

Restricciones:

- `FOREIGN KEY (animal_holding_id, animal_id, farm_id) REFERENCES animal_holdings(id, animal_id, farm_id)`.
- `FOREIGN KEY (assigned_by) REFERENCES users(id)`.
- `FOREIGN KEY (geofence_id, farm_id) REFERENCES geofences(id, farm_id)`.
- `FOREIGN KEY (animal_id, farm_id) REFERENCES animals(id, farm_id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from, valid_to, '[)'::text) WITH &&)`.
- `PRIMARY KEY (id)`.
- `CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))`.

### `permissions`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `code` | `text` | No |
| `description` | `text` | No |

Restricciones:

- `PRIMARY KEY (code)`.

### `platform_admins`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `user_id` | `uuid` | No |
| `active` | `boolean` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (user_id) REFERENCES users(id)`.
- `PRIMARY KEY (user_id)`.

### `request_metrics`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `account_id` | `uuid` | Sí |
| `farm_id` | `uuid` | Sí |
| `actor_id` | `uuid` | Sí |
| `request_id` | `text` | No |
| `method` | `text` | No |
| `route_template` | `text` | No |
| `status_code` | `integer` | No |
| `duration_ms` | `numeric` | No |
| `request_bytes` | `bigint` | No |
| `response_bytes` | `bigint` | No |
| `occurred_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (farm_id, account_id) REFERENCES farms(id, account_id)`.
- `FOREIGN KEY (actor_id) REFERENCES users(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `FOREIGN KEY (account_id) REFERENCES owner_accounts(id)`.
- `PRIMARY KEY (id)`.
- `CHECK (((farm_id IS NULL) OR (account_id IS NOT NULL)))`.
- `CHECK ((response_bytes >= 0))`.
- `CHECK ((request_bytes >= 0))`.
- `CHECK ((duration_ms >= (0)::numeric))`.
- `CHECK (((status_code >= 100) AND (status_code <= 599)))`.

### `role_permissions`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `role_code` | `text` | No |
| `permission_code` | `text` | No |

Restricciones:

- `FOREIGN KEY (permission_code) REFERENCES permissions(code)`.
- `FOREIGN KEY (role_code) REFERENCES roles(code)`.
- `PRIMARY KEY (role_code, permission_code)`.

### `roles`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `code` | `text` | No |
| `name` | `text` | No |
| `scope` | `text` | No |

Restricciones:

- `PRIMARY KEY (code)`.
- `CHECK ((scope = ANY (ARRAY['platform'::text, 'account'::text, 'farm'::text])))`.

### `rule_settings`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `farm_id` | `uuid` | No |
| `version` | `integer` | No |
| `battery_low_mv` | `integer` | No |
| `temperature_high_c` | `double precision` | Sí |
| `activity_low_threshold` | `double precision` | Sí |
| `activity_window_minutes` | `integer` | No |
| `proximity_meters` | `double precision` | No |
| `temperature_enabled` | `boolean` | No |
| `activity_enabled` | `boolean` | No |
| `proximity_enabled` | `boolean` | No |

Restricciones:

- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `PRIMARY KEY (farm_id)`.
- `CHECK (((NOT activity_enabled) OR (activity_low_threshold IS NOT NULL)))`.
- `CHECK (((NOT temperature_enabled) OR (temperature_high_c IS NOT NULL)))`.
- `CHECK (((proximity_meters >= (0)::double precision) AND (proximity_meters <= (1000)::double precision)))`.
- `CHECK (((activity_window_minutes >= 1) AND (activity_window_minutes <= 1440)))`.
- `CHECK (((activity_low_threshold >= (0)::double precision) AND (activity_low_threshold <= (1000000)::double precision)))`.
- `CHECK (((temperature_high_c >= ('-60'::integer)::double precision) AND (temperature_high_c <= (100)::double precision)))`.
- `CHECK (((battery_low_mv >= 0) AND (battery_low_mv <= 20000)))`.

### `sag_movements`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `fma_folio` | `text` | Sí |
| `origin_rup` | `text` | No |
| `destination_rup` | `text` | No |
| `status` | `text` | No |
| `departure_at` | `timestamp with time zone` | Sí |
| `arrival_at` | `timestamp with time zone` | Sí |
| `external_evidence` | `text` | Sí |
| `created_by` | `uuid` | No |
| `created_at` | `timestamp with time zone` | No |

Restricciones:

- `FOREIGN KEY (created_by) REFERENCES users(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (fma_folio)`.
- `UNIQUE (id, farm_id)`.
- `PRIMARY KEY (id)`.
- `CHECK (((arrival_at IS NULL) OR ((departure_at IS NOT NULL) AND (arrival_at >= departure_at))))`.
- `CHECK ((origin_rup <> destination_rup))`.
- `CHECK ((status = ANY (ARRAY['draft'::text, 'confirmed'::text, 'submitted'::text, 'externally_confirmed'::text, 'executed'::text, 'cancelled'::text])))`.

### `sectors`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `name` | `text` | No |
| `land_use` | `text` | No |
| `description` | `text` | Sí |
| `active` | `boolean` | No |

Restricciones:

- `CHECK ((land_use = ANY (ARRAY['grazing'::text, 'available'::text, 'cropped'::text, 'restricted'::text, 'other'::text])))`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `UNIQUE (farm_id, name)`.
- `PRIMARY KEY (id)`.

### `telemetry`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `device_id` | `uuid` | No |
| `animal_id` | `uuid` | Sí |
| `assignment_id` | `uuid` | Sí |
| `session_id` | `text` | No |
| `seq` | `bigint` | No |
| `observed_at` | `timestamp with time zone` | No |
| `received_at` | `timestamp with time zone` | No |
| `longitude` | `double precision` | Sí |
| `latitude` | `double precision` | Sí |
| `point` | `geometry(Point,4326)` | Sí |
| `gnss_valid` | `boolean` | No |
| `surface_temperature_c` | `double precision` | Sí |
| `activity_index` | `double precision` | Sí |
| `battery_mv` | `integer` | Sí |
| `source` | `text` | No |
| `quality` | `jsonb` | No |
| `config_version` | `integer` | Sí |

Restricciones:

- `FOREIGN KEY (animal_id, farm_id) REFERENCES animals(id, farm_id)`.
- `FOREIGN KEY (device_id, farm_id) REFERENCES devices(id, farm_id)`.
- `FOREIGN KEY (assignment_id) REFERENCES assignments(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (id, farm_id)`.
- `UNIQUE (device_id, session_id, seq)`.
- `PRIMARY KEY (id)`.
- `CHECK ((observed_at <= (received_at + '00:05:00'::interval)))`.
- `CHECK (((gnss_valid AND (longitude IS NOT NULL) AND (latitude IS NOT NULL) AND (point IS NOT NULL)) OR ((NOT gnss_valid) AND (longitude IS NULL) AND (latitude IS NULL) AND (point IS NULL))))`.
- `CHECK ((config_version >= 0))`.
- `CHECK ((source = ANY (ARRAY['sim'::text, 'academic'::text, 'lorawan'::text])))`.
- `CHECK (((battery_mv >= 0) AND (battery_mv <= 20000)))`.
- `CHECK (((activity_index >= (0)::double precision) AND (activity_index <= (1000000)::double precision)))`.
- `CHECK (((surface_temperature_c >= ('-60'::integer)::double precision) AND (surface_temperature_c <= (100)::double precision)))`.
- `CHECK (((latitude >= ('-90'::integer)::double precision) AND (latitude <= (90)::double precision)))`.
- `CHECK (((longitude >= ('-180'::integer)::double precision) AND (longitude <= (180)::double precision)))`.
- `CHECK ((seq >= 0))`.

### `telemetry_receptions`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `telemetry_id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `gateway_id` | `uuid` | No |
| `received_at` | `timestamp with time zone` | No |
| `rssi_dbm` | `numeric` | Sí |
| `snr_db` | `numeric` | Sí |

Restricciones:

- `FOREIGN KEY (gateway_id, farm_id) REFERENCES gateways(id, farm_id)`.
- `FOREIGN KEY (telemetry_id, farm_id) REFERENCES telemetry(id, farm_id)`.
- `FOREIGN KEY (gateway_id) REFERENCES gateways(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `FOREIGN KEY (telemetry_id) REFERENCES telemetry(id)`.
- `PRIMARY KEY (telemetry_id, gateway_id)`.

### `trust_grants`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | No |
| `membership_id` | `uuid` | No |
| `action` | `text` | No |
| `granted_by` | `uuid` | No |
| `valid_from` | `timestamp with time zone` | No |
| `valid_to` | `timestamp with time zone` | Sí |

Restricciones:

- `FOREIGN KEY (membership_id, farm_id) REFERENCES farm_memberships(id, farm_id)`.
- `FOREIGN KEY (granted_by) REFERENCES users(id)`.
- `FOREIGN KEY (membership_id) REFERENCES farm_memberships(id)`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `EXCLUDE USING gist (membership_id WITH =, action WITH =, tstzrange(valid_from, valid_to, '[)'::text) WITH &&)`.
- `UNIQUE (id, farm_id)`.
- `PRIMARY KEY (id)`.
- `CHECK (((valid_to IS NULL) OR (valid_to > valid_from)))`.
- `CHECK ((action = ANY (ARRAY['animal_status'::text, 'animal_report'::text, 'health_record'::text, 'battery_replacement'::text])))`.

### `users`

| Columna | Tipo real | Permite NULL |
|---|---|---|
| `id` | `uuid` | No |
| `farm_id` | `uuid` | Sí |
| `username` | `text` | No |
| `password_hash` | `text` | No |
| `role` | `text` | No |
| `active` | `boolean` | No |
| `email` | `text` | Sí |
| `full_name` | `text` | No |
| `phone` | `text` | Sí |
| `version` | `bigint` | No |
| `email_verified_at` | `timestamp with time zone` | Sí |
| `created_at` | `timestamp with time zone` | No |
| `updated_at` | `timestamp with time zone` | No |

Restricciones:

- `CHECK (((email IS NULL) OR ((email = lower(btrim(email))) AND (POSITION(('@'::text) IN (email)) > 1))))`.
- `CHECK ((version > 0))`.
- `CHECK ((role = ANY (ARRAY['admin'::text, 'owner'::text, 'worker'::text, 'veterinarian'::text, 'operator'::text, 'viewer'::text])))`.
- `FOREIGN KEY (farm_id) REFERENCES farms(id)`.
- `UNIQUE (username)`.
- `PRIMARY KEY (id)`.

