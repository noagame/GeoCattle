-- Esquema implementado V3: concatenación de migraciones para base vacía.
-- En operación usar el runner geocattle.migrate; no reaplicar este archivo en una base existente.

-- Fuente: 001_schema.sql
-- PostgreSQL 16 + PostGIS 3.4. UTC timestamptz; coordinates WGS84.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE TABLE farms (id uuid PRIMARY KEY, name text NOT NULL, environment text NOT NULL CHECK(environment IN ('simulation','development','production')), timezone text NOT NULL DEFAULT 'America/Santiago');
CREATE TABLE users (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, username text NOT NULL UNIQUE, password_hash text NOT NULL, role text NOT NULL CHECK(role IN ('owner','operator','viewer')), active boolean NOT NULL DEFAULT true);
CREATE TABLE login_sessions (token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users, csrf_token text NOT NULL, expires_at timestamptz NOT NULL);
CREATE INDEX login_sessions_expiry ON login_sessions(expires_at);
CREATE TABLE sectors (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, name text NOT NULL, UNIQUE(farm_id,name), UNIQUE(id,farm_id));
CREATE TABLE animals (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, diio text NOT NULL UNIQUE, name text NOT NULL, orientation text NOT NULL CHECK(orientation IN ('meat','milk')), enabled boolean NOT NULL DEFAULT true, sector_id uuid, UNIQUE(id,farm_id), FOREIGN KEY(sector_id,farm_id) REFERENCES sectors(id,farm_id));
CREATE TABLE devices (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, hardware_id text NOT NULL UNIQUE, dev_eui text UNIQUE CHECK(dev_eui IS NULL OR dev_eui ~ '^[0-9a-f]{16}$'), name text NOT NULL, transport text NOT NULL CHECK(transport IN ('academic','lorawan')), enabled boolean NOT NULL DEFAULT true, interval_seconds integer NOT NULL CHECK(interval_seconds BETWEEN 30 AND 86400), config_version integer NOT NULL DEFAULT 0, installed_at timestamptz NOT NULL, last_observed_at timestamptz, last_received_at timestamptz, last_telemetry_id uuid, UNIQUE(id,farm_id));
CREATE TABLE assignments (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, animal_id uuid NOT NULL, device_id uuid NOT NULL, valid_from timestamptz NOT NULL, valid_to timestamptz, CHECK(valid_to IS NULL OR valid_to > valid_from), FOREIGN KEY(animal_id,farm_id) REFERENCES animals(id,farm_id), FOREIGN KEY(device_id,farm_id) REFERENCES devices(id,farm_id), EXCLUDE USING gist(animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&), EXCLUDE USING gist(device_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&));
CREATE TABLE geofences (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, sector_id uuid NOT NULL, name text NOT NULL, version integer NOT NULL CHECK(version>0), geometry geometry(Polygon,4326) NOT NULL CHECK(ST_IsValid(geometry) AND NOT ST_IsEmpty(geometry) AND ST_Area(geometry)>0), active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL, valid_to timestamptz, UNIQUE(sector_id,version), UNIQUE(id,farm_id), CHECK(valid_to IS NULL OR valid_to>created_at), FOREIGN KEY(sector_id,farm_id) REFERENCES sectors(id,farm_id));
CREATE UNIQUE INDEX geofence_one_active ON geofences(sector_id) WHERE active;
CREATE INDEX geofence_geometry_gist ON geofences USING gist(geometry);
CREATE TABLE pasture_assignments (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, animal_id uuid NOT NULL, geofence_id uuid NOT NULL, valid_from timestamptz NOT NULL, valid_to timestamptz, CHECK(valid_to IS NULL OR valid_to>valid_from), FOREIGN KEY(animal_id,farm_id) REFERENCES animals(id,farm_id), FOREIGN KEY(geofence_id,farm_id) REFERENCES geofences(id,farm_id), EXCLUDE USING gist(animal_id WITH =, tstzrange(valid_from,valid_to,'[)') WITH &&));
CREATE TABLE telemetry (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, device_id uuid NOT NULL, animal_id uuid, assignment_id uuid REFERENCES assignments, session_id text NOT NULL, seq bigint NOT NULL CHECK(seq>=0), observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL, longitude double precision CHECK(longitude BETWEEN -180 AND 180), latitude double precision CHECK(latitude BETWEEN -90 AND 90), point geometry(Point,4326), gnss_valid boolean NOT NULL, surface_temperature_c double precision CHECK(surface_temperature_c BETWEEN -60 AND 100), activity_index double precision CHECK(activity_index BETWEEN 0 AND 1000000), battery_mv integer CHECK(battery_mv BETWEEN 0 AND 20000), source text NOT NULL CHECK(source IN ('sim','academic','lorawan')), quality jsonb NOT NULL DEFAULT '{}', config_version integer CHECK(config_version>=0), UNIQUE(device_id,session_id,seq), UNIQUE(id,farm_id), FOREIGN KEY(device_id,farm_id) REFERENCES devices(id,farm_id), FOREIGN KEY(animal_id,farm_id) REFERENCES animals(id,farm_id), CHECK((gnss_valid AND longitude IS NOT NULL AND latitude IS NOT NULL AND point IS NOT NULL) OR (NOT gnss_valid AND longitude IS NULL AND latitude IS NULL AND point IS NULL)), CHECK(observed_at <= received_at+interval '5 minutes'));
CREATE INDEX telemetry_device_time ON telemetry(device_id,observed_at DESC);
CREATE INDEX telemetry_animal_time ON telemetry(animal_id,observed_at DESC);
CREATE INDEX telemetry_point_gist ON telemetry USING gist(point);
ALTER TABLE devices ADD FOREIGN KEY(last_telemetry_id) REFERENCES telemetry;
CREATE TABLE animal_states (animal_id uuid PRIMARY KEY REFERENCES animals, telemetry_id uuid REFERENCES telemetry, observed_at timestamptz, position_telemetry_id uuid REFERENCES telemetry, outside_count integer NOT NULL DEFAULT 0 CHECK(outside_count>=0), geofence_status text NOT NULL DEFAULT 'unknown' CHECK(geofence_status IN ('unknown','inside','outside','pending')));
CREATE TABLE events (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, animal_id uuid, device_id uuid NOT NULL, telemetry_id uuid, geofence_id uuid, type text NOT NULL CHECK(type IN ('escape','communication_timeout','low_battery','high_surface_temperature','low_activity','proximity','config_timeout')), severity text NOT NULL CHECK(severity IN ('warning','critical')), condition text NOT NULL CHECK(condition IN ('active','resolved')), attention text NOT NULL CHECK(attention IN ('pending','acknowledged','in_review','concluded')), opened_at timestamptz NOT NULL, resolved_at timestamptz, detail jsonb NOT NULL DEFAULT '{}', FOREIGN KEY(device_id,farm_id) REFERENCES devices(id,farm_id), FOREIGN KEY(animal_id,farm_id) REFERENCES animals(id,farm_id), FOREIGN KEY(telemetry_id,farm_id) REFERENCES telemetry(id,farm_id), FOREIGN KEY(geofence_id,farm_id) REFERENCES geofences(id,farm_id), CHECK((condition='active' AND resolved_at IS NULL) OR (condition='resolved' AND resolved_at IS NOT NULL)));
CREATE UNIQUE INDEX one_active_event ON events(device_id,type) WHERE condition='active';
CREATE INDEX events_farm_condition ON events(farm_id,condition,opened_at DESC);
CREATE TABLE event_actions (id uuid PRIMARY KEY, event_id uuid NOT NULL REFERENCES events, actor_id uuid NOT NULL REFERENCES users, action text NOT NULL CHECK(action IN ('acknowledge','review','conclude','reopen')), at timestamptz NOT NULL, note text NOT NULL);
CREATE TABLE device_configs (id uuid PRIMARY KEY, device_id uuid NOT NULL REFERENCES devices, version integer NOT NULL CHECK(version>0), interval_seconds integer NOT NULL CHECK(interval_seconds BETWEEN 30 AND 86400), status text NOT NULL CHECK(status IN ('requested','sent','applied','failed')), requested_at timestamptz NOT NULL, sent_at timestamptz, applied_at timestamptz, error text, UNIQUE(device_id,version));
CREATE UNIQUE INDEX one_pending_config ON device_configs(device_id) WHERE status IN ('requested','sent');
CREATE TABLE rule_settings (farm_id uuid PRIMARY KEY REFERENCES farms, version integer NOT NULL DEFAULT 1, battery_low_mv integer NOT NULL DEFAULT 3300 CHECK(battery_low_mv BETWEEN 0 AND 20000), temperature_high_c double precision DEFAULT 39.5 CHECK(temperature_high_c BETWEEN -60 AND 100), activity_low_threshold double precision DEFAULT 0.1 CHECK(activity_low_threshold BETWEEN 0 AND 1000000), activity_window_minutes integer NOT NULL DEFAULT 30 CHECK(activity_window_minutes BETWEEN 1 AND 1440), proximity_meters double precision NOT NULL DEFAULT 10 CHECK(proximity_meters BETWEEN 0 AND 1000), temperature_enabled boolean NOT NULL DEFAULT false, activity_enabled boolean NOT NULL DEFAULT false, proximity_enabled boolean NOT NULL DEFAULT false, CHECK(NOT temperature_enabled OR temperature_high_c IS NOT NULL), CHECK(NOT activity_enabled OR activity_low_threshold IS NOT NULL));
CREATE TABLE audit_log (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, actor_id uuid REFERENCES users, object_type text NOT NULL, object_id text NOT NULL, action text NOT NULL, at timestamptz NOT NULL, before jsonb, after jsonb);
CREATE INDEX audit_farm_time ON audit_log(farm_id,at DESC);
CREATE TABLE notifications (id uuid PRIMARY KEY, event_id uuid NOT NULL REFERENCES events, status text NOT NULL CHECK(status IN ('pending','accepted','failed','expired','disabled')), channel text NOT NULL, requested_at timestamptz, created_at timestamptz NOT NULL, next_attempt_at timestamptz NOT NULL);
CREATE TABLE notification_attempts (id uuid PRIMARY KEY, notification_id uuid NOT NULL REFERENCES notifications, attempt integer NOT NULL CHECK(attempt>0), at timestamptz NOT NULL, status text NOT NULL CHECK(status IN ('accepted','failed','expired','disabled')), provider_id text, error text, UNIQUE(notification_id,attempt));
CREATE FUNCTION prevent_immutable_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Immutable record cannot be updated or deleted'; END $$;
CREATE TRIGGER telemetry_immutable BEFORE UPDATE OR DELETE ON telemetry FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();
CREATE TRIGGER actions_immutable BEFORE UPDATE OR DELETE ON event_actions FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();
CREATE TRIGGER notification_attempts_immutable BEFORE UPDATE OR DELETE ON notification_attempts FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();


-- Fuente: 002_maintenance.sql
CREATE TABLE maintenance (id uuid PRIMARY KEY, farm_id uuid NOT NULL REFERENCES farms, device_id uuid NOT NULL, battery_id text, kind text NOT NULL CHECK(kind IN ('inspection','recharge','replacement','retirement')), at timestamptz NOT NULL, responsible_id uuid NOT NULL REFERENCES users, result text NOT NULL, FOREIGN KEY(device_id,farm_id) REFERENCES devices(id,farm_id));
CREATE INDEX maintenance_farm_time ON maintenance(farm_id,at DESC);
CREATE TRIGGER maintenance_immutable BEFORE UPDATE OR DELETE ON maintenance FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation();


-- Fuente: 003_application_v3.sql
-- GeoCattle V3: migración aditiva sobre public; no crea otra base ni elimina datos.
-- Ejecutar mediante geocattle.migrate, bajo su transacción y advisory lock.
-- La cuenta global conserva username y el predio legado de V1 por compatibilidad.
ALTER TABLE users DROP CONSTRAINT users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK(role IN ('admin','owner','worker','veterinarian','operator','viewer'));
ALTER TABLE users ALTER COLUMN farm_id DROP NOT NULL;
ALTER TABLE users ADD COLUMN email text;
ALTER TABLE users ADD COLUMN full_name text NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN phone text;
ALTER TABLE users ADD COLUMN version bigint NOT NULL DEFAULT 1 CHECK(version>0);
ALTER TABLE users ADD COLUMN email_verified_at timestamptz;
ALTER TABLE users ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
UPDATE users SET email=lower(btrim(username)) WHERE position('@' in username)>1
 AND NOT EXISTS(SELECT 1 FROM users other WHERE other.id<>users.id AND lower(btrim(other.username))=lower(btrim(users.username)));
UPDATE users SET full_name=username WHERE full_name='';
ALTER TABLE users ADD CONSTRAINT users_email_check CHECK(email IS NULL OR (email=lower(btrim(email)) AND position('@' in email)>1));
CREATE UNIQUE INDEX users_email_unique ON users(email) WHERE email IS NOT NULL;


CREATE TABLE platform_admins (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

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

CREATE TABLE mfa_recovery_codes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  code_hash text NOT NULL UNIQUE,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

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

CREATE TABLE roles (
  code text PRIMARY KEY,
  name text NOT NULL,
  scope text NOT NULL CHECK(scope IN ('platform','account','farm'))
);

CREATE TABLE permissions (
  code text PRIMARY KEY,
  description text NOT NULL
);

CREATE TABLE role_permissions (
  role_code text NOT NULL REFERENCES roles(code),
  permission_code text NOT NULL REFERENCES permissions(code),
  PRIMARY KEY(role_code,permission_code)
);

CREATE TABLE owner_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id uuid NOT NULL REFERENCES users(id),
  display_name text NOT NULL,
  max_farms integer NOT NULL DEFAULT 1 CHECK(max_farms>0),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(owner_user_id)
);

-- account_id permite NULL únicamente para bootstrap/fixtures V1 sin dueño aún.
ALTER TABLE farms ADD COLUMN account_id uuid REFERENCES owner_accounts(id);
ALTER TABLE farms ADD COLUMN rup text UNIQUE;
ALTER TABLE farms ADD COLUMN address text;
ALTER TABLE farms ADD COLUMN region text;
ALTER TABLE farms ADD COLUMN commune text;
ALTER TABLE farms ADD COLUMN boundary geometry(MultiPolygon,4326);
ALTER TABLE farms ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE farms ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE farms ADD CONSTRAINT farms_id_account_unique UNIQUE(id,account_id);
ALTER TABLE farms ADD CONSTRAINT farm_boundary_valid CHECK(boundary IS NULL OR (ST_IsValid(boundary) AND NOT ST_IsEmpty(boundary) AND ST_Area(boundary)>0));

ALTER TABLE login_sessions ADD COLUMN active_farm_id uuid REFERENCES farms(id);
ALTER TABLE login_sessions ADD COLUMN mfa_verified_at timestamptz;
ALTER TABLE login_sessions ADD COLUMN step_up_at timestamptz;
ALTER TABLE login_sessions ADD COLUMN authenticated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE login_sessions ADD COLUMN last_seen_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE login_sessions ADD COLUMN revoked_at timestamptz;
UPDATE login_sessions s SET active_farm_id=u.farm_id FROM users u WHERE u.id=s.user_id;

-- Reto previo al login o de elevación contextual. Nunca guarda el OTP ni el token en claro.
CREATE TABLE auth_challenges (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES users(id),
 token_hash text NOT NULL UNIQUE,
 purpose text NOT NULL CHECK(purpose IN ('login','step_up','mfa_setup','verify_email','reset_password','close_account')),
 session_token_hash text REFERENCES login_sessions(token_hash),
 operation_digest text,
 expires_at timestamptz NOT NULL,
 verified_at timestamptz,
 consumed_at timestamptz,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_challenges_expiry ON auth_challenges(expires_at);

INSERT INTO roles VALUES ('admin','Administrador de plataforma','platform'),('owner','Dueño','account'),('worker','Trabajador','farm'),('veterinarian','Veterinario','farm'),('operator','Operador legado','farm'),('viewer','Consulta legado','farm');
INSERT INTO permissions VALUES ('platform.manage','Administrar plataforma'),('account.manage','Administrar cuenta y predios'),('map.read','Consultar mapa autorizado'),('animal.read','Consultar bovinos'),('animal_profile','Modificar ficha técnica'),('animal_status','Modificar estado'),('animal_report','Registrar reporte'),('health_record','Registrar hecho sanitario'),('health_schedule','Planificar atención sanitaria'),('battery_replacement','Registrar reemplazo de batería'),('changes.review','Revisar solicitudes'),('audit.read','Consultar auditoría autorizada');
INSERT INTO role_permissions SELECT 'admin',code FROM permissions;
INSERT INTO role_permissions SELECT 'owner',code FROM permissions WHERE code<>'platform.manage';
INSERT INTO role_permissions SELECT r.code,p.code FROM roles r CROSS JOIN permissions p WHERE r.code IN ('worker','operator') AND p.code IN ('map.read','animal.read','animal_status','animal_report','health_record','battery_replacement');
INSERT INTO role_permissions SELECT 'veterinarian',code FROM permissions WHERE code IN ('map.read','animal.read','animal_profile','health_record','health_schedule');
INSERT INTO role_permissions SELECT 'viewer',code FROM permissions WHERE code IN ('map.read','animal.read');

CREATE TABLE farm_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farms(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role_code text NOT NULL REFERENCES roles(code) CHECK(role_code IN ('owner','worker','veterinarian','operator','viewer')),
  granted_by uuid NOT NULL REFERENCES users(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  UNIQUE(id,farm_id),
  CHECK(valid_to IS NULL OR valid_to>valid_from),
  EXCLUDE USING gist (user_id WITH =,farm_id WITH =,tstzrange(valid_from,valid_to,'[)') WITH &&)
);

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

ALTER TABLE sectors ADD COLUMN land_use text NOT NULL DEFAULT 'grazing' CHECK(land_use IN ('grazing','available','cropped','restricted','other'));
ALTER TABLE sectors ADD COLUMN description text;
ALTER TABLE sectors ADD COLUMN active boolean NOT NULL DEFAULT true;

ALTER TABLE animals ADD COLUMN species text NOT NULL DEFAULT 'bovine' CHECK(species='bovine');
ALTER TABLE animals ADD COLUMN breed text;
ALTER TABLE animals ADD COLUMN color text;
ALTER TABLE animals ADD COLUMN sex text NOT NULL DEFAULT 'unknown' CHECK(sex IN ('female','male','unknown'));
ALTER TABLE animals ADD COLUMN birth_date date;
ALTER TABLE animals ADD COLUMN birth_date_estimated boolean NOT NULL DEFAULT false;
ALTER TABLE animals ADD COLUMN production_type text NOT NULL DEFAULT 'other' CHECK(production_type IN ('milk','meat','dual','other'));
ALTER TABLE animals ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','missing','dead','slaughtered','retired'));
ALTER TABLE animals ADD COLUMN version bigint NOT NULL DEFAULT 1 CHECK(version>0);
ALTER TABLE animals ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
UPDATE animals SET production_type=orientation;

ALTER TABLE devices ADD COLUMN serial_number text UNIQUE;
ALTER TABLE devices ADD COLUMN hardware_revision text;
ALTER TABLE devices ADD COLUMN firmware_version text;
ALTER TABLE devices ADD COLUMN status text NOT NULL DEFAULT 'available' CHECK(status IN ('available','installed','maintenance','retired'));
UPDATE devices d SET serial_number=d.hardware_id,status=CASE WHEN NOT d.enabled THEN 'retired' WHEN EXISTS(SELECT 1 FROM assignments a WHERE a.device_id=d.id AND now() <@ tstzrange(a.valid_from,a.valid_to,'[)')) THEN 'installed' ELSE 'available' END;


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

CREATE TABLE change_decisions (
  request_id uuid PRIMARY KEY REFERENCES change_requests(id),
  decided_by uuid NOT NULL REFERENCES users(id),
  decision text NOT NULL CHECK(decision IN ('approved','rejected','direct')),
  trust_grant_id uuid REFERENCES trust_grants(id),
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(decision<>'rejected' OR nullif(btrim(reason),'') IS NOT NULL)
);

CREATE TABLE change_applications (
  request_id uuid PRIMARY KEY REFERENCES change_decisions(request_id),
  entity_type text NOT NULL,
  entity_id uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

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

CREATE TABLE features (
  code text PRIMARY KEY,
  name text NOT NULL
);

CREATE TABLE farm_features (
  farm_id uuid NOT NULL REFERENCES farms(id),
  feature_code text NOT NULL REFERENCES features(code),
  enabled boolean NOT NULL DEFAULT true,
  enabled_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(farm_id,feature_code)
);

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

CREATE TABLE movement_animals (
  movement_id uuid NOT NULL REFERENCES sag_movements(id),
  animal_id uuid NOT NULL REFERENCES animals(id),
  diio_snapshot text NOT NULL,
  PRIMARY KEY(movement_id,animal_id)
);

CREATE TABLE movement_status_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  movement_id uuid NOT NULL REFERENCES sag_movements(id),
  status text NOT NULL,
  actor_id uuid NOT NULL REFERENCES users(id),
  reason text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Las columnas históricas nuevas son opcionales para mantener escrituras V1.
ALTER TABLE assignments ADD COLUMN animal_holding_id uuid;
ALTER TABLE assignments ADD COLUMN assigned_by uuid REFERENCES users(id);
ALTER TABLE assignments ADD COLUMN reason text;
ALTER TABLE assignments ADD CONSTRAINT assignment_holding_farm FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id);
ALTER TABLE pasture_assignments ADD COLUMN animal_holding_id uuid;
ALTER TABLE pasture_assignments ADD COLUMN assigned_by uuid REFERENCES users(id);
ALTER TABLE pasture_assignments ADD CONSTRAINT pasture_holding_farm FOREIGN KEY(animal_holding_id,animal_id,farm_id) REFERENCES animal_holdings(id,animal_id,farm_id);
ALTER TABLE geofences ADD COLUMN created_by uuid REFERENCES users(id);
ALTER TABLE maintenance ADD COLUMN request_id uuid;
ALTER TABLE maintenance ADD CONSTRAINT maintenance_request_farm FOREIGN KEY(request_id,farm_id) REFERENCES change_requests(id,farm_id);

ALTER TABLE notifications ALTER COLUMN event_id DROP NOT NULL;
ALTER TABLE notifications ADD COLUMN farm_id uuid REFERENCES farms(id);
ALTER TABLE notifications ADD COLUMN recipient_id uuid REFERENCES users(id);
ALTER TABLE notifications ADD COLUMN request_id uuid;
ALTER TABLE notifications ADD COLUMN schedule_id uuid;
ALTER TABLE notifications ADD COLUMN recipient_address text;
ALTER TABLE notifications ADD COLUMN message text NOT NULL DEFAULT '';
ALTER TABLE notifications ADD COLUMN read_at timestamptz;
ALTER TABLE notifications ADD CONSTRAINT notification_request_farm FOREIGN KEY(request_id,farm_id) REFERENCES change_requests(id,farm_id);
ALTER TABLE notifications ADD CONSTRAINT notification_schedule_farm FOREIGN KEY(schedule_id,farm_id) REFERENCES health_schedules(id,farm_id);
ALTER TABLE notifications DROP CONSTRAINT notifications_status_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_status_check CHECK(status IN ('pending','accepted','failed','expired','disabled','read'));
UPDATE notifications n SET farm_id=e.farm_id FROM events e WHERE e.id=n.event_id;

ALTER TABLE audit_log ALTER COLUMN farm_id DROP NOT NULL;
ALTER TABLE audit_log ADD COLUMN account_id uuid REFERENCES owner_accounts(id);
ALTER TABLE audit_log ADD COLUMN session_token_hash text REFERENCES login_sessions(token_hash);
ALTER TABLE audit_log ADD COLUMN actor_kind text NOT NULL DEFAULT 'service' CHECK(actor_kind IN ('user','service'));
ALTER TABLE audit_log ADD COLUMN ip_address inet;
ALTER TABLE audit_log ADD COLUMN request_id text;
ALTER TABLE audit_log ADD CONSTRAINT audit_account_farm FOREIGN KEY(farm_id,account_id) REFERENCES farms(id,account_id);

-- Backfill determinista y no destructivo: nunca cambia claves, roles o contraseñas V1.
INSERT INTO owner_accounts(owner_user_id,display_name,max_farms)
 SELECT id,CASE WHEN full_name='' THEN username ELSE full_name END,1 FROM users WHERE role='owner';
UPDATE farms f SET account_id=(SELECT a.id FROM owner_accounts a JOIN users u ON u.id=a.owner_user_id WHERE u.farm_id=f.id ORDER BY u.username,u.id LIMIT 1);
UPDATE owner_accounts a SET max_farms=greatest(1,(SELECT count(*) FROM farms f WHERE f.account_id=a.id));
INSERT INTO farm_memberships(farm_id,user_id,role_code,granted_by,valid_from)
 SELECT u.farm_id,u.id,CASE WHEN u.role='operator' THEN 'worker' ELSE u.role END,coalesce(a.owner_user_id,u.id),u.created_at
 FROM users u JOIN farms f ON f.id=u.farm_id LEFT JOIN owner_accounts a ON a.id=f.account_id
 WHERE u.role IN ('owner','operator','worker','viewer','veterinarian');
INSERT INTO animal_holdings(farm_id,animal_id,valid_from,reason)
 SELECT a.farm_id,a.id,least(a.created_at,coalesce((SELECT min(x.valid_from) FROM assignments x WHERE x.animal_id=a.id),a.created_at),coalesce((SELECT min(x.valid_from) FROM pasture_assignments x WHERE x.animal_id=a.id),a.created_at),coalesce((SELECT min(t.observed_at) FROM telemetry t WHERE t.animal_id=a.id),a.created_at)),'legacy_backfill'
 FROM animals a;
UPDATE assignments a SET animal_holding_id=h.id FROM animal_holdings h WHERE h.animal_id=a.animal_id AND h.farm_id=a.farm_id;
UPDATE pasture_assignments a SET animal_holding_id=h.id FROM animal_holdings h WHERE h.animal_id=a.animal_id AND h.farm_id=a.farm_id;
INSERT INTO features VALUES ('monitoring','Monitoreo IoT'),('health','Ficha sanitaria'),('approvals','Aprobaciones'),('fma','Movimientos FMA');
INSERT INTO farm_features(farm_id,feature_code) SELECT f.id,c.code FROM farms f CROSS JOIN features c WHERE c.code<>'fma';

CREATE UNIQUE INDEX one_health_successor ON health_events(target_event_id) WHERE target_event_id IS NOT NULL;
CREATE UNIQUE INDEX one_schedule_successor ON health_schedules(target_schedule_id) WHERE target_schedule_id IS NOT NULL;
CREATE INDEX audit_account_time ON audit_log(account_id,at DESC);
CREATE INDEX metrics_account_time ON request_metrics(account_id,occurred_at DESC);
CREATE INDEX pending_requests_lookup ON change_requests(farm_id,created_at DESC);
CREATE INDEX membership_lookup ON farm_memberships(user_id,farm_id);
CREATE INDEX health_event_lookup ON health_events(animal_holding_id,occurred_at DESC);
CREATE INDEX health_schedule_lookup ON health_schedules(animal_holding_id,due_at);
CREATE INDEX notification_recipient_time ON notifications(recipient_id,created_at DESC);
CREATE INDEX gateway_farm_lookup ON gateways(farm_id);
CREATE INDEX farm_account_lookup ON farms(account_id);

-- Inmutabilidad efectiva también a nivel de la base (no depende del panel).
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['telemetry_receptions','change_requests','change_decisions','change_applications','animal_measurements','animal_reports','health_events','health_treatments','health_schedules','request_metrics','movement_status_events'] LOOP
 EXECUTE format('CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION prevent_immutable_mutation()',tab);
 END LOOP;
END $$;

CREATE FUNCTION validate_farm_limit_v3() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE limit_count int; current_count int;
BEGIN
 IF TG_OP='UPDATE' AND OLD.account_id IS NOT NULL AND NEW.account_id IS DISTINCT FROM OLD.account_id THEN RAISE EXCEPTION 'No se reasigna un predio a otro cliente' USING ERRCODE='23514'; END IF;
 IF NEW.account_id IS NULL THEN RETURN NEW; END IF;
 SELECT max_farms INTO STRICT limit_count FROM owner_accounts WHERE id=NEW.account_id FOR UPDATE;
 SELECT count(*) INTO current_count FROM farms WHERE account_id=NEW.account_id AND active AND id<>NEW.id;
 IF NEW.active AND current_count>=limit_count THEN RAISE EXCEPTION 'Cupo de predios excedido' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER farm_limit_v3 BEFORE INSERT OR UPDATE ON farms FOR EACH ROW EXECUTE FUNCTION validate_farm_limit_v3();

CREATE FUNCTION validate_geofence_v3() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE vertex_count int;
BEGIN
 IF TG_OP='INSERT' THEN
  SELECT count(DISTINCT ST_AsEWKB((d).geom)) INTO vertex_count FROM ST_DumpPoints(ST_ExteriorRing(NEW.geometry)) AS d;
  IF vertex_count<4 OR ST_NumInteriorRings(NEW.geometry)<>0 THEN RAISE EXCEPTION 'Se requieren cuatro vertices distintos, sin huecos y mas cierre' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='UPDATE' AND (NEW.geometry IS DISTINCT FROM OLD.geometry OR NEW.sector_id<>OLD.sector_id OR NEW.farm_id<>OLD.farm_id OR NEW.version<>OLD.version OR NEW.created_at<>OLD.created_at) THEN RAISE EXCEPTION 'Crear nueva version para editar geocerca' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER geofence_vertices_v3 BEFORE INSERT OR UPDATE ON geofences FOR EACH ROW EXECUTE FUNCTION validate_geofence_v3();

CREATE FUNCTION validate_assignment_interval_v3() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE h animal_holdings; g geofences;
BEGIN
 -- Una escritura V1 puede carecer de holding_id; sus FK y exclusiones originales siguen vigentes.
 IF NEW.animal_holding_id IS NOT NULL THEN
  SELECT * INTO STRICT h FROM animal_holdings WHERE id=NEW.animal_holding_id FOR SHARE;
  IF NOT tstzrange(NEW.valid_from,NEW.valid_to,'[)') <@ tstzrange(h.valid_from,h.valid_to,'[)') THEN RAISE EXCEPTION 'Asignacion fuera de permanencia' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='pasture_assignments' THEN
  SELECT * INTO STRICT g FROM geofences WHERE id=NEW.geofence_id FOR SHARE;
  IF NOT tstzrange(NEW.valid_from,NEW.valid_to,'[)') <@ tstzrange(g.created_at,g.valid_to,'[)') THEN RAISE EXCEPTION 'Pastoreo fuera de version geocerca' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER assignment_interval_v3 BEFORE INSERT OR UPDATE ON assignments FOR EACH ROW EXECUTE FUNCTION validate_assignment_interval_v3();
CREATE TRIGGER pasture_interval_v3 BEFORE INSERT OR UPDATE ON pasture_assignments FOR EACH ROW EXECUTE FUNCTION validate_assignment_interval_v3();
CREATE FUNCTION validate_holding_close() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.animal_id<>OLD.animal_id OR NEW.farm_id<>OLD.farm_id OR NEW.valid_from<>OLD.valid_from THEN RAISE EXCEPTION 'Permanencia historica no reasignable' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM assignments a WHERE a.animal_holding_id=NEW.id AND NOT tstzrange(a.valid_from,a.valid_to,'[)') <@ tstzrange(NEW.valid_from,NEW.valid_to,'[)')) OR EXISTS(SELECT 1 FROM pasture_assignments a WHERE a.animal_holding_id=NEW.id AND NOT tstzrange(a.valid_from,a.valid_to,'[)') <@ tstzrange(NEW.valid_from,NEW.valid_to,'[)')) THEN RAISE EXCEPTION 'Cerrar asignaciones antes de cerrar permanencia' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER holding_close BEFORE UPDATE ON animal_holdings FOR EACH ROW EXECUTE FUNCTION validate_holding_close();

CREATE FUNCTION validate_telemetry_context() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a assignments;
BEGIN
 IF NEW.assignment_id IS NOT NULL THEN
 SELECT * INTO STRICT a FROM assignments WHERE id=NEW.assignment_id FOR SHARE;
 IF a.animal_id IS DISTINCT FROM NEW.animal_id OR a.device_id<>NEW.device_id OR a.farm_id<>NEW.farm_id OR NOT NEW.observed_at <@ tstzrange(a.valid_from,a.valid_to,'[)') THEN RAISE EXCEPTION 'Animal o instante no corresponde a asignacion' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER telemetry_context BEFORE INSERT ON telemetry FOR EACH ROW EXECUTE FUNCTION validate_telemetry_context();

CREATE FUNCTION active_owner_or_admin(actor uuid,predio uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM users u WHERE u.id=actor AND u.active) AND
 (EXISTS(SELECT 1 FROM users p WHERE p.id=actor AND p.active AND p.role='admin') OR EXISTS(SELECT 1 FROM platform_admins p WHERE p.user_id=actor AND p.active) OR
 EXISTS(SELECT 1 FROM farms f JOIN owner_accounts a ON a.id=f.account_id WHERE f.id=predio AND f.active AND a.active AND a.owner_user_id=actor));
$$;

CREATE FUNCTION validate_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r change_requests; m farm_memberships; grant_row trust_grants;
BEGIN
 SELECT * INTO STRICT r FROM change_requests WHERE id=NEW.request_id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.decided_by AND active) THEN RAISE EXCEPTION 'Actor inactivo' USING ERRCODE='23514'; END IF;
 IF NEW.decision='approved' AND NOT EXISTS(SELECT 1 FROM users WHERE id=r.requested_by AND active) THEN RAISE EXCEPTION 'Solicitante ya no activo' USING ERRCODE='23514'; END IF;
 IF NEW.decision='approved' AND r.membership_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM farm_memberships WHERE id=r.membership_id AND user_id=r.requested_by AND now() <@ tstzrange(valid_from,valid_to,'[)')) THEN RAISE EXCEPTION 'Membresia del solicitante ya no vigente' USING ERRCODE='23514'; END IF;
 IF NEW.decision IN ('approved','rejected') THEN
  IF NOT active_owner_or_admin(NEW.decided_by,r.farm_id) THEN RAISE EXCEPTION 'Solo dueno o administrador revisa' USING ERRCODE='23514'; END IF;
  IF NEW.trust_grant_id IS NOT NULL THEN RAISE EXCEPTION 'Revision manual no usa confianza' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.decided_by<>r.requested_by THEN RAISE EXCEPTION 'Aplicacion directa debe conservar autor' USING ERRCODE='23514'; END IF;
  IF active_owner_or_admin(NEW.decided_by,r.farm_id) THEN
   IF NEW.trust_grant_id IS NOT NULL THEN RAISE EXCEPTION 'Dueno/admin no necesita confianza' USING ERRCODE='23514'; END IF;
  ELSE
   SELECT * INTO STRICT m FROM farm_memberships WHERE id=r.membership_id AND user_id=NEW.decided_by AND farm_id=r.farm_id AND now() <@ tstzrange(valid_from,valid_to,'[)') FOR SHARE;
   IF m.role_code='veterinarian' THEN
    IF r.action NOT IN ('animal_profile','health_record','health_schedule') OR NEW.trust_grant_id IS NOT NULL THEN RAISE EXCEPTION 'Accion no autorizada al veterinario' USING ERRCODE='23514'; END IF;
   ELSIF m.role_code IN ('worker','operator') THEN
    SELECT * INTO STRICT grant_row FROM trust_grants WHERE id=NEW.trust_grant_id AND membership_id=m.id AND action=r.action AND now() <@ tstzrange(valid_from,valid_to,'[)') FOR SHARE;
   ELSE RAISE EXCEPTION 'Perfil sin permiso para aplicacion directa' USING ERRCODE='23514';
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
  IF TG_TABLE_NAME='maintenance' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Se requiere solicitud para aplicar este registro' USING ERRCODE='23514';
 END IF;
 SELECT * INTO STRICT r FROM change_requests WHERE id=NEW.request_id FOR SHARE;
 SELECT * INTO STRICT d FROM change_decisions WHERE request_id=r.id;
 IF d.decision='rejected' OR r.farm_id<>NEW.farm_id THEN RAISE EXCEPTION 'Solicitud no aprobada o contexto incorrecto' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='maintenance' THEN
  IF r.action<>'battery_replacement' OR NEW.device_id IS DISTINCT FROM r.device_id OR NEW.kind<>'replacement' THEN RAISE EXCEPTION 'Mantenimiento no corresponde a solicitud' USING ERRCODE='23514'; END IF;
 ELSE
  IF NEW.animal_holding_id IS DISTINCT FROM r.animal_holding_id THEN RAISE EXCEPTION 'Permanencia no corresponde a solicitud' USING ERRCODE='23514'; END IF;
  SELECT * INTO STRICT h FROM animal_holdings WHERE id=NEW.animal_holding_id;
  IF TG_TABLE_NAME='health_events' THEN
   IF r.action<>'health_record' OR NEW.recorded_by<>r.requested_by OR NOT NEW.occurred_at <@ tstzrange(h.valid_from,h.valid_to,'[)') THEN RAISE EXCEPTION 'Evento no corresponde a solicitud o permanencia' USING ERRCODE='23514'; END IF;
   IF NEW.target_event_id IS NOT NULL THEN
    SELECT animal_holding_id INTO STRICT prev_h FROM health_events WHERE id=NEW.target_event_id;
    IF prev_h<>NEW.animal_holding_id THEN RAISE EXCEPTION 'Correccion de otro animal/permanencia' USING ERRCODE='23514'; END IF;
   END IF;
  ELSIF TG_TABLE_NAME='animal_reports' THEN
   IF r.action<>'animal_report' THEN RAISE EXCEPTION 'Tipo de solicitud incorrecto' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='animal_measurements' THEN
   IF r.action<>'animal_profile' OR NEW.animal_id<>h.animal_id THEN RAISE EXCEPTION 'Medicion inconsistente' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='health_schedules' THEN
   IF r.action<>'health_schedule' THEN RAISE EXCEPTION 'Tipo de solicitud incorrecto' USING ERRCODE='23514'; END IF;
   IF NEW.target_schedule_id IS NOT NULL THEN
    SELECT animal_holding_id INTO STRICT prev_h FROM health_schedules WHERE id=NEW.target_schedule_id;
    IF prev_h<>NEW.animal_holding_id THEN RAISE EXCEPTION 'Agenda de otro animal/permanencia' USING ERRCODE='23514'; END IF;
   END IF;
   IF NEW.completed_event_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM health_events WHERE id=NEW.completed_event_id AND animal_holding_id=NEW.animal_holding_id AND operation<>'void') THEN RAISE EXCEPTION 'Cumplimiento no corresponde al animal' USING ERRCODE='23514'; END IF;
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
 IF NOT EXISTS(SELECT 1 FROM change_decisions WHERE request_id=NEW.request_id AND decision IN ('approved','direct')) THEN RAISE EXCEPTION 'No se aplica solicitud rechazada' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER application_check BEFORE INSERT ON change_applications FOR EACH ROW EXECUTE FUNCTION validate_application();

CREATE FUNCTION require_application_at_commit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.decision IN ('approved','direct') AND NOT EXISTS(SELECT 1 FROM change_applications WHERE request_id=NEW.request_id) THEN RAISE EXCEPTION 'Decision aceptada requiere aplicacion en misma transaccion' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER decision_application AFTER INSERT ON change_decisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_application_at_commit();

CREATE FUNCTION validate_request_context() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE m farm_memberships;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.requested_by AND active) THEN RAISE EXCEPTION 'Solicitante inactivo' USING ERRCODE='23514'; END IF;
 IF NOT active_owner_or_admin(NEW.requested_by,NEW.farm_id) THEN
  SELECT * INTO STRICT m FROM farm_memberships WHERE id=NEW.membership_id AND user_id=NEW.requested_by AND farm_id=NEW.farm_id AND now() <@ tstzrange(valid_from,valid_to,'[)');
  IF NOT EXISTS(SELECT 1 FROM role_permissions WHERE role_code=m.role_code AND permission_code=NEW.action) THEN RAISE EXCEPTION 'Accion no permitida al solicitante' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER request_authorization BEFORE INSERT ON change_requests FOR EACH ROW EXECUTE FUNCTION validate_request_context();

CREATE FUNCTION validate_trust_context() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT active_owner_or_admin(NEW.granted_by,NEW.farm_id) OR NOT EXISTS(SELECT 1 FROM farm_memberships WHERE id=NEW.membership_id AND farm_id=NEW.farm_id AND role_code IN ('worker','operator')) THEN RAISE EXCEPTION 'Confianza requiere dueno/admin y trabajador del predio' USING ERRCODE='23514'; END IF;
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
 (SELECT count(DISTINCT m.user_id) FROM farm_memberships m JOIN farms f ON f.id=m.farm_id JOIN users u ON u.id=m.user_id WHERE f.account_id=a.id AND u.active AND m.role_code<>'owner' AND now() <@ tstzrange(m.valid_from,m.valid_to,'[)')) AS collaborators,
 (SELECT count(*) FROM installed_devices d JOIN farms f ON f.id=d.farm_id WHERE f.account_id=a.id) AS installed_collars,
 (SELECT count(DISTINCT ff.feature_code) FROM farm_features ff JOIN farms f ON f.id=ff.farm_id WHERE f.account_id=a.id AND ff.enabled) AS software_modules
 FROM owner_accounts a;
CREATE VIEW kpi_alerts_by_day AS SELECT f.account_id,e.farm_id,(e.opened_at AT TIME ZONE f.timezone)::date AS local_day,count(*) AS alerts FROM events e JOIN farms f ON f.id=e.farm_id GROUP BY f.account_id,e.farm_id,(e.opened_at AT TIME ZONE f.timezone)::date;

COMMENT ON COLUMN farms.account_id IS 'Cuenta cliente V3; NULL reservado a provisionamiento legado V1 pendiente de asociacion';
COMMENT ON COLUMN users.farm_id IS 'Contexto inicial legado V1; V3 resuelve alcance mediante owner_accounts y farm_memberships';
COMMENT ON TABLE change_requests IS 'Propuesta inmutable; pendiente hasta decision/aplicacion atomica';
COMMENT ON TABLE mfa_factors IS 'protected_data cifrado por aplicacion; clave externa a la base';
COMMENT ON TABLE request_metrics IS 'Sin cuerpos, query strings, contraseñas ni tokens';
