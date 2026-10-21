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
