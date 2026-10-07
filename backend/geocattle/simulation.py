from uuid import uuid4
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import func, select
from .models import *
from .schemas import TelemetryIn
from .domain import ingest, at_time,check_timeouts,append_audit

def run_scenario(db,user,body):
    query=select(Animal).where(Animal.farm_id==user.farm_id,Animal.enabled)
    if body.animal_id:query=query.where(Animal.id==body.animal_id)
    animal=db.scalar(query.order_by(Animal.diio))
    if not animal:raise HTTPException(422,"No hay animal habilitado en el escenario")
    now=utcnow()
    association=db.scalar(select(Assignment).where(Assignment.animal_id==animal.id,at_time(Assignment,now)))
    if not association:raise HTTPException(422,"Animal sin módulo vigente")
    device=db.get(Device,association.device_id,with_for_update=True)
    zone=db.scalar(select(PastureAssignment).where(PastureAssignment.animal_id==animal.id,at_time(PastureAssignment,now)))
    if not zone:raise HTTPException(422,"Animal sin geocerca")
    center=db.execute(select(func.ST_X(func.ST_PointOnSurface(Geofence.geometry)),func.ST_Y(func.ST_PointOnSurface(Geofence.geometry))).where(Geofence.id==zone.geofence_id)).one()
    lon,lat=center
    if body.scenario=="escape":
        lon=db.scalar(select(func.ST_XMax(func.Box3D(Geofence.geometry))).where(Geofence.id==zone.geofence_id))+.0001
    if body.scenario=="timeout":
        previous=device.last_received_at
        device.last_received_at=now-timedelta(seconds=3*device.interval_seconds+31)
        db.flush()
        check_timeouts(db,now)
        append_audit(db,user.farm_id,user.id,"simulation",animal.id,"timeout",before={"last_received_at":previous.isoformat() if previous else None},after={"last_received_at":device.last_received_at.isoformat(),"source":"sim","reason":"Interrupción de transmisión sintética; no altera telemetría"})
        return {"scenario":body.scenario,"animal_id":animal.id,"source":"sim","message":"Comunicación efectiva interrumpida en el escenario sintético; ejecutar normal para recuperar"}
    results=[]
    session="scenario-"+str(uuid4())
    # Capture timestamps never exceed the real current time.
    stamps=[now-timedelta(microseconds=1),now] if body.scenario=="escape" else [now]
    for seq,stamp in enumerate(stamps):
        row=TelemetryIn(hardware_id=device.hardware_id,session_id=session,seq=seq,observed_at=stamp,longitude=None if body.scenario=="no_fix" else lon,latitude=None if body.scenario=="no_fix" else lat,gnss_valid=body.scenario!="no_fix",surface_temperature_c=34.5,activity_index=.6,battery_mv=3150 if body.scenario=="low_battery" else 3750,source="sim",quality={"simulation":True,"scenario":body.scenario,"sensor_algorithm":"synthetic-v1"})
        results.append(ingest(db,row,now))
    append_audit(db,user.farm_id,user.id,"simulation",animal.id,body.scenario,after={"source":"sim","rows":len(results)})
    return {"scenario":body.scenario,"animal_id":animal.id,"source":"sim","results":results}
