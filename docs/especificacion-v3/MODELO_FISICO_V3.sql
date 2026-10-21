-- GeoCattle V3: propuesta física independiente. PostgreSQL 16 + PostGIS 3.4.
-- Instalar en una base vacía de revisión; NO es una migración de producción.
-- No configura servidor MFA, API ni autorización HTTP. Ver 05_MODELO_FISICO.md.
BEGIN;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE SCHEMA geocattle_v3;
SET search_path = geocattle_v3, public;

-- Cuenta global; correo normalizado; no se duplica por predio.
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE CHECK(email=lower(btrim(email)) AND position('@' in email)>1),
  password_hash text NOT NULL,
  full_name text NOT NULL,
  phone text,
  status text NOT NULL DEFAULT 'invited' CHECK(status IN ('invited','active','suspended','closed')),
  email_verified_at timestamptz,
  version bigint NOT NULL DEFAULT 1 CHECK(version>0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Administradores globales, independientes de clientes y predios.
CREATE TABLE platform_admins (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Factores MFA; secretos cifrados por la aplicación con clave externa.
CREATE TABLE mfa_factors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  kind text NOT NULL CHECK(kind IN ('totp','webauthn')),
  credential_id text,
  protected_data bytea NOT NULL,
  verified_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Códigos de recuperación de un solo uso almacenados con hash.
CREATE TABLE mfa_recovery_codes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  code_hash text NOT NULL UNIQUE,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Sesiones emitidas solo después de completar autenticación requerida.
CREATE TABLE login_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  token_hash text NOT NULL UNIQUE,
  csrf_hash text NOT NULL,
  authenticated_at timestamptz NOT NULL DEFAULT now(),
  mfa_verified_at timestamptz,
  expires_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  CHECK(expires_at>authenticated_at)
);

-- Retos MFA/step-up vinculados a sesión, propósito y operación; no contienen OTP en claro.
CREATE TABLE security_challenges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES login_sessions(id),
  purpose text NOT NULL,
  operation_digest text NOT NULL,
  expires_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz,
  consumed_at timestamptz,
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5)
);

-- Enlaces de verificación de correo/recuperación sin sesión previa; token de un solo uso con hash.
CREATE TABLE account_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  purpose text NOT NULL CHECK(purpose IN ('verify_email','reset_password','close_account')),
  token_hash text NOT NULL UNIQUE,
  pending_email text,
  expires_at timestamptz NOT NULL DEFAULT now(),
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Catálogo: platform_admin, owner, worker, veterinarian. El alcance se materializa en tablas distintas.
CREATE TABLE roles (
  code text PRIMARY KEY,
  name text NOT NULL,
  scope text NOT NULL CHECK(scope IN ('platform','account','farm'))
);

-- Catálogo de acciones autorizables.
CREATE TABLE permissions (
  code text PRIMARY KEY,
  description text NOT NULL
);

-- Permisos por rol; la confianza no agrega permisos, solo elimina revisión en acciones permitidas.
CREATE TABLE role_permissions (
  role_code text NOT NULL REFERENCES roles(code),
  permission_code text NOT NULL REFERENCES permissions(code),
  PRIMARY KEY(role_code,permission_code)
);

-- Cliente del sistema, administrado por un dueño principal.
CREATE TABLE owner_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id uuid NOT NULL REFERENCES users(id),
  display_name text NOT NULL,
  max_farms integer NOT NULL DEFAULT 1 CHECK(max_farms>0),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(owner_user_id)
);

-- Predio perteneciente a una cuenta cliente.
CREATE TABLE farms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES owner_accounts(id),
  name text NOT NULL,
  rup text UNIQUE,
  address text,
  region text,
  commune text,
  timezone text NOT NULL DEFAULT 'America/Santiago',
  boundary geometry(MultiPolygon,4326),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,account_id),
  CHECK(boundary IS NULL OR (ST_IsValid(boundary) AND NOT ST_IsEmpty(boundary) AND ST_Area(boundary)>0))
);

-- Acceso temporal de trabajador/veterinario; el dueño accede mediante su cuenta.
CREATE TABLE farm_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role_code text NOT NULL REFERENCES roles(code) CHECK(role_code IN ('worker','veterinarian')),
  granted_by uuid NOT NULL REFERENCES users(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  UNIQUE(id,farm_id),
  CHECK(valid_to IS NULL OR valid_to>valid_from),
  EXCLUDE USING gist (user_id WITH =,farm_id WITH =,tstzrange(valid_from,valid_to,'[)') WITH &&)
);

-- Invitación por predio y rol; acceso solo al aceptar y verificar correo.
CREATE TABLE invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  email text NOT NULL CHECK(email=lower(btrim(email))),
  role_code text NOT NULL REFERENCES roles(code) CHECK(role_code IN ('worker','veterinarian')),
  token_hash text NOT NULL UNIQUE,
  invited_by uuid NOT NULL REFERENCES users(id),
  expires_at timestamptz NOT NULL DEFAULT now(),
  accepted_at timestamptz,
  accepted_user_id uuid REFERENCES users(id),
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK((accepted_at IS NULL)=(accepted_user_id IS NULL))
);

-- Exención de aprobación por trabajador y acción, revocable y con vigencia.
CREATE TABLE trust_grants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  membership_id uuid NOT NULL REFERENCES farm_memberships(id),
  action text NOT NULL CHECK(action IN ('animal_status','animal_report','health_record','battery_replacement')),
  granted_by uuid NOT NULL REFERENCES users(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  UNIQUE(id,farm_id),
  FOREIGN KEY (membership_id,farm_id) REFERENCES farm_memberships(id,farm_id),
  CHECK(valid_to IS NULL OR valid_to>valid_from),
  EXCLUDE USING gist(membership_id WITH =,action WITH =,tstzrange(valid_from,valid_to,'[)') WITH &&)
);

-- Sector/potrero del predio y su uso actual.
CREATE TABLE sectors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  name text NOT NULL,
  land_use text NOT NULL CHECK(land_use IN ('grazing','available','cropped','restricted','other')),
  description text,
  active boolean NOT NULL DEFAULT true,
  UNIQUE(id,farm_id),
  UNIQUE(farm_id,name)
);

-- Versiones inmutables de límites; se cierra vigencia sin cambiar coordenadas.
CREATE TABLE geofences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  sector_id uuid NOT NULL REFERENCES sectors(id),
  version integer NOT NULL CHECK(version>0),
  geometry geometry(Polygon,4326) NOT NULL,
  created_by uuid NOT NULL REFERENCES users(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  UNIQUE(id,farm_id),
  UNIQUE(sector_id,version),
  FOREIGN KEY (sector_id,farm_id) REFERENCES sectors(id,farm_id),
  CHECK(ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry) AND ST_Area(geometry)>0 AND ST_NumInteriorRings(geometry)=0 AND ST_NPoints(ST_ExteriorRing(geometry))>=5),
  CHECK(valid_to IS NULL OR valid_to>valid_from),
  EXCLUDE USING gist (sector_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&)
);

-- Identidad global del bovino; edad derivada de fecha de nacimiento.
CREATE TABLE animals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  diio text NOT NULL UNIQUE,
  name text,
  species text NOT NULL DEFAULT 'bovine' CHECK(species='bovine'),
  breed text,
  color text,
  sex text NOT NULL CHECK(sex IN ('female','male','unknown')),
  birth_date date,
  birth_date_estimated boolean NOT NULL DEFAULT false,
  production_type text NOT NULL CHECK(production_type IN ('milk','meat','dual','other')),
  status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','missing','dead','slaughtered','retired')),
  version bigint NOT NULL DEFAULT 1 CHECK(version>0),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Permanencia histórica del animal en un predio.
CREATE TABLE animal_holdings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  animal_id uuid NOT NULL REFERENCES animals(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  reason text NOT NULL,
  UNIQUE(id,farm_id),
  UNIQUE(id,animal_id,farm_id),
  CHECK(valid_to IS NULL OR valid_to>valid_from),
  EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&)
);

-- Inventario de gateways y su ubicación; no se confunde con collar.
CREATE TABLE gateways (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  gateway_eui text NOT NULL UNIQUE CHECK(gateway_eui ~ '^[0-9a-f]{16}$'),
  name text NOT NULL,
  position geometry(Point,4326),
  status text NOT NULL CHECK(status IN ('installed','maintenance','retired')),
  installed_at timestamptz,
  last_seen_at timestamptz,
  UNIQUE(id,farm_id)
);

-- Módulos físicos/collares; inventario independiente de asignación activa.
CREATE TABLE devices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  serial_number text NOT NULL UNIQUE,
  dev_eui text UNIQUE CHECK(dev_eui IS NULL OR dev_eui ~ '^[0-9a-f]{16}$'),
  transport text NOT NULL CHECK(transport IN ('academic','lorawan')),
  hardware_revision text,
  firmware_version text,
  status text NOT NULL CHECK(status IN ('available','installed','maintenance','retired')),
  interval_seconds integer NOT NULL DEFAULT 300 CHECK(interval_seconds BETWEEN 30 AND 86400),
  config_version integer NOT NULL DEFAULT 0 CHECK(config_version>=0),
  last_observed_at timestamptz,
  last_received_at timestamptz,
  UNIQUE(id,farm_id)
);

-- Historial de animal/collar sin duplicidad temporal.
CREATE TABLE assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  animal_holding_id uuid NOT NULL REFERENCES animal_holdings(id),
  animal_id uuid NOT NULL REFERENCES animals(id),
  device_id uuid NOT NULL REFERENCES devices(id),
  assigned_by uuid NOT NULL REFERENCES users(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  reason text,
  UNIQUE(id,farm_id),
  UNIQUE(id,device_id,farm_id),
  FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id),
  FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id),
  CHECK(valid_to IS NULL OR valid_to>valid_from),
  EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&),
  EXCLUDE USING gist(device_id WITH =,tstzrange(valid_from,valid_to,'[)') WITH &&)
);

-- Pastoreo temporal del animal en una versión de geocerca.
CREATE TABLE pasture_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  animal_holding_id uuid NOT NULL REFERENCES animal_holdings(id),
  animal_id uuid NOT NULL REFERENCES animals(id),
  geofence_id uuid NOT NULL REFERENCES geofences(id),
  assigned_by uuid NOT NULL REFERENCES users(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id),
  FOREIGN KEY (geofence_id,farm_id) REFERENCES geofences(id,farm_id),
  CHECK(valid_to IS NULL OR valid_to>valid_from),
  EXCLUDE USING gist (animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&)
);

-- Lectura inmutable y deduplicada; atribución por instante de captura.
CREATE TABLE telemetry (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  device_id uuid NOT NULL REFERENCES devices(id),
  assignment_id uuid REFERENCES assignments(id),
  animal_id uuid REFERENCES animals(id),
  session_id text NOT NULL,
  seq bigint NOT NULL CHECK(seq>=0),
  observed_at timestamptz NOT NULL DEFAULT now(),
  received_at timestamptz NOT NULL DEFAULT now(),
  point geometry(Point,4326),
  gnss_valid boolean NOT NULL,
  surface_temperature_c numeric CHECK(surface_temperature_c BETWEEN -60 AND 100),
  activity_index numeric CHECK(activity_index>=0),
  battery_mv integer CHECK(battery_mv BETWEEN 0 AND 20000),
  source text NOT NULL CHECK(source IN ('sim','academic','lorawan')),
  quality jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(id,farm_id),
  UNIQUE(device_id,session_id,seq),
  FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id),
  FOREIGN KEY(assignment_id,device_id,farm_id) REFERENCES assignments(id,device_id,farm_id),
  CHECK((assignment_id IS NULL)=(animal_id IS NULL)),
  CHECK((gnss_valid AND point IS NOT NULL) OR (NOT gnss_valid AND point IS NULL)),
  CHECK(point IS NULL OR (ST_X(point) BETWEEN -180 AND 180 AND ST_Y(point) BETWEEN -90 AND 90)),
  CHECK(observed_at<=received_at+interval '5 minutes')
);

-- Recepción de una lectura por gateway; varias antenas no duplican telemetría.
CREATE TABLE telemetry_receptions (
  telemetry_id uuid NOT NULL REFERENCES telemetry(id),
  farm_id uuid NOT NULL REFERENCES farms(id),
  gateway_id uuid NOT NULL REFERENCES gateways(id),
  received_at timestamptz NOT NULL DEFAULT now(),
  rssi_dbm numeric,
  snr_db numeric,
  PRIMARY KEY(telemetry_id,gateway_id),
  FOREIGN KEY (telemetry_id,farm_id) REFERENCES telemetry(id,farm_id),
  FOREIGN KEY (gateway_id,farm_id) REFERENCES gateways(id,farm_id)
);

-- Proyección reconstruible, no historial clínico.
CREATE TABLE animal_states (
  animal_id uuid PRIMARY KEY REFERENCES animals(id),
  telemetry_id uuid REFERENCES telemetry(id),
  position_telemetry_id uuid REFERENCES telemetry(id),
  geofence_status text NOT NULL DEFAULT 'unknown' CHECK(geofence_status IN ('unknown','inside','outside','pending')),
  outside_count integer NOT NULL DEFAULT 0 CHECK(outside_count>=0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Reglas configuradas por predio y auditadas.
CREATE TABLE rule_settings (
  farm_id uuid PRIMARY KEY REFERENCES farms(id),
  version integer NOT NULL DEFAULT 1 CHECK(version>0),
  battery_low_mv integer NOT NULL DEFAULT 3300 CHECK(battery_low_mv BETWEEN 0 AND 20000),
  temperature_enabled boolean NOT NULL DEFAULT false,
  temperature_high_c numeric,
  activity_enabled boolean NOT NULL DEFAULT false,
  activity_low_threshold numeric,
  activity_window_minutes integer NOT NULL DEFAULT 30 CHECK(activity_window_minutes>0),
  proximity_enabled boolean NOT NULL DEFAULT false,
  proximity_meters numeric CHECK(proximity_meters>=0),
  updated_by uuid NOT NULL REFERENCES users(id),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK(NOT temperature_enabled OR temperature_high_c IS NOT NULL),
  CHECK(NOT activity_enabled OR activity_low_threshold IS NOT NULL),
  CHECK(NOT proximity_enabled OR proximity_meters IS NOT NULL)
);

-- Alerta técnica; atender no implica resolver su condición.
CREATE TABLE events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  device_id uuid NOT NULL REFERENCES devices(id),
  animal_id uuid REFERENCES animals(id),
  telemetry_id uuid REFERENCES telemetry(id),
  geofence_id uuid REFERENCES geofences(id),
  type text NOT NULL CHECK(type IN ('escape','communication_timeout','low_battery','high_surface_temperature','low_activity','proximity','config_timeout')),
  severity text NOT NULL CHECK(severity IN ('warning','critical')),
  condition text NOT NULL CHECK(condition IN ('active','resolved')),
  attention text NOT NULL DEFAULT 'pending' CHECK(attention IN ('pending','acknowledged','in_review','concluded')),
  opened_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(id,farm_id),
  FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id),
  FOREIGN KEY (telemetry_id,farm_id) REFERENCES telemetry(id,farm_id),
  FOREIGN KEY (geofence_id,farm_id) REFERENCES geofences(id,farm_id),
  CHECK((condition='active' AND resolved_at IS NULL) OR (condition='resolved' AND resolved_at IS NOT NULL AND resolved_at>=opened_at))
);

-- Historial inmutable de atención de alertas.
CREATE TABLE event_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  event_id uuid NOT NULL REFERENCES events(id),
  actor_id uuid NOT NULL REFERENCES users(id),
  action text NOT NULL CHECK(action IN ('acknowledge','review','conclude','reopen')),
  note text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (event_id,farm_id) REFERENCES events(id,farm_id)
);

-- Ciclo solicitud/envío/confirmación de configuración.
CREATE TABLE device_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  device_id uuid NOT NULL REFERENCES devices(id),
  version integer NOT NULL CHECK(version>0),
  interval_seconds integer NOT NULL CHECK(interval_seconds BETWEEN 30 AND 86400),
  status text NOT NULL CHECK(status IN ('requested','sent','applied','failed')),
  requested_by uuid NOT NULL REFERENCES users(id),
  requested_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz,
  applied_at timestamptz,
  error text,
  UNIQUE(device_id,version),
  FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id)
);

-- Propuesta inmutable; los datos efectivos no cambian mientras esté pendiente.
CREATE TABLE change_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  requested_by uuid NOT NULL REFERENCES users(id),
  membership_id uuid REFERENCES farm_memberships(id),
  action text NOT NULL CHECK(action IN ('animal_profile','animal_status','animal_report','health_record','battery_replacement','health_schedule')),
  animal_holding_id uuid REFERENCES animal_holdings(id),
  animal_id uuid REFERENCES animals(id),
  device_id uuid REFERENCES devices(id),
  expected_version bigint CHECK(expected_version>0),
  payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
  idempotency_key uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,farm_id),
  UNIQUE(requested_by,idempotency_key),
  FOREIGN KEY (membership_id,farm_id) REFERENCES farm_memberships(id,farm_id),
  FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id),
  FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id),
  CHECK((animal_holding_id IS NULL)=(animal_id IS NULL)),
  CHECK((action='battery_replacement' AND device_id IS NOT NULL) OR (action<>'battery_replacement' AND animal_id IS NOT NULL))
);

-- Decisión única e inmutable: revisión del dueño o aplicación directa autorizada.
CREATE TABLE change_decisions (
  request_id uuid PRIMARY KEY REFERENCES change_requests(id),
  decided_by uuid NOT NULL REFERENCES users(id),
  decision text NOT NULL CHECK(decision IN ('approved','rejected','direct')),
  trust_grant_id uuid REFERENCES trust_grants(id),
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(decision<>'rejected' OR nullif(btrim(reason),'') IS NOT NULL)
);

-- Prueba única de aplicación efectiva, misma transacción que decisión y mutación.
CREATE TABLE change_applications (
  request_id uuid PRIMARY KEY REFERENCES change_decisions(request_id),
  entity_type text NOT NULL,
  entity_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Peso/altura históricos; correcciones referencian medición previa.
CREATE TABLE animal_measurements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  animal_holding_id uuid NOT NULL REFERENCES animal_holdings(id),
  animal_id uuid NOT NULL REFERENCES animals(id),
  request_id uuid NOT NULL REFERENCES change_requests(id),
  measured_at timestamptz NOT NULL DEFAULT now(),
  weight_kg numeric CHECK(weight_kg>0),
  height_cm numeric CHECK(height_cm>0),
  corrects_id uuid REFERENCES animal_measurements(id),
  UNIQUE(id,farm_id),
  FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id),
  FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id),
  CHECK(weight_kg IS NOT NULL OR height_cm IS NOT NULL)
);

-- Reporte del animal aplicado por dueño o trabajador autorizado.
CREATE TABLE animal_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  animal_holding_id uuid NOT NULL REFERENCES animal_holdings(id),
  request_id uuid NOT NULL REFERENCES change_requests(id),
  description text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (animal_holding_id,farm_id) REFERENCES animal_holdings(id,farm_id),
  FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)
);

-- Versión clínica inmutable; CRUD se expresa mediante registro, corrección y anulación.
CREATE TABLE health_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  animal_holding_id uuid NOT NULL REFERENCES animal_holdings(id),
  request_id uuid NOT NULL REFERENCES change_requests(id),
  event_type text NOT NULL CHECK(event_type IN ('examination','vaccination','antibiotic','pathology','diagnosis','procedure','injury','death','observation')),
  operation text NOT NULL CHECK(operation IN ('record','correct','void')),
  target_event_id uuid REFERENCES health_events(id),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  recorded_by uuid NOT NULL REFERENCES users(id),
  description text NOT NULL,
  diagnosis text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,farm_id),
  FOREIGN KEY (animal_holding_id,farm_id) REFERENCES animal_holdings(id,farm_id),
  FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id),
  FOREIGN KEY (target_event_id,farm_id) REFERENCES health_events(id,farm_id),
  CHECK((operation='record' AND target_event_id IS NULL) OR (operation IN ('correct','void') AND target_event_id IS NOT NULL))
);

-- Uno o varios fármacos/vacunas por evento.
CREATE TABLE health_treatments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  health_event_id uuid NOT NULL REFERENCES health_events(id),
  product_name text NOT NULL,
  product_registration text,
  batch_number text,
  dose_value numeric NOT NULL CHECK(dose_value>0),
  dose_unit text NOT NULL,
  route text NOT NULL,
  administered_at timestamptz NOT NULL DEFAULT now(),
  withdrawal_meat_until date,
  withdrawal_milk_until date,
  withdrawal_basis text,
  FOREIGN KEY (health_event_id,farm_id) REFERENCES health_events(id,farm_id)
);

-- Próxima vacuna/control/antibiótico planificado; planificación no equivale a administración.
CREATE TABLE health_schedules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  animal_holding_id uuid NOT NULL REFERENCES animal_holdings(id),
  request_id uuid NOT NULL REFERENCES change_requests(id),
  kind text NOT NULL CHECK(kind IN ('vaccination','antibiotic','checkup')),
  description text NOT NULL,
  due_at timestamptz NOT NULL DEFAULT now(),
  operation text NOT NULL CHECK(operation IN ('plan','replace','cancel','complete')),
  target_schedule_id uuid REFERENCES health_schedules(id),
  completed_event_id uuid REFERENCES health_events(id),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,farm_id),
  FOREIGN KEY (animal_holding_id,farm_id) REFERENCES animal_holdings(id,farm_id),
  FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id),
  FOREIGN KEY (target_schedule_id,farm_id) REFERENCES health_schedules(id,farm_id),
  FOREIGN KEY (completed_event_id,farm_id) REFERENCES health_events(id,farm_id),
  CHECK((operation='plan' AND target_schedule_id IS NULL) OR (operation<>'plan' AND target_schedule_id IS NOT NULL)),
  CHECK((operation='complete')=(completed_event_id IS NOT NULL))
);

-- Mantenimiento efectivo inmutable; solicitud pendiente no cambia batería confirmada.
CREATE TABLE maintenance (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  device_id uuid NOT NULL REFERENCES devices(id),
  request_id uuid REFERENCES change_requests(id),
  responsible_id uuid NOT NULL REFERENCES users(id),
  kind text NOT NULL CHECK(kind IN ('inspection','recharge','replacement','retirement')),
  battery_id text,
  result text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (device_id,farm_id) REFERENCES devices(id,farm_id),
  FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id)
);

-- Cola de avisos por alerta, solicitud o agenda, con destinatario explícito.
CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  recipient_id uuid NOT NULL REFERENCES users(id),
  event_id uuid REFERENCES events(id),
  request_id uuid REFERENCES change_requests(id),
  schedule_id uuid REFERENCES health_schedules(id),
  channel text NOT NULL CHECK(channel IN ('in_app','email','external')),
  recipient_address text,
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','failed','expired','read')),
  message text NOT NULL,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (event_id,farm_id) REFERENCES events(id,farm_id),
  FOREIGN KEY (request_id,farm_id) REFERENCES change_requests(id,farm_id),
  FOREIGN KEY (schedule_id,farm_id) REFERENCES health_schedules(id,farm_id)
);

-- Intentos inmutables; aceptación externa no prueba lectura.
CREATE TABLE notification_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  notification_id uuid NOT NULL REFERENCES notifications(id),
  attempt integer NOT NULL CHECK(attempt>0),
  status text NOT NULL,
  provider_id text,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(notification_id,attempt)
);

-- Auditoría global o predial, con identidad del actor y contexto de sesión.
CREATE TABLE audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid REFERENCES owner_accounts(id),
  farm_id uuid REFERENCES farms(id),
  actor_id uuid REFERENCES users(id),
  session_id uuid REFERENCES login_sessions(id),
  actor_kind text NOT NULL CHECK(actor_kind IN ('user','service')),
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  before_data jsonb,
  after_data jsonb,
  ip_address inet,
  request_id text,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(farm_id,account_id) REFERENCES farms(id,account_id),
  CHECK(farm_id IS NULL OR account_id IS NOT NULL),
  CHECK(actor_kind<>'user' OR actor_id IS NOT NULL)
);

-- Métricas técnicas por petición; sin body, secretos ni query string.
CREATE TABLE request_metrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid REFERENCES owner_accounts(id),
  farm_id uuid REFERENCES farms(id),
  actor_id uuid REFERENCES users(id),
  request_id text NOT NULL,
  method text NOT NULL,
  route_template text NOT NULL,
  status_code integer NOT NULL CHECK(status_code BETWEEN 100 AND 599),
  duration_ms numeric NOT NULL CHECK(duration_ms>=0),
  request_bytes bigint NOT NULL CHECK(request_bytes>=0),
  response_bytes bigint NOT NULL CHECK(response_bytes>=0),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(farm_id,account_id) REFERENCES farms(id,account_id),
  CHECK(farm_id IS NULL OR account_id IS NOT NULL)
);

-- Catálogo de módulos funcionales de software, separado del hardware.
CREATE TABLE features (
  code text PRIMARY KEY,
  name text NOT NULL
);

-- Módulos de software habilitados por predio; no es facturación.
CREATE TABLE farm_features (
  farm_id uuid NOT NULL REFERENCES farms(id),
  feature_code text NOT NULL REFERENCES features(code),
  enabled boolean NOT NULL DEFAULT true,
  enabled_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(farm_id,feature_code)
);

-- Documento de traslado opcional; estado oficial requiere evidencia externa.
CREATE TABLE sag_movements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  fma_folio text,
  origin_rup text NOT NULL,
  destination_rup text NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','confirmed','submitted','externally_confirmed','executed','cancelled')),
  departure_at timestamptz,
  arrival_at timestamptz,
  external_evidence text,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(id,farm_id),
  UNIQUE(fma_folio),
  CHECK(origin_rup<>destination_rup),
  CHECK(arrival_at IS NULL OR (departure_at IS NOT NULL AND arrival_at>=departure_at))
);

-- Detalle con DIIO preservado.
CREATE TABLE movement_animals (
  movement_id uuid NOT NULL REFERENCES sag_movements(id),
  animal_id uuid NOT NULL REFERENCES animals(id),
  diio_snapshot text NOT NULL,
  PRIMARY KEY(movement_id,animal_id)
);

-- Historial inmutable de transición del documento.
CREATE TABLE movement_status_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  movement_id uuid NOT NULL REFERENCES sag_movements(id),
  status text NOT NULL,
  actor_id uuid NOT NULL REFERENCES users(id),
  reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);
-- Se concatena tras CREATE TABLE y antes del COMMIT del esquema V3.
CREATE INDEX telemetry_device_time ON telemetry(device_id,observed_at DESC);
CREATE INDEX telemetry_animal_time ON telemetry(animal_id,observed_at DESC);
CREATE INDEX telemetry_point_gist ON telemetry USING gist(point);
CREATE INDEX geofences_geometry_gist ON geofences USING gist(geometry);
CREATE UNIQUE INDEX one_active_event ON events(device_id,type) WHERE condition='active';
CREATE UNIQUE INDEX one_pending_config ON device_configs(device_id) WHERE status IN ('requested','sent');
CREATE UNIQUE INDEX one_health_successor ON health_events(target_event_id) WHERE target_event_id IS NOT NULL;
CREATE UNIQUE INDEX one_schedule_successor ON health_schedules(target_schedule_id) WHERE target_schedule_id IS NOT NULL;
CREATE INDEX audit_account_time ON audit_log(account_id,occurred_at DESC);
CREATE INDEX audit_farm_time ON audit_log(farm_id,occurred_at DESC);
CREATE INDEX metrics_account_time ON request_metrics(account_id,occurred_at DESC);
CREATE INDEX pending_requests_lookup ON change_requests(farm_id,created_at DESC);
CREATE INDEX notification_queue ON notifications(next_attempt_at) WHERE status='pending';
CREATE INDEX membership_lookup ON farm_memberships(user_id,farm_id);

CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Registro inmutable: %',TG_TABLE_NAME; END $$;
DO $$
DECLARE tab text;
BEGIN
 FOREACH tab IN ARRAY ARRAY['telemetry','telemetry_receptions','event_actions','change_requests','change_decisions','change_applications','animal_measurements','animal_reports','health_events','health_treatments','health_schedules','maintenance','notification_attempts','audit_log','request_metrics','movement_status_events'] LOOP
 EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION forbid_mutation()',tab);
 END LOOP;
END $$;

CREATE FUNCTION validate_farm_limit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE limit_count int; current_count int;
BEGIN
 IF TG_OP='UPDATE' AND NEW.account_id<>OLD.account_id THEN RAISE EXCEPTION 'No se reasigna un predio a otro cliente'; END IF;
 SELECT max_farms INTO limit_count FROM owner_accounts WHERE id=NEW.account_id FOR UPDATE;
 SELECT count(*) INTO current_count FROM farms WHERE account_id=NEW.account_id AND active AND id<>NEW.id;
 IF NEW.active AND current_count>=limit_count THEN RAISE EXCEPTION 'Cupo de predios excedido'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER farm_limit BEFORE INSERT OR UPDATE ON farms FOR EACH ROW EXECUTE FUNCTION validate_farm_limit();

CREATE FUNCTION validate_spatial_vertices() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE vertex_count int;
BEGIN
 SELECT count(DISTINCT ST_AsEWKB((d).geom)) INTO vertex_count FROM ST_DumpPoints(ST_ExteriorRing(NEW.geometry)) AS d;
 IF vertex_count<4 THEN RAISE EXCEPTION 'Se requieren cuatro vertices distintos mas cierre'; END IF;
 IF TG_OP='UPDATE' AND (NEW.geometry IS DISTINCT FROM OLD.geometry OR NEW.sector_id<>OLD.sector_id OR NEW.farm_id<>OLD.farm_id OR NEW.version<>OLD.version OR NEW.valid_from<>OLD.valid_from) THEN RAISE EXCEPTION 'Crear nueva version para editar geocerca'; END IF;
 IF EXISTS(SELECT 1 FROM pasture_assignments p WHERE p.geofence_id=NEW.id AND NOT tstzrange(p.valid_from,p.valid_to,'[)') <@ tstzrange(NEW.valid_from,NEW.valid_to,'[)')) THEN RAISE EXCEPTION 'Cerrar/reasignar pastoreo antes de cerrar geocerca'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER geofence_vertices BEFORE INSERT OR UPDATE ON geofences FOR EACH ROW EXECUTE FUNCTION validate_spatial_vertices();

CREATE FUNCTION validate_assignment_interval() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE h animal_holdings; g geofences;
BEGIN
 SELECT * INTO STRICT h FROM animal_holdings WHERE id=NEW.animal_holding_id FOR SHARE;
 IF NOT tstzrange(NEW.valid_from,NEW.valid_to,'[)') <@ tstzrange(h.valid_from,h.valid_to,'[)') THEN RAISE EXCEPTION 'Asignacion fuera de permanencia'; END IF;
 IF TG_TABLE_NAME='pasture_assignments' THEN
  SELECT * INTO STRICT g FROM geofences WHERE id=NEW.geofence_id FOR SHARE;
  IF NOT tstzrange(NEW.valid_from,NEW.valid_to,'[)') <@ tstzrange(g.valid_from,g.valid_to,'[)') THEN RAISE EXCEPTION 'Pastoreo fuera de version geocerca'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER assignment_interval BEFORE INSERT OR UPDATE ON assignments FOR EACH ROW EXECUTE FUNCTION validate_assignment_interval();
CREATE TRIGGER pasture_interval BEFORE INSERT OR UPDATE ON pasture_assignments FOR EACH ROW EXECUTE FUNCTION validate_assignment_interval();

CREATE FUNCTION validate_holding_close() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.animal_id<>OLD.animal_id OR NEW.farm_id<>OLD.farm_id OR NEW.valid_from<>OLD.valid_from THEN RAISE EXCEPTION 'Permanencia historica no reasignable'; END IF;
 IF EXISTS(SELECT 1 FROM assignments a WHERE a.animal_holding_id=NEW.id AND NOT tstzrange(a.valid_from,a.valid_to,'[)') <@ tstzrange(NEW.valid_from,NEW.valid_to,'[)')) OR EXISTS(SELECT 1 FROM pasture_assignments a WHERE a.animal_holding_id=NEW.id AND NOT tstzrange(a.valid_from,a.valid_to,'[)') <@ tstzrange(NEW.valid_from,NEW.valid_to,'[)')) THEN RAISE EXCEPTION 'Cerrar asignaciones antes de cerrar permanencia'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER holding_close BEFORE UPDATE ON animal_holdings FOR EACH ROW EXECUTE FUNCTION validate_holding_close();

CREATE FUNCTION validate_telemetry_context() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a assignments;
BEGIN
 IF NEW.assignment_id IS NOT NULL THEN
 SELECT * INTO STRICT a FROM assignments WHERE id=NEW.assignment_id FOR SHARE;
 IF a.animal_id<>NEW.animal_id OR NOT NEW.observed_at <@ tstzrange(a.valid_from,a.valid_to,'[)') THEN RAISE EXCEPTION 'Animal o instante no corresponde a asignacion'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER telemetry_context BEFORE INSERT ON telemetry FOR EACH ROW EXECUTE FUNCTION validate_telemetry_context();

CREATE FUNCTION active_owner_or_admin(actor uuid,predio uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM users u WHERE u.id=actor AND u.status='active') AND
 (EXISTS(SELECT 1 FROM platform_admins p WHERE p.user_id=actor AND p.active) OR
 EXISTS(SELECT 1 FROM farms f JOIN owner_accounts a ON a.id=f.account_id WHERE f.id=predio AND f.active AND a.active AND a.owner_user_id=actor));
$$;

CREATE FUNCTION validate_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r change_requests; m farm_memberships; grant_row trust_grants;
BEGIN
 SELECT * INTO STRICT r FROM change_requests WHERE id=NEW.request_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.decided_by AND status='active') THEN RAISE EXCEPTION 'Actor inactivo'; END IF;
 IF NEW.decision='approved' AND NOT EXISTS(SELECT 1 FROM users WHERE id=r.requested_by AND status='active') THEN RAISE EXCEPTION 'Solicitante ya no activo'; END IF;
 IF NEW.decision='approved' AND r.membership_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM farm_memberships WHERE id=r.membership_id AND user_id=r.requested_by AND now() <@ tstzrange(valid_from,valid_to,'[)')) THEN RAISE EXCEPTION 'Membresia del solicitante ya no vigente'; END IF;
 IF NEW.decision IN ('approved','rejected') THEN
  IF NOT active_owner_or_admin(NEW.decided_by,r.farm_id) THEN RAISE EXCEPTION 'Solo dueno o administrador revisa'; END IF;
  IF NEW.trust_grant_id IS NOT NULL THEN RAISE EXCEPTION 'Revision manual no usa confianza'; END IF;
 ELSE
  IF NEW.decided_by<>r.requested_by THEN RAISE EXCEPTION 'Aplicacion directa debe conservar autor'; END IF;
  IF active_owner_or_admin(NEW.decided_by,r.farm_id) THEN
   IF NEW.trust_grant_id IS NOT NULL THEN RAISE EXCEPTION 'Dueno/admin no necesita confianza'; END IF;
  ELSE
   SELECT * INTO STRICT m FROM farm_memberships WHERE id=r.membership_id AND user_id=NEW.decided_by AND farm_id=r.farm_id AND now() <@ tstzrange(valid_from,valid_to,'[)') FOR SHARE;
   IF m.role_code='veterinarian' THEN
    IF r.action NOT IN ('animal_profile','health_record','health_schedule') OR NEW.trust_grant_id IS NOT NULL THEN RAISE EXCEPTION 'Accion no autorizada al veterinario'; END IF;
   ELSE
    SELECT * INTO STRICT grant_row FROM trust_grants WHERE id=NEW.trust_grant_id AND membership_id=m.id AND action=r.action AND now() <@ tstzrange(valid_from,valid_to,'[)') FOR SHARE;
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER decision_authorization BEFORE INSERT ON change_decisions FOR EACH ROW EXECUTE FUNCTION validate_decision();

CREATE FUNCTION validate_effective_record() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r change_requests; d change_decisions; h animal_holdings; prev_h uuid;
BEGIN
 IF NEW.request_id IS NULL THEN
  IF TG_TABLE_NAME='maintenance' AND NEW.kind<>'replacement' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Se requiere solicitud para aplicar este registro';
 END IF;
 SELECT * INTO STRICT r FROM change_requests WHERE id=NEW.request_id FOR SHARE;
 SELECT * INTO STRICT d FROM change_decisions WHERE request_id=r.id;
 IF d.decision='rejected' OR r.farm_id<>NEW.farm_id THEN RAISE EXCEPTION 'Solicitud no aprobada o contexto incorrecto'; END IF;
 IF TG_TABLE_NAME='maintenance' THEN
  IF r.action<>'battery_replacement' OR NEW.device_id IS DISTINCT FROM r.device_id OR NEW.kind<>'replacement' THEN RAISE EXCEPTION 'Mantenimiento no corresponde a solicitud'; END IF;
 ELSE
  IF NEW.animal_holding_id IS DISTINCT FROM r.animal_holding_id THEN RAISE EXCEPTION 'Permanencia no corresponde a solicitud'; END IF;
  SELECT * INTO STRICT h FROM animal_holdings WHERE id=NEW.animal_holding_id;
  IF TG_TABLE_NAME='health_events' THEN
   IF r.action<>'health_record' OR NEW.recorded_by<>r.requested_by OR NOT NEW.occurred_at <@ tstzrange(h.valid_from,h.valid_to,'[)') THEN RAISE EXCEPTION 'Evento no corresponde a solicitud o permanencia'; END IF;
   IF NEW.target_event_id IS NOT NULL THEN
    SELECT animal_holding_id INTO STRICT prev_h FROM health_events WHERE id=NEW.target_event_id;
    IF prev_h<>NEW.animal_holding_id THEN RAISE EXCEPTION 'Correccion de otro animal/permanencia'; END IF;
   END IF;
  ELSIF TG_TABLE_NAME='animal_reports' THEN
   IF r.action<>'animal_report' THEN RAISE EXCEPTION 'Tipo de solicitud incorrecto'; END IF;
  ELSIF TG_TABLE_NAME='animal_measurements' THEN
   IF r.action<>'animal_profile' OR NEW.animal_id<>h.animal_id THEN RAISE EXCEPTION 'Medicion inconsistente'; END IF;
  ELSIF TG_TABLE_NAME='health_schedules' THEN
   IF r.action<>'health_schedule' THEN RAISE EXCEPTION 'Tipo de solicitud incorrecto'; END IF;
   IF NEW.target_schedule_id IS NOT NULL THEN
    SELECT animal_holding_id INTO STRICT prev_h FROM health_schedules WHERE id=NEW.target_schedule_id;
    IF prev_h<>NEW.animal_holding_id THEN RAISE EXCEPTION 'Agenda de otro animal/permanencia'; END IF;
   END IF;
   IF NEW.completed_event_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM health_events WHERE id=NEW.completed_event_id AND animal_holding_id=NEW.animal_holding_id AND operation<>'void') THEN RAISE EXCEPTION 'Cumplimiento no corresponde al animal'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['health_events','animal_reports','animal_measurements','health_schedules','maintenance'] LOOP
 EXECUTE format('CREATE TRIGGER effective_authorization BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION validate_effective_record()',tab);
 END LOOP;
END $$;

CREATE FUNCTION validate_application() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM change_decisions WHERE request_id=NEW.request_id AND decision IN ('approved','direct')) THEN RAISE EXCEPTION 'No se aplica solicitud rechazada'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER application_check BEFORE INSERT ON change_applications FOR EACH ROW EXECUTE FUNCTION validate_application();

CREATE FUNCTION require_application_at_commit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.decision IN ('approved','direct') AND NOT EXISTS(SELECT 1 FROM change_applications WHERE request_id=NEW.request_id) THEN RAISE EXCEPTION 'Decision aceptada requiere aplicacion en misma transaccion'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER decision_application AFTER INSERT ON change_decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_application_at_commit();

CREATE FUNCTION validate_request_context() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE m farm_memberships;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.requested_by AND status='active') THEN RAISE EXCEPTION 'Solicitante inactivo'; END IF;
 IF NOT active_owner_or_admin(NEW.requested_by,NEW.farm_id) THEN
  SELECT * INTO STRICT m FROM farm_memberships WHERE id=NEW.membership_id AND user_id=NEW.requested_by AND farm_id=NEW.farm_id AND now() <@ tstzrange(valid_from,valid_to,'[)');
  IF NOT EXISTS(SELECT 1 FROM role_permissions WHERE role_code=m.role_code AND permission_code=NEW.action) THEN RAISE EXCEPTION 'Accion no permitida al solicitante'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER request_authorization BEFORE INSERT ON change_requests FOR EACH ROW EXECUTE FUNCTION validate_request_context();

CREATE FUNCTION validate_trust_context() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT active_owner_or_admin(NEW.granted_by,NEW.farm_id) OR NOT EXISTS(SELECT 1 FROM farm_memberships WHERE id=NEW.membership_id AND farm_id=NEW.farm_id AND role_code='worker') THEN RAISE EXCEPTION 'Confianza requiere dueno/admin y trabajador del predio'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trust_authorization BEFORE INSERT OR UPDATE ON trust_grants FOR EACH ROW EXECUTE FUNCTION validate_trust_context();

CREATE VIEW pending_changes AS SELECT r.* FROM change_requests r WHERE NOT EXISTS(SELECT 1 FROM change_decisions d WHERE d.request_id=r.id);
CREATE VIEW effective_health_events AS SELECT h.* FROM health_events h WHERE h.operation<>'void' AND NOT EXISTS(SELECT 1 FROM health_events n WHERE n.target_event_id=h.id);
CREATE VIEW effective_health_schedules AS SELECT s.* FROM health_schedules s WHERE s.operation IN ('plan','replace') AND NOT EXISTS(SELECT 1 FROM health_schedules n WHERE n.target_schedule_id=s.id);
CREATE VIEW installed_devices AS SELECT a.farm_id,a.device_id,a.animal_id FROM assignments a WHERE now() <@ tstzrange(a.valid_from,a.valid_to,'[)');
CREATE VIEW kpi_inventory_by_owner AS
 SELECT a.id AS account_id,a.owner_user_id,
 (SELECT count(*) FROM farms f WHERE f.account_id=a.id AND f.active) AS farms,
 (SELECT count(*) FROM sectors s JOIN farms f ON f.id=s.farm_id WHERE f.account_id=a.id AND s.active) AS sectors,
 (SELECT count(DISTINCT h.animal_id) FROM animal_holdings h JOIN farms f ON f.id=h.farm_id WHERE f.account_id=a.id AND now() <@ tstzrange(h.valid_from,h.valid_to,'[)')) AS animals,
 (SELECT count(DISTINCT m.user_id) FROM farm_memberships m JOIN farms f ON f.id=m.farm_id JOIN users u ON u.id=m.user_id WHERE f.account_id=a.id AND u.status='active' AND now() <@ tstzrange(m.valid_from,m.valid_to,'[)')) AS collaborators,
 (SELECT count(*) FROM installed_devices d JOIN farms f ON f.id=d.farm_id WHERE f.account_id=a.id) AS installed_collars,
 (SELECT count(DISTINCT ff.feature_code) FROM farm_features ff JOIN farms f ON f.id=ff.farm_id WHERE f.account_id=a.id AND ff.enabled) AS software_modules
 FROM owner_accounts a;
CREATE VIEW kpi_alerts_by_day AS SELECT f.account_id,e.farm_id,(e.opened_at AT TIME ZONE f.timezone)::date AS local_day,count(*) AS alerts FROM events e JOIN farms f ON f.id=e.farm_id GROUP BY f.account_id,e.farm_id,(e.opened_at AT TIME ZONE f.timezone)::date;

INSERT INTO roles VALUES ('platform_admin','Administrador de plataforma','platform'),('owner','Dueno','account'),('worker','Trabajador','farm'),('veterinarian','Veterinario','farm');
INSERT INTO permissions VALUES ('platform.manage','Administrar plataforma'),('account.manage','Administrar cuenta y predios'),('map.read','Consultar mapa autorizado'),('animal.read','Consultar bovinos'),('animal_profile','Modificar ficha tecnica'),('animal_status','Modificar estado'),('animal_report','Registrar reporte'),('health_record','Registrar hecho sanitario'),('health_schedule','Planificar atencion sanitaria'),('battery_replacement','Registrar reemplazo de bateria'),('changes.review','Revisar solicitudes'),('audit.read','Consultar auditoria autorizada');
INSERT INTO role_permissions SELECT 'platform_admin',code FROM permissions;
INSERT INTO role_permissions SELECT 'owner',code FROM permissions WHERE code<>'platform.manage';
INSERT INTO role_permissions SELECT 'worker',code FROM permissions WHERE code IN ('map.read','animal.read','animal_status','animal_report','health_record','battery_replacement');
INSERT INTO role_permissions SELECT 'veterinarian',code FROM permissions WHERE code IN ('map.read','animal.read','animal_profile','health_record','health_schedule');
INSERT INTO features VALUES ('monitoring','Monitoreo IoT'),('health','Ficha sanitaria'),('approvals','Aprobaciones'),('fma','Movimientos FMA');
COMMENT ON SCHEMA geocattle_v3 IS 'Propuesta V3; autorizacion HTTP, MFA y contratos de aplicacion documentados por separado';
REVOKE ALL ON SCHEMA geocattle_v3 FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA geocattle_v3 FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA geocattle_v3 FROM PUBLIC;
COMMIT;
