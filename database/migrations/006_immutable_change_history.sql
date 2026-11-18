-- The request is immutable. Foreign keys and the unique decision key protect
-- the reference without taking a row lock that requires UPDATE privileges.

CREATE OR REPLACE FUNCTION validate_decision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r change_requests; m farm_memberships; grant_row trust_grants;
BEGIN
 SELECT * INTO STRICT r FROM change_requests WHERE id=NEW.request_id;
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

CREATE OR REPLACE FUNCTION validate_effective_record() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r change_requests; d change_decisions; h animal_holdings; prev_h uuid;
BEGIN
 IF NEW.request_id IS NULL THEN
  IF TG_TABLE_NAME='maintenance' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Se requiere solicitud para aplicar este registro' USING ERRCODE='23514';
 END IF;
 SELECT * INTO STRICT r FROM change_requests WHERE id=NEW.request_id;
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
