"""Módulo de Ingesta de Telemetría Transaccional y Evaluación de Reglas."""
from datetime import timedelta
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text
from .demo_farm import DEMO_FARM_ID
from .device_candidates import capture_farm, candidate_receipt, detect_radio_candidate, lock_device_identity
from .gateway_detection import observe_bus_gateway
from .models import *
from .settings import settings
from .schemas import TelemetryIn
from .v3_receptions import persist_receptions

def append_audit(db,farm_id,actor,kind,obj,action,before=None,after=None):
    """ 
    Registra una traza de auditoría transaccional para trazabilidad del sistema.
    Args:
        db: Sesión activa de SQLAlchemy.
        farm_id: Identificador de predio.
        actor: Identificador de usuario.
        kind: tipo de entidad afectada.
        obj: Identificador o instancia del objeto auditado.
        action: Acción realizada ('opened', 'resolved', 'applied').
        before: Estado previo de la entidad,
        after: Estado posterior de la entidad.
    """
    db.add(Audit(farm_id=farm_id,actor_id=actor,object_type=kind,object_id=str(obj),action=action,before=before,after=after))

def rule_position(outside_count, valid, inside):
    """
    Evalúa la máquina de estados georreferenciados para la regla de escape de animales.

    Implementa la política de validación de doble posición consecutiva fuera del perímetro

    Args:
        outside_count: Conteo actual de lecturas continuas fuera del geocercado.
        valid: Indicador de validez de la señal GNSS
        inside: Booleano que indica si el punto se encuentra dentro de la geocerca.
    Returns:
        Tuple contenido:
            - Nuevo conteo acumulado de posiciones exteriores.
            - Estado de la posición ('unknown', 'inside', 'pending', 'outside').
            - Evidencia de regla cumplida (True/False o None si no aplica).
    """
    if not valid: 
        return 0,"unknown",None
    if inside: 
        return 0,"inside",False
        
    count = outside_count+1
    return count,"outside" if count>=2 else "pending",True if count>=2 else None


def temperature_alert(value, threshold):
    return None if value is None or threshold is None else value>=threshold

def low_activity_alert(average, threshold):
    return None if average is None or threshold is None else average<threshold

def freshness(observed_at,received_at,interval,now):
    position="unknown" if observed_at is None else ("fresh" if (now-observed_at).total_seconds()<=2*interval+30 else "stale")
    communication="unknown" if received_at is None else ("recent" if (now-received_at).total_seconds()<=3*interval+30 else "absent")
    return position,communication

def resolve_assignment_events(db,assignment,actor_id=None,at=None):
    """Cierra el contexto de monitoreo anterior sin modificar la evidencia de sensor asociada."""
    at=at or utcnow()
    events=db.scalars(select(Event).where(Event.device_id==assignment.device_id,Event.animal_id==assignment.animal_id,Event.condition=="active").with_for_update()).all()
    for event in events:
        event.condition="resolved";event.resolved_at=max(at,event.opened_at)
        event.detail={**event.detail,"resolution_reason":"assignment_closed","resolution":"Asociación cerrada; el evento conserva su evidencia original","closed_assignment_id":str(assignment.id)}
        append_audit(db,assignment.farm_id,actor_id,"event",event.id,"resolved",after={"condition":"resolved","reason":"assignment_closed","assignment_id":str(assignment.id)})


def clear_animal_monitoring(db,animal_id):
    state=db.get(AnimalState,animal_id,with_for_update=True)
    if state:
        state.outside_count=0;state.geofence_status="unknown"
        state.telemetry_id=None;state.position_telemetry_id=None;state.observed_at=None


def reset_pasture_monitoring(db,animal_id,farm_id,geofence_id,actor_id,at):
    state=db.get(AnimalState,animal_id,with_for_update=True)
    if state:
        state.outside_count=0;state.geofence_status="unknown"
    events=db.scalars(select(Event).where(
        Event.farm_id==farm_id,Event.animal_id==animal_id,Event.condition=="active",
        Event.type.in_(("escape","proximity"))).with_for_update()).all()
    for event in events:
        event.condition="resolved";event.resolved_at=max(at,event.opened_at)
        event.detail={**event.detail,"resolution_reason":"pasture_changed",
                      "resolution":"Cambió la geocerca vigilada","new_geofence_id":str(geofence_id)}
        append_audit(db,farm_id,actor_id,"event",event.id,"resolved",after={
            "condition":"resolved","reason":"pasture_changed","geofence_id":str(geofence_id)})


def condition(db,device,animal_id,event_type,active,severity="warning",telemetry=None,geofence=None,detail=None,at=None):
    current=db.scalar(select(Event).where(Event.device_id==device.id,Event.type==event_type,Event.condition=="active").with_for_update())
    if active is None: return current
    if active and current is None:
        current=Event(id=uuid4(),farm_id=device.farm_id,animal_id=animal_id,device_id=device.id,telemetry_id=telemetry.id if telemetry else None,geofence_id=geofence.id if geofence else None,type=event_type,severity=severity,condition="active",attention="pending",opened_at=at or utcnow(),detail=detail or {})
        if event_type=="communication_timeout":
            assignment=db.scalar(select(Assignment).where(Assignment.device_id==device.id,Assignment.animal_id==animal_id,at_time(Assignment,current.opened_at)))
            if assignment:
                current.last_position_id=db.scalar(select(Telemetry.id).where(
                    Telemetry.farm_id==device.farm_id,Telemetry.device_id==device.id,
                    Telemetry.animal_id==animal_id,Telemetry.assignment_id==assignment.id,
                    Telemetry.gnss_valid.is_(True),Telemetry.latitude.is_not(None),Telemetry.longitude.is_not(None),
                    Telemetry.observed_at>=assignment.valid_from,Telemetry.observed_at<=current.opened_at,
                    Telemetry.received_at<=current.opened_at).order_by(Telemetry.observed_at.desc(),Telemetry.received_at.desc(),Telemetry.id.desc()).limit(1))
        db.add(current); db.flush()
        status = "disabled" if device.farm_id == DEMO_FARM_ID else "pending"
        db.add(Notification(event_id=current.id,status=status,channel="webhook"))
        append_audit(db,device.farm_id,None,"event",current.id,"opened",after={"type":event_type,"condition":"active"})
    elif not active and current:
        current.condition="resolved"; current.resolved_at=at or utcnow()
        append_audit(db,device.farm_id,None,"event",current.id,"resolved",after={"condition":"resolved","evidence_telemetry_id":str(telemetry.id) if telemetry else None})
    return current

def at_time(model,when): return and_(model.valid_from<=when,or_(model.valid_to.is_(None),model.valid_to>when))

def ingest(db,payload:TelemetryIn,received_at=None,*,detect_candidates=False,capture_farm_id=None):
    """ 
    Procesa la ingesta transaccional de un paquete de telemetría de dispositivos IoT.
    Args:
        db: Sesión activa de SQLAlchemy.
        payload: Esquema de validación con los datos de telemetría entrantes.
        received_at: Timestamp opcional de recepción en servidor.
        detect_candidates: Registra detecciones académicas desconocidas en la captura HTTP.
        capture_farm_id: Predio opcional indicado por el capturador autenticado.

    Returns:
        Recibo de telemetría o detección con el ID persistido y el indicador de duplicado.
        
    Raises:
        HTTPException(422): Si la marca de tiempo es futura o el dispositivo es desconocido o incompatible.
        HTTPException(403): Si hay violaciones de entorno de simulación o aislamiento de predio.
    """
    now = received_at or utcnow()
    
    if payload.observed_at > now + timedelta(minutes = 5):
        raise HTTPException(422,"Hora de captura futura fuera de tolerancia")
    
    device_query = select(Device).where(Device.hardware_id == payload.hardware_id).with_for_update()
    device = db.scalar(device_query)
    discover = detect_candidates and payload.source == 'academic'
    if device is None and discover:
        farm_id = capture_farm(db, capture_farm_id)
        lock_device_identity(db, payload.hardware_id)
        device = db.scalar(device_query)
        if device is None:
            receipt = detect_radio_candidate(db, farm_id, payload, now)
            observe_bus_gateway(db, farm_id, payload, now)
            return receipt

    if device is None:
        raise HTTPException(422,"Dispositivo desconocido o deshabilitado")
    
    farm = db.get(Farm,device.farm_id)
    
    if settings().app_env == "simulation" and payload.source != "sim" :
        raise HTTPException(403,"Simulación no admite mediciones de hardware real")
    if payload.source == "sim":
        if settings().app_env != "simulation" or not settings().simulation_enabled or farm.environment != "simulation":
            raise HTTPException(403,"Simulación aislada requerida")
    if farm.environment!=settings().app_env: raise HTTPException(403,"Predio de otro entorno")
    if capture_farm_id is not None and farm.id != capture_farm_id:
        raise HTTPException(403,"Dispositivo de otro predio de captura")
    if discover:
        receipt = candidate_receipt(db, farm.id, payload)
        if receipt:
            observe_bus_gateway(db, farm.id, payload, now)
            return receipt
    if not device.enabled:
        raise HTTPException(422,"Dispositivo desconocido o deshabilitado")
    if payload.source != 'sim' and payload.source != device.transport:
        raise HTTPException(422,"Fuente incompatible con transporte registrado")
    
    existing=db.scalar(select(Telemetry).where(Telemetry.device_id==device.id,Telemetry.session_id==payload.session_id,Telemetry.seq==payload.seq))
    if existing:
        if discover:
            observe_bus_gateway(db, farm.id, payload, now, existing)
        persist_receptions(db,existing,payload.receptions,now)
        return {"id":str(existing.id),"duplicate":True,"animal_id":str(existing.animal_id) if existing.animal_id else None}
    
    assignment = db.scalar(select(Assignment).where(Assignment.device_id == device.id, at_time(Assignment, payload.observed_at)))
    values = payload.model_dump(exclude = {"hardware_id", "schema_version", "receptions"})
    row = Telemetry(id = uuid4(), farm_id = device.farm_id, device_id = device.id, animal_id = assignment.animal_id if assignment else None, assignment_id = assignment.id if assignment else None, received_at = now, **values)
    
    if row.gnss_valid:
        row.point = func.ST_SetSRID(func.ST_MakePoint(row.longitude, row.latitude), 4326)
    
    db.add(row); 
    db.flush()
    
    if discover:
        observe_bus_gateway(db, farm.id, payload, now, row)
    persist_receptions(db,row,payload.receptions,now)
    newer=device.last_observed_at is None or row.observed_at>device.last_observed_at
    recent=(now-row.observed_at).total_seconds()<=2*device.interval_seconds+30
    # Un paquete tardío o duplicado no puede rejuvenecer la comunicación efectiva.
    if newer:
        device.last_observed_at=row.observed_at
        device.last_telemetry_id=row.id
        if recent: device.last_received_at=now
    if not assignment:
        append_audit(db,device.farm_id,None,"telemetry",row.id,"unassigned",after={"hardware_id":device.hardware_id,"observed_at":row.observed_at.isoformat()})
    if not newer or not recent: return {"id":str(row.id),"duplicate":False,"animal_id":str(row.animal_id) if row.animal_id else None,"state_updated":False}
    current_assignment=db.scalar(select(Assignment).where(Assignment.device_id==device.id,at_time(Assignment,now)))
    if current_assignment and assignment and current_assignment.id==assignment.id:
        condition(db,device,row.animal_id,"communication_timeout",False,telemetry=row,at=now)
    # La configuración aplicada la prueba el dispositivo, nunca el guardado de un formulario.
    if row.config_version is not None and row.config_version>device.config_version:
        config=db.scalar(select(DeviceConfig).where(DeviceConfig.device_id==device.id,DeviceConfig.version==row.config_version).with_for_update())
        if config and row.observed_at>=config.requested_at:
            device.interval_seconds=config.interval_seconds; device.config_version=config.version
            config.status="applied"; config.applied_at=now; config.error=None
            condition(db,device,row.animal_id,"config_timeout",False,telemetry=row)
            append_audit(db,device.farm_id,None,"device_config",config.id,"applied",after={"version":config.version})
    if not assignment or not current_assignment or assignment.id!=current_assignment.id: return {"id":str(row.id),"duplicate":False,"animal_id":str(row.animal_id) if row.animal_id else None,"state_updated":False}
    # Serializa la evaluación espacial con cambios en el potrero de este animal.
    animal=db.get(Animal,assignment.animal_id,with_for_update={"key_share":True})
    if not animal.enabled: return {"id":str(row.id),"duplicate":False,"animal_id":str(row.animal_id),"state_updated":False}
    state=db.get(AnimalState,animal.id,with_for_update=True)
    if state is None:
        state=AnimalState(animal_id=animal.id,outside_count=0,geofence_status="unknown");db.add(state);db.flush()
    if state.observed_at and row.observed_at<=state.observed_at: return {"id":str(row.id),"duplicate":False,"animal_id":str(row.animal_id),"state_updated":False}
    if state.observed_at and (row.observed_at-state.observed_at).total_seconds()>2*device.interval_seconds+30:
        state.outside_count=0
    state.telemetry_id=row.id; state.observed_at=row.observed_at
    evaluated_at=max(now,utcnow())
    zone=db.scalar(select(PastureAssignment).where(PastureAssignment.animal_id==animal.id,at_time(PastureAssignment,evaluated_at)))
    in_current_period=zone and zone.valid_from<=row.observed_at and (zone.valid_to is None or row.observed_at<zone.valid_to)
    fence=db.get(Geofence,zone.geofence_id) if in_current_period else None
    inside=None
    if row.gnss_valid:
        state.position_telemetry_id=row.id
        if fence:
            inside=db.scalar(select(func.ST_Covers(Geofence.geometry,Telemetry.point)).select_from(Geofence).join(Telemetry,Telemetry.id==row.id).where(Geofence.id==fence.id))
    if fence:
        count,status,evidence=rule_position(state.outside_count,row.gnss_valid,inside)
        state.outside_count=count;state.geofence_status=status
        condition(db,device,animal.id,"escape",evidence,severity="critical",telemetry=row,geofence=fence,detail={"rule":"two_consecutive_valid_outside","geofence_version":fence.version},at=now)
    elif zone is None: state.outside_count=0;state.geofence_status="unknown"
    # Evita que un cambio concurrente de regla deje una alerta abierta bajo una regla deshabilitada.
    rules=db.get(RuleSettings,device.farm_id,with_for_update={"read":True})
    if rules:
        if row.battery_mv is not None: condition(db,device,animal.id,"low_battery",row.battery_mv<rules.battery_low_mv,telemetry=row,detail={"battery_mv":row.battery_mv,"threshold_mv":rules.battery_low_mv,"rule_version":rules.version},at=now)
        if rules.temperature_enabled and row.surface_temperature_c is not None:
            condition(db,device,animal.id,"high_surface_temperature",temperature_alert(row.surface_temperature_c,rules.temperature_high_c),telemetry=row,detail={"surface_temperature_c":row.surface_temperature_c,"threshold_c":rules.temperature_high_c,"preventive":True,"message":"Revisión presencial; lectura superficial no diagnóstica","rule_version":rules.version})
        if rules.activity_enabled and row.activity_index is not None:
            start=row.observed_at-timedelta(minutes=rules.activity_window_minutes)
            samples=db.scalars(select(Telemetry).where(Telemetry.assignment_id==assignment.id,Telemetry.observed_at>=start,Telemetry.observed_at<=row.observed_at).order_by(Telemetry.observed_at)).all()
            complete=len(samples)>=2 and all(s.activity_index is not None for s in samples) and (row.observed_at-samples[0].observed_at).total_seconds()>=max(0,rules.activity_window_minutes*60-device.interval_seconds)
            no_gaps=all((b.observed_at-a.observed_at).total_seconds()<=2*device.interval_seconds+30 for a,b in zip(samples,samples[1:]))
            if complete and no_gaps:
                average=sum(s.activity_index for s in samples)/len(samples)
                condition(db,device,animal.id,"low_activity",low_activity_alert(average,rules.activity_low_threshold),telemetry=row,detail={"average":average,"threshold_activity":rules.activity_low_threshold,"window_minutes":rules.activity_window_minutes,"preventive":True,"rule_version":rules.version})
        if rules.proximity_enabled and fence and row.gnss_valid and inside is not None:
            distance=db.scalar(text("SELECT ST_Distance(t.point::geography,ST_Boundary(g.geometry)::geography) FROM telemetry t,geofences g WHERE t.id=:t AND g.id=:g"),{"t":row.id,"g":fence.id})
            condition(db,device,animal.id,"proximity",bool(inside and distance<=rules.proximity_meters),telemetry=row,geofence=fence,detail={"distance_meters":distance,"threshold_meters":rules.proximity_meters,"rule_version":rules.version})
    db.flush()
    return {"id":str(row.id),"duplicate":False,"animal_id":str(row.animal_id),"state_updated":True}

def check_timeouts(db,now=None):
    now=now or utcnow()
    # Orden de bloqueo igual al de ingesta; SKIP LOCKED permite varios workers simultáneos.
    devices=db.scalars(select(Device).where(Device.enabled.is_(True),Device.farm_id!=DEMO_FARM_ID).order_by(Device.id).with_for_update(skip_locked=True)).all()
    for d in devices:
        assignment=db.scalar(select(Assignment).where(Assignment.device_id==d.id,at_time(Assignment,now)))
        animal=db.get(Animal,assignment.animal_id) if assignment else None
        if animal and animal.enabled:
            baseline=max(d.last_received_at or assignment.valid_from,assignment.valid_from)
            timeout=(now-baseline).total_seconds()>3*d.interval_seconds+30
            condition(db,d,animal.id,"communication_timeout",timeout,detail={"last_received_at":d.last_received_at.isoformat() if d.last_received_at else None,"threshold_seconds":3*d.interval_seconds+30},at=now)
        configs=db.scalars(select(DeviceConfig).where(DeviceConfig.device_id==d.id,DeviceConfig.status.in_(["requested","sent"]))).all()
        for config in configs:
            if (now-config.requested_at).total_seconds()>settings().config_timeout_seconds:
                config.status="failed";config.error="Sin confirmación del módulo dentro del plazo"
                condition(db,d,animal.id if animal and animal.enabled else None,"config_timeout",True,detail={"config_version":config.version,"timeout_seconds":settings().config_timeout_seconds},at=now)
    db.flush()
