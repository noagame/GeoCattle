from pathlib import Path
import uuid
P=Path(__file__).resolve().parent
def u(s): return "'"+str(uuid.uuid5(uuid.NAMESPACE_DNS,'geocattle-v3-test-'+s))+"'"
s=['-- Pruebas sintéticas de integridad V3; todos los datos se revierten.','BEGIN;','SET search_path=geocattle_v3,public;', '''CREATE FUNCTION pg_temp.assert_true(value boolean,label text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN IF value IS DISTINCT FROM true THEN RAISE EXCEPTION 'FALLO: %',label; END IF; RAISE NOTICE 'OK: %',label; END $$;
CREATE FUNCTION pg_temp.expect_error(query text,label text,expected text DEFAULT NULL) RETURNS void LANGUAGE plpgsql AS $$ DECLARE caught boolean:=false; actual text; BEGIN BEGIN EXECUTE query; EXCEPTION WHEN OTHERS THEN caught:=true; GET STACKED DIAGNOSTICS actual=RETURNED_SQLSTATE; IF expected IS NOT NULL AND actual<>expected THEN RAISE EXCEPTION 'SQLSTATE inesperado para %: %',label,actual; END IF; END; IF NOT caught THEN RAISE EXCEPTION 'FALLO (debio rechazar): %',label; END IF; RAISE NOTICE 'OK: %',label; END $$;''']
def add(q): s.append(q+';')
def check(expr,label): add(f"SELECT pg_temp.assert_true({expr},'{label}')")
def err(q,label,code=None): add(f"SELECT pg_temp.expect_error($q${q}$q$,'{label}'"+(f",'{code}'" if code else '')+")")
for user in ['owner','owner2','worker','vet','admin']:
 add(f"INSERT INTO users(id,email,password_hash,full_name,status) VALUES({u(user)},'{user}@example.invalid','hash-sintetico','{user}','active')")
add(f"INSERT INTO platform_admins(user_id) VALUES({u('admin')})")
for i,own in [('1','owner'),('2','owner2')]:
 add(f"INSERT INTO owner_accounts(id,owner_user_id,display_name,max_farms) VALUES({u('acc'+i)},{u(own)},'Cuenta {i}',1)")
 add(f"INSERT INTO farms(id,account_id,name) VALUES({u('farm'+i)},{u('acc'+i)},'Predio {i}')")
 add(f"INSERT INTO sectors(id,farm_id,name,land_use) VALUES({u('sector'+i)},{u('farm'+i)},'Sector','grazing')")
for who,role in [('worker','worker'),('vet','veterinarian')]:
 add(f"INSERT INTO farm_memberships(id,farm_id,user_id,role_code,granted_by,valid_from) VALUES({u('m'+who)},{u('farm1')},{u(who)},'{role}',{u('owner')},now()-interval '2 hours')")
for i in ['1','2']:
 add(f"INSERT INTO animals(id,diio,sex,production_type) VALUES({u('animal'+i)},'0000{i}','female','milk')")
 add(f"INSERT INTO animal_holdings(id,farm_id,animal_id,valid_from,reason) VALUES({u('holding'+i)},{u('farm1')},{u('animal'+i)},now()-interval '2 hours','ingreso')")
 add(f"INSERT INTO devices(id,farm_id,serial_number,transport,status) VALUES({u('device'+i)},{u('farm'+i)},'SERIE-{i}','academic','available')")
polygon="ST_GeomFromText('POLYGON((0 0,1 0,1 1,0 1,0 0))',4326)"
add(f"INSERT INTO geofences(id,farm_id,sector_id,version,geometry,created_by,valid_from) VALUES({u('geo')},{u('farm1')},{u('sector1')},1,{polygon},{u('owner')},now()-interval '2 hours')")
add(f"INSERT INTO assignments(id,farm_id,animal_holding_id,animal_id,device_id,assigned_by,valid_from,valid_to) VALUES({u('assign1')},{u('farm1')},{u('holding1')},{u('animal1')},{u('device1')},{u('owner')},now()-interval '1 hour',now()-interval '30 minutes')")
add(f"INSERT INTO assignments(id,farm_id,animal_holding_id,animal_id,device_id,assigned_by,valid_from) VALUES({u('assign2')},{u('farm1')},{u('holding2')},{u('animal2')},{u('device1')},{u('owner')},now()-interval '30 minutes')")
check('(SELECT count(*) FROM assignments)=2','01 reasignacion sin solapamiento conserva historia')
err(f"INSERT INTO assignments(farm_id,animal_holding_id,animal_id,device_id,assigned_by,valid_from) VALUES({u('farm1')},{u('holding1')},{u('animal1')},{u('device1')},{u('owner')},now())",'02 collar no se asigna simultaneamente a dos animales','23P01')
err(f"INSERT INTO assignments(farm_id,animal_holding_id,animal_id,device_id,assigned_by,valid_from) VALUES({u('farm1')},{u('holding1')},{u('animal1')},{u('device2')},{u('owner')},now())",'03 collar de otro predio rechazado','23503')
err(f"INSERT INTO animal_holdings(farm_id,animal_id,valid_from,reason) VALUES({u('farm2')},{u('animal1')},now(),'traslado')",'04 permanencias solapadas rechazadas','23P01')
err(f"INSERT INTO farms(account_id,name) VALUES({u('acc1')},'Exceso')",'05 cupo predial aplicado','P0001')
err(f"INSERT INTO animals(diio,sex,production_type) VALUES('00001','female','milk')",'06 DIIO duplicado rechazado','23505')
err(f"INSERT INTO geofences(farm_id,sector_id,version,geometry,created_by,valid_from) VALUES({u('farm2')},{u('sector2')},1,ST_GeomFromText('POLYGON((0 0,1 0,0 1,0 0))',4326),{u('owner2')},now())",'07 triangulo rechazado: minimo cuatro vertices','P0001')
err(f"UPDATE geofences SET geometry=ST_GeomFromText('POLYGON((0 0,2 0,2 2,0 2,0 0))',4326) WHERE id={u('geo')}",'08 geocerca no se reescribe','P0001')
# Telemetria capturada antes de reasignacion y recibida ahora.
def telemetry(id,animal,seq='1',obs="now()-interval '45 minutes'"):
 return f"INSERT INTO telemetry(id,farm_id,device_id,assignment_id,animal_id,session_id,seq,observed_at,received_at,point,gnss_valid,source) VALUES({u(id)},{u('farm1')},{u('device1')},{u('assign1')},{u(animal)},'sesion-1',{seq},{obs},now(),ST_SetSRID(ST_Point(0.5,0.5),4326),true,'academic')"
add(telemetry('reading1','animal1'))
check(f"(SELECT animal_id={u('animal1')} FROM telemetry WHERE id={u('reading1')})",'09 lectura tardia conserva animal anterior')
err(telemetry('reading-wrong','animal2','2'),'10 lectura de animal incorrecto rechazada','P0001')
err(telemetry('reading-time','animal1','2','now()'),'11 captura fuera de asignacion rechazada','P0001')
err(telemetry('reading-dup','animal1'),'12 uplink duplicado rechazado','23505')
err(f"UPDATE telemetry SET quality='{{}}' WHERE id={u('reading1')}",'13 telemetria inmutable','P0001')
# Varias antenas conservan una lectura.
for i in ['1','2']:
 add(f"INSERT INTO gateways(id,farm_id,gateway_eui,name,status) VALUES({u('gw'+i)},{u('farm1')},'000000000000000{i}','Gateway {i}','installed')")
 add(f"INSERT INTO telemetry_receptions(telemetry_id,farm_id,gateway_id,rssi_dbm) VALUES({u('reading1')},{u('farm1')},{u('gw'+i)},-80)")
check('(SELECT count(*) FROM telemetry)=1 AND (SELECT count(*) FROM telemetry_receptions)=2','14 multiantena no duplica lectura')

def request(name,who,action,animal='1',device=None):
 membership='NULL' if who in ['owner','owner2','admin'] else u('m'+who)
 if device:
  return f"INSERT INTO change_requests(id,farm_id,requested_by,membership_id,action,device_id,payload,idempotency_key) VALUES({u(name)},{u('farm1')},{u(who)},{membership},'{action}',{u(device)},'{{\"result\":\"reemplazada\"}}',{u('key'+name)})"
 return f"INSERT INTO change_requests(id,farm_id,requested_by,membership_id,action,animal_holding_id,animal_id,payload,idempotency_key) VALUES({u(name)},{u('farm1')},{u(who)},{membership},'{action}',{u('holding'+animal)},{u('animal'+animal)},'{{\"description\":\"registro sintetico\"}}',{u('key'+name)})"
add(request('rw','worker','health_record'))
check(f"EXISTS(SELECT 1 FROM pending_changes WHERE id={u('rw')}) AND NOT EXISTS(SELECT 1 FROM health_events)",'15 solicitud pendiente no altera salud efectiva')
err(f"INSERT INTO change_decisions(request_id,decided_by,decision) VALUES({u('rw')},{u('worker')},'approved')",'16 trabajador no aprueba su propuesta','P0001')
err(f"INSERT INTO change_decisions(request_id,decided_by,decision) VALUES({u('rw')},{u('vet')},'approved')",'17 veterinario no revisa propuestas del trabajador','P0001')
err(f"INSERT INTO change_decisions(request_id,decided_by,decision) VALUES({u('rw')},{u('owner2')},'approved')",'18 dueno ajeno no aprueba','P0001')
err(request('workerprofile','worker','animal_profile'),'19 trabajador no solicita campos de ficha tecnica','P0001')
err(f"INSERT INTO health_events(farm_id,animal_holding_id,request_id,event_type,operation,recorded_by,description) VALUES({u('farm1')},{u('holding1')},{u('rw')},'observation','record',{u('worker')},'sin decision')",'20 sin decision no hay evento efectivo','P0002')
add(f"INSERT INTO change_decisions(request_id,decided_by,decision,reason) VALUES({u('rw')},{u('owner')},'rejected','requiere aclaracion')")
err(f"UPDATE change_decisions SET reason='cambio' WHERE request_id={u('rw')}",'21 decision inmutable','P0001')
err(f"INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES({u('rw')},'health_events',{u('false')})",'22 rechazo no permite aplicacion','P0001')
# Veterinario directo, sin revisar por dueno.
add(request('rv','vet','health_record'))
add(f"INSERT INTO change_decisions(request_id,decided_by,decision) VALUES({u('rv')},{u('vet')},'direct')")
add(f"INSERT INTO health_events(id,farm_id,animal_holding_id,request_id,event_type,operation,recorded_by,description) VALUES({u('he')},{u('farm1')},{u('holding1')},{u('rv')},'observation','record',{u('vet')},'evento directo')")
add(f"INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES({u('rv')},'health_events',{u('he')})")
add('SET CONSTRAINTS ALL IMMEDIATE'); add('SET CONSTRAINTS ALL DEFERRED')
check(f"EXISTS(SELECT 1 FROM effective_health_events WHERE id={u('he')})",'23 veterinario aplica salud directamente')
err(f"DELETE FROM health_events WHERE id={u('he')}",'24 salud historica no se borra','P0001')
# Confianza controlada: rechaza sin concesion y admite con concesion vigente.
add(request('rb','worker','battery_replacement',device='device1'))
err(f"INSERT INTO change_decisions(request_id,decided_by,decision) VALUES({u('rb')},{u('worker')},'direct')",'25 trabajador sin confianza no aplica directo','P0002')
add(f"INSERT INTO trust_grants(id,farm_id,membership_id,action,granted_by,valid_from) VALUES({u('trust')},{u('farm1')},{u('mworker')},'battery_replacement',{u('owner')},now()-interval '1 hour')")
add(f"INSERT INTO change_decisions(request_id,decided_by,decision,trust_grant_id) VALUES({u('rb')},{u('worker')},'direct',{u('trust')})")
add(f"INSERT INTO maintenance(id,farm_id,device_id,request_id,responsible_id,kind,result) VALUES({u('maint')},{u('farm1')},{u('device1')},{u('rb')},{u('worker')},'replacement','reemplazada')")
add(f"INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES({u('rb')},'maintenance',{u('maint')})")
add('SET CONSTRAINTS ALL IMMEDIATE'); add('SET CONSTRAINTS ALL DEFERRED')
check(f"EXISTS(SELECT 1 FROM maintenance WHERE id={u('maint')})",'26 confianza permite bateria con evidencia')
err(f"INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES({u('rb')},'maintenance',{u('maint')})",'27 solicitud no se aplica dos veces','23505')
add(request('rnoapp','owner','animal_status'))
err(f"DO $b$ BEGIN INSERT INTO change_decisions(request_id,decided_by,decision) VALUES({u('rnoapp')},{u('owner')},'direct'); SET CONSTRAINTS ALL IMMEDIATE; END $b$",'28 decision aceptada sin aplicacion impide commit','P0001')
# Correccion: nuevo evento, original conservado.
add(request('rc','vet','health_record'))
add(f"INSERT INTO change_decisions(request_id,decided_by,decision) VALUES({u('rc')},{u('vet')},'direct')")
add(f"INSERT INTO health_events(id,farm_id,animal_holding_id,request_id,event_type,operation,target_event_id,recorded_by,description) VALUES({u('he2')},{u('farm1')},{u('holding1')},{u('rc')},'observation','correct',{u('he')},{u('vet')},'correccion')")
add(f"INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES({u('rc')},'health_events',{u('he2')})")
check('(SELECT count(*) FROM health_events)=2 AND (SELECT count(*) FROM effective_health_events)=1','29 correccion conserva original y cambia vista efectiva')
err(f"INSERT INTO health_events(farm_id,animal_holding_id,request_id,event_type,operation,target_event_id,recorded_by,description) VALUES({u('farm1')},{u('holding1')},{u('rc')},'observation','correct',{u('he')},{u('vet')},'otra correccion')",'30 evento no admite dos sucesores','23505')
add(f"INSERT INTO audit_log(actor_id,actor_kind,action,entity_type) VALUES({u('admin')},'user','review','specification')")
err("DELETE FROM audit_log",'31 auditoria inmutable','P0001')
check(f"(SELECT installed_collars=1 AND animals=2 FROM kpi_inventory_by_owner WHERE account_id={u('acc1')})",'32 KPIs de inventario coherentes')
add('SET CONSTRAINTS ALL IMMEDIATE')
add("SELECT '32 comprobaciones SQL superadas; datos sinteticos revertidos' AS resultado")
add('ROLLBACK')
(P/'VALIDACION_SQL.sql').write_text('\n'.join(s)+'\n')
print('Generada validacion SQL de 32 comprobaciones.')
