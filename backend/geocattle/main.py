import csv
import io
import json
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from .db import get_db
from .models import *
from .schemas import *
from .security import current_user, owner, operator, service_auth, create_session, token_hash, verify_password, hash_password
from .domain import ingest, append_audit, freshness, at_time, check_timeouts
from .settings import settings

app=FastAPI(title="GeoCattle API",version="0.1.0",docs_url="/api/docs",openapi_url="/api/openapi.json",redoc_url=None)
app.add_middleware(CORSMiddleware,allow_origins=[s.strip() for s in settings().allowed_origins.split(",")],allow_credentials=True,allow_methods=["GET","POST","PATCH","PUT","DELETE"],allow_headers=["Content-Type","X-CSRF-Token","X-Operation-Token"])
api=APIRouter(prefix="/api/v1")
login_attempts=defaultdict(deque)
dummy_hash=hash_password(secrets.token_urlsafe(32))

@app.exception_handler(IntegrityError)
async def integrity_error(request,exc): return JSONResponse(status_code=409,content={"detail":"Conflicto de identidad, versión, geometría o intervalo temporal; no se guardaron cambios"})
@app.exception_handler(OperationalError)
async def unavailable(request,exc): return JSONResponse(status_code=503,content={"detail":"Base de datos temporalmente no disponible"})
from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    errors=[".".join(str(x) for x in e["loc"])+": "+e["msg"] for e in exc.errors()]
    return JSONResponse(status_code=422,content={"detail":"; ".join(errors)})

@app.middleware("http")
async def security_headers(request,call_next):
    request.state.started=time.monotonic()
    request.state.request_id=secrets.token_hex(12)
    response=await call_next(request)
    response.headers['X-Request-ID']=request.state.request_id
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Cache-Control"]="no-store"
    try:
        from .db import SessionLocal
        from .v3_security import execute
        actor=getattr(request.state,'actor',None)
        farm_id=getattr(actor,'farm_id',None)
        with SessionLocal.begin() as metrics_db:
            execute(metrics_db,"INSERT INTO request_metrics(id,account_id,farm_id,actor_id,request_id,method,route_template,status_code,duration_ms,request_bytes,response_bytes) VALUES(:i,(SELECT account_id FROM farms WHERE id=:f),:f,:u,:r,:m,:p,:s,:d,:b,:o)",i=uuid4(),f=farm_id,u=getattr(actor,'id',None),r=request.state.request_id,m=request.method,p=getattr(request.scope.get('route'),'path','unmatched'),s=response.status_code,d=max(0,(time.monotonic()-request.state.started)*1000),b=int(request.headers.get('content-length','0')),o=int(response.headers.get('content-length','0')))
    except Exception:
        import logging
        logging.getLogger('geocattle.metrics').warning('Métrica no persistida; revisar conexión/configuración de observabilidad')
    return response

def accessible(db,model,ident,user,lock=False):
    row=db.scalar(select(model).where(model.id==ident,model.farm_id==user.farm_id).with_for_update() if lock else select(model).where(model.id==ident,model.farm_id==user.farm_id))
    if not row: raise HTTPException(403,"Recurso no autorizado para este predio")
    return row

from .v3_security import user_json
def telemetry_json(t):
    if t is None:return None
    keys=["id","device_id","animal_id","session_id","seq","observed_at","received_at","longitude","latitude","gnss_valid","surface_temperature_c","activity_index","battery_mv","source","quality","config_version"]
    return {k:getattr(t,k) for k in keys}
def event_json(db,e):
    animal=db.get(Animal,e.animal_id) if e.animal_id else None
    return {"id":e.id,"animal_id":e.animal_id,"animal_name":animal.name if animal else None,"diio":animal.diio if animal else None,"device_id":e.device_id,"device_name":db.get(Device,e.device_id).name,"telemetry_id":e.telemetry_id,"geofence_id":e.geofence_id,"telemetry":telemetry_json(db.get(Telemetry,e.telemetry_id)) if e.telemetry_id else None,"evidence":telemetry_json(db.get(Telemetry,e.telemetry_id)) if e.telemetry_id else None,"geofence_name":db.get(Geofence,e.geofence_id).name if e.geofence_id else None,"geofence_version":db.get(Geofence,e.geofence_id).version if e.geofence_id else None,"type":e.type,"severity":e.severity,"condition":e.condition,"attention":e.attention,"opened_at":e.opened_at,"resolved_at":e.resolved_at,"detail":e.detail,"actions":[{"id":a.id,"actor_id":a.actor_id,"action":a.action,"at":a.at,"note":a.note} for a in db.scalars(select(EventAction).where(EventAction.event_id==e.id).order_by(EventAction.at)).all()]}
def device_json(db,d):
    assignment=db.scalar(select(Assignment).where(Assignment.device_id==d.id,at_time(Assignment,utcnow())))
    pending=db.scalar(select(DeviceConfig).where(DeviceConfig.device_id==d.id,DeviceConfig.status.in_(["requested","sent"])).order_by(DeviceConfig.version.desc()))
    return {"id":d.id,"hardware_id":d.hardware_id,"dev_eui":d.dev_eui,"name":d.name,"transport":d.transport,"enabled":d.enabled,"interval_seconds":d.interval_seconds,"config_version":d.config_version,"pending_config":{"version":pending.version,"interval_seconds":pending.interval_seconds,"status":pending.status} if pending else None,"animal_id":assignment.animal_id if assignment else None,"last_received_at":d.last_received_at}
def animal_json(db,a):
    now=utcnow()
    state=db.get(AnimalState,a.id)
    assignment=db.scalar(select(Assignment).where(Assignment.animal_id==a.id,at_time(Assignment,now)))
    device=db.get(Device,assignment.device_id) if assignment else None
    t=db.get(Telemetry,state.telemetry_id) if state and state.telemetry_id else None
    p=db.get(Telemetry,state.position_telemetry_id) if state and state.position_telemetry_id else None
    sector=db.get(Sector,a.sector_id) if a.sector_id else None
    events=db.scalars(select(Event).where(Event.animal_id==a.id,Event.condition=="active")).all()
    position,communication=freshness(p.observed_at if p else None,device.last_received_at if device else None,device.interval_seconds if device else 300,now)
    if device is None or not device.enabled or not a.enabled: communication="unknown"
    status="critical" if any(e.severity=="critical" for e in events) else "warning" if events else "unknown" if position!="fresh" or communication!="recent" or not t or not t.gnss_valid or not state or state.geofence_status=="unknown" else "normal"
    return {"id":a.id,"diio":a.diio,"name":a.name,"orientation":a.orientation,"version":a.version,"vital_status":a.status,"breed":a.breed,"color":a.color,"sex":a.sex,"birth_date":a.birth_date,"enabled":a.enabled,"sector_id":a.sector_id,"sector_name":sector.name if sector else None,"device_id":device.id if device else None,"device_name":device.name if device else None,"status":status,"position_status":position,"communication_status":communication,"geofence_status":state.geofence_status if state else "unknown","last_telemetry":telemetry_json(t),"last_position":telemetry_json(p),"position_age_seconds":max(0,(now-p.observed_at).total_seconds()) if p else None,"active_events":len(events)}
def fence_json(db,g):
    geometry=db.scalar(select(func.ST_AsGeoJSON(Geofence.geometry)).where(Geofence.id==g.id))
    return {"id":g.id,"sector_id":g.sector_id,"name":g.name,"version":g.version,"active":g.active,"geometry":json.loads(geometry),"created_at":g.created_at}
def settings_json(r):return {k:getattr(r,k) for k in ["version","battery_low_mv","temperature_high_c","activity_low_threshold","activity_window_minutes","proximity_meters","temperature_enabled","activity_enabled","proximity_enabled"]}

def valid_effective(t):
    now=utcnow()
    t=t or now
    if t>now+timedelta(seconds=5):raise HTTPException(422,"Vigencia futura no admitida en esta versión")
    return t

def period(start,end):
    for v in (start,end):
        if v is not None and (v.tzinfo is None or v.utcoffset() is None):raise HTTPException(422,"Rango UTC requiere zona horaria")
    if start and end and start>=end:raise HTTPException(422,"Inicio debe preceder al fin")

@api.get("/health")
def health(db=Depends(get_db, scope="function")):
    db.execute(text("SELECT 1"))
    return {"status":"ok","environment":settings().app_env,"database":"postgresql-postgis"}

@api.post("/auth/login")
def login(body:LoginIn,request:Request,response:Response,db=Depends(get_db, scope="function")):
    origin=request.headers.get("origin")
    if origin and origin not in {s.strip() for s in settings().allowed_origins.split(",")}:
        raise HTTPException(403,"Origen no autorizado")
    key=(request.client.host if request.client else "unknown",body.username.lower())
    now=time.monotonic(); attempts=login_attempts[key]
    while attempts and attempts[0]<now-300:attempts.popleft()
    if len(attempts)>=10:raise HTTPException(429,"Demasiados intentos; espere cinco minutos")
    attempts.append(now)
    user=db.scalar(select(User).where(User.username==body.username.lower()))
    valid=verify_password(user.password_hash if user else dummy_hash,body.password)
    if not valid or not user or not user.active:raise HTTPException(401,"Credenciales inválidas")
    if user.farm_id and db.get(Farm,user.farm_id).environment!=settings().app_env:raise HTTPException(403,"Cuenta de otro entorno")
    from .v3_security import one,create_challenge
    from .v3_auth import issue_session
    if user.role=='admin':
        factor=one(db,'SELECT id FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL',u=user.id)
        return create_challenge(db,user,'login' if factor else 'mfa_setup',setup=not bool(factor))
    attempts.clear()
    return issue_session(db,user,response)
@api.get("/auth/me")
def me(request:Request,user=Depends(current_user)):return {"user":user_json(user),"csrf_token":request.state.session.csrf_token}
@api.post("/auth/logout",status_code=204)
def logout(request:Request,response:Response,user=Depends(current_user),db=Depends(get_db, scope="function")):
    request.state.session.revoked_at=utcnow()
    response.delete_cookie("geocattle_session",path="/",httponly=True,secure=settings().cookie_secure,samesite="lax")

@api.get("/dashboard")
def dashboard(user=Depends(current_user),db=Depends(get_db, scope="function")):
    farm=db.get(Farm,user.farm_id) if user.farm_id else None
    if not farm:raise HTTPException(409,"Selecciona o crea un predio para consultar monitoreo")
    animals=[animal_json(db,a) for a in db.scalars(select(Animal).where(Animal.farm_id==user.farm_id,Animal.enabled.is_(True)).order_by(Animal.diio)).all()]
    events=db.scalars(select(Event).where(Event.farm_id==user.farm_id,Event.condition=="active").order_by(Event.opened_at.desc())).all()
    summary={"total":len(animals),**{s:sum(a["status"]==s for a in animals) for s in ("normal","warning","critical","unknown")},"active_events":len(events)}
    return {"farm":{"id":farm.id,"name":farm.name,"environment":farm.environment},"summary":summary,"animals":animals,"events":[event_json(db,e) for e in events],"sectors":[{"id":s.id,"name":s.name} for s in db.scalars(select(Sector).where(Sector.farm_id==farm.id)).all()]}
@api.get("/animals")
def animals(q:str=Query(default="",max_length=100),sector_id:UUID|None=None,limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),user=Depends(current_user),db=Depends(get_db, scope="function")):
    query=select(Animal).where(Animal.farm_id==user.farm_id)
    if q:query=query.where(or_(Animal.diio.ilike(f"%{q}%"),Animal.name.ilike(f"%{q}%")))
    if sector_id:accessible(db,Sector,sector_id,user);query=query.where(Animal.sector_id==sector_id)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {"items":[animal_json(db,a) for a in db.scalars(query.order_by(Animal.diio).limit(limit).offset(offset)).all()],"total":total}
@api.get("/animals/{animal_id}")
def animal(animal_id:UUID,user=Depends(current_user),db=Depends(get_db, scope="function")):return animal_json(db,accessible(db,Animal,animal_id,user))
@api.post("/animals",status_code=201)
def create_animal(body:AnimalIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    if body.sector_id:accessible(db,Sector,body.sector_id,user)
    a=Animal(id=uuid4(),farm_id=user.farm_id,**body.model_dump());db.add(a);db.flush()
    append_audit(db,user.farm_id,user.id,"animal",a.id,"create",after=body.model_dump(mode="json"))
    from .v3_security import execute
    execute(db,"INSERT INTO animal_holdings(id,animal_id,farm_id,valid_from,reason) VALUES(:id,:a,:f,now(),'registration')",id=uuid4(),a=a.id,f=a.farm_id)
    return animal_json(db,a)
@api.patch("/animals/{animal_id}")
def update_animal(animal_id:UUID,body:AnimalPatch,user=Depends(owner),db=Depends(get_db, scope="function")):
    a=accessible(db,Animal,animal_id,user,True)
    changes=body.model_dump(exclude_unset=True)
    if any(changes.get(k)==None for k in ("name","orientation","enabled") if k in changes):raise HTTPException(422,"Nombre orientación y habilitación no pueden ser nulos")
    if body.sector_id:accessible(db,Sector,body.sector_id,user)
    before={k:str(getattr(a,k)) for k in changes}
    for k,v in changes.items():setattr(a,k,v)
    a.version+=1
    db.flush();append_audit(db,user.farm_id,user.id,"animal",a.id,"update",before,body.model_dump(mode="json",exclude_unset=True))
    return animal_json(db,a)
@api.get("/animals/{animal_id}/history")
def history(animal_id:UUID,start:datetime|None=None,end:datetime|None=None,limit:int=Query(500,ge=1,le=1000),offset:int=Query(0,ge=0),user=Depends(current_user),db=Depends(get_db, scope="function")):
    accessible(db,Animal,animal_id,user);period(start,end)
    query=select(Telemetry).where(Telemetry.animal_id==animal_id,Telemetry.farm_id==user.farm_id)
    if start:query=query.where(Telemetry.observed_at>=start)
    if end:query=query.where(Telemetry.observed_at<end)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {"items":[telemetry_json(t) for t in db.scalars(query.order_by(Telemetry.observed_at,Telemetry.id).limit(limit).offset(offset)).all()],"total":total}
@api.get("/devices")
def devices(user=Depends(current_user),db=Depends(get_db, scope="function")):
    items=db.scalars(select(Device).where(Device.farm_id==user.farm_id).order_by(Device.name)).all()
    return {"items":[device_json(db,d) for d in items],"total":len(items)}
@api.post("/devices",status_code=201)
def create_device(body:DeviceIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    data=body.model_dump()
    if data["dev_eui"]:data["dev_eui"]=data["dev_eui"].lower()
    if body.transport=="lorawan" and not body.dev_eui:raise HTTPException(422,"LoRaWAN requiere DevEUI")
    d=Device(id=uuid4(),farm_id=user.farm_id,**data);db.add(d);db.flush()
    append_audit(db,user.farm_id,user.id,"device",d.id,"create",after=data)
    return device_json(db,d)
@api.post("/assignments",status_code=201)
def assign(body:AssignmentIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    animal=accessible(db,Animal,body.animal_id,user,True)
    device=accessible(db,Device,body.device_id,user,True)
    if not animal.enabled or not device.enabled:raise HTTPException(422,"Animal y dispositivo deben estar habilitados")
    at=valid_effective(body.effective_at)
    existing=db.scalars(select(Assignment).where(or_(Assignment.animal_id==animal.id,Assignment.device_id==device.id),or_(Assignment.valid_to.is_(None),Assignment.valid_to>at)).with_for_update()).all()
    if existing and not body.replace:raise HTTPException(409,"Asociación existente; cierre explícito requerido")
    for old in existing:
        if old.valid_from>=at:raise HTTPException(409,"Inicio debe ser posterior a asignaciones previas")
        old.valid_to=at
        append_audit(db,user.farm_id,user.id,"assignment",old.id,"close",after={"valid_to":at.isoformat()})
    db.flush()
    from .v3_api import active_holding
    holding=active_holding(db,animal.id,user.farm_id)
    row=Assignment(id=uuid4(),farm_id=user.farm_id,animal_id=animal.id,animal_holding_id=holding["id"],device_id=device.id,assigned_by=user.id,valid_from=at)
    db.add(row)
    state=db.get(AnimalState,animal.id)
    if state:state.outside_count=0;state.geofence_status="unknown";state.telemetry_id=None;state.position_telemetry_id=None;state.observed_at=None
    db.flush();append_audit(db,user.farm_id,user.id,"assignment",row.id,"create",after={"animal_id":str(animal.id),"device_id":str(device.id),"valid_from":at.isoformat()})
    return {"id":row.id,"animal_id":animal.id,"device_id":device.id,"valid_from":at,"valid_to":None}
@api.get("/sectors")
def sectors(user=Depends(current_user),db=Depends(get_db, scope="function")):
    items=db.scalars(select(Sector).where(Sector.farm_id==user.farm_id).order_by(Sector.name)).all()
    return {"items":[{"id":s.id,"name":s.name,"land_use":s.land_use,"description":s.description,"active":s.active} for s in items],"total":len(items)}
@api.post("/sectors",status_code=201)
def create_sector(body:SectorIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    s=Sector(id=uuid4(),farm_id=user.farm_id,**body.model_dump());db.add(s);db.flush();append_audit(db,user.farm_id,user.id,"sector",s.id,"create",after={"name":s.name});return {"id":s.id,"name":s.name}
@api.get("/geofences")
def fences(user=Depends(current_user),db=Depends(get_db, scope="function")):
    items=db.scalars(select(Geofence).where(Geofence.farm_id==user.farm_id).order_by(Geofence.sector_id,Geofence.version.desc())).all()
    return {"items":[fence_json(db,g) for g in items],"total":len(items)}
@api.post("/geofences",status_code=201)
def create_fence(body:GeofenceIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    accessible(db,Sector,body.sector_id,user,True)
    if not body.confirm_impact:raise HTTPException(422,"Debe confirmar el impacto en asignaciones vigentes")
    old=db.scalar(select(Geofence).where(Geofence.sector_id==body.sector_id,Geofence.active).with_for_update())
    if (old.version if old else 0)!=body.expected_version:raise HTTPException(409,"Versión obsoleta; recargue la geocerca")
    encoded=json.dumps(body.geometry)
    if not db.scalar(select(func.ST_IsValid(func.ST_SetSRID(func.ST_GeomFromGeoJSON(encoded),4326)))):raise HTTPException(422,"Polígono inválido: intersección o anillo inválido")
    now=utcnow()
    if old:old.active=False;old.valid_to=now;db.flush()
    g=Geofence(id=uuid4(),farm_id=user.farm_id,sector_id=body.sector_id,name=body.name,version=body.expected_version+1,geometry=func.ST_SetSRID(func.ST_GeomFromGeoJSON(encoded),4326),active=True,created_at=now)
    db.add(g);db.flush()
    if old:
        for zone in db.scalars(select(PastureAssignment).where(PastureAssignment.geofence_id==old.id,PastureAssignment.valid_to.is_(None)).with_for_update()).all():
            zone.valid_to=now;db.flush()
            db.add(PastureAssignment(farm_id=user.farm_id,animal_id=zone.animal_id,animal_holding_id=zone.animal_holding_id,assigned_by=user.id,geofence_id=g.id,valid_from=now))
            state=db.get(AnimalState,zone.animal_id)
            if state:state.outside_count=0;state.geofence_status="unknown"
    append_audit(db,user.farm_id,user.id,"geofence",g.id,"version_create",after={"version":g.version,"geometry":body.geometry,"previous_id":str(old.id) if old else None})
    return fence_json(db,g)
@api.post("/pasture-assignments",status_code=201)
def assign_pasture(body:PastureIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    a=accessible(db,Animal,body.animal_id,user,True);g=accessible(db,Geofence,body.geofence_id,user)
    if not g.active:raise HTTPException(409,"Seleccione la versión activa de la geocerca")
    at=valid_effective(body.effective_at)
    if at<g.created_at:raise HTTPException(422,"Asignación precede a la versión de geocerca")
    old=db.scalar(select(PastureAssignment).where(PastureAssignment.animal_id==a.id,PastureAssignment.valid_to.is_(None)).with_for_update())
    if old:
        if old.valid_from>=at:raise HTTPException(409,"Inicio debe ser posterior al previo")
        old.valid_to=at;db.flush()
    from .v3_api import active_holding
    holding=active_holding(db,a.id,user.farm_id)
    row=PastureAssignment(id=uuid4(),farm_id=user.farm_id,animal_id=a.id,animal_holding_id=holding["id"],geofence_id=g.id,assigned_by=user.id,valid_from=at);db.add(row)
    a.sector_id=g.sector_id
    state=db.get(AnimalState,a.id)
    if state:state.outside_count=0;state.geofence_status="unknown"
    db.flush();append_audit(db,user.farm_id,user.id,"pasture_assignment",row.id,"create",after={"animal_id":str(a.id),"geofence_id":str(g.id),"valid_from":at.isoformat()})
    return {"id":row.id,"animal_id":a.id,"geofence_id":g.id,"valid_from":at,"valid_to":None}
@api.get("/events")
def events(condition:Literal["active","resolved"]|None=None,attention:Literal["pending","acknowledged","in_review","concluded"]|None=None,limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),user=Depends(current_user),db=Depends(get_db, scope="function")):
    query=select(Event).where(Event.farm_id==user.farm_id)
    if condition:query=query.where(Event.condition==condition)
    if attention:query=query.where(Event.attention==attention)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {"items":[event_json(db,e) for e in db.scalars(query.order_by(Event.opened_at.desc()).limit(limit).offset(offset)).all()],"total":total}
@api.post("/events/{event_id}/actions")
def action(event_id:UUID,body:ActionIn,user=Depends(operator),db=Depends(get_db, scope="function")):
    e=accessible(db,Event,event_id,user,True);before={"attention":e.attention,"condition":e.condition}
    e.attention={"acknowledge":"acknowledged","review":"in_review","conclude":"concluded","reopen":"pending"}[body.action]
    db.add(EventAction(event_id=e.id,actor_id=user.id,action=body.action,note=body.note))
    append_audit(db,user.farm_id,user.id,"event",e.id,body.action,before,{"attention":e.attention,"condition":e.condition,"note":body.note});db.flush()
    return event_json(db,e)
@api.post("/devices/{device_id}/config",status_code=201)
def config(device_id:UUID,body:ConfigIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    d=accessible(db,Device,device_id,user,True)
    if not d.enabled:raise HTTPException(422,"Dispositivo deshabilitado")
    last=db.scalar(select(func.max(DeviceConfig.version)).where(DeviceConfig.device_id==d.id)) or d.config_version
    if body.expected_version!=d.config_version:raise HTTPException(409,"Versión aplicada de configuración obsoleta")
    if db.scalar(select(DeviceConfig).where(DeviceConfig.device_id==d.id,DeviceConfig.status.in_(["requested","sent"]))):raise HTTPException(409,"Ya existe una configuración pendiente")
    c=DeviceConfig(id=uuid4(),device_id=d.id,version=last+1,interval_seconds=body.interval_seconds,status="requested");db.add(c);db.flush()
    append_audit(db,user.farm_id,user.id,"device_config",c.id,"requested",after={"version":c.version,"interval_seconds":c.interval_seconds})
    return {"id":c.id,"version":c.version,"interval_seconds":c.interval_seconds,"status":c.status,"requested_at":c.requested_at}
@api.get("/settings")
def get_settings(user=Depends(current_user),db=Depends(get_db, scope="function")):
    r=db.get(RuleSettings,user.farm_id)
    if not r:raise HTTPException(503,"Reglas no inicializadas")
    return settings_json(r)
@api.put("/settings")
def update_settings(body:SettingsIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    r=db.get(RuleSettings,user.farm_id,with_for_update=True)
    if r.version!=body.expected_version:raise HTTPException(409,"Versión de reglas obsoleta")
    if settings().app_env!="simulation" and not settings().preventive_rules_validated and (body.temperature_enabled or body.activity_enabled):raise HTTPException(422,"Sensores preventivos requieren validación de campo PREVENTIVE_RULES_VALIDATED")
    before=settings_json(r)
    for k,v in body.model_dump(exclude={"expected_version"}).items():setattr(r,k,v)
    r.version+=1;db.flush();append_audit(db,user.farm_id,user.id,"rule_settings",user.farm_id,"update",before,settings_json(r))
    return settings_json(r)
@api.get("/audit")
def audit(limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),user=Depends(owner),db=Depends(get_db, scope="function")):
    query=select(Audit).where(Audit.farm_id==user.farm_id)
    return {"items":[{k:getattr(a,k) for k in ["id","actor_id","object_type","object_id","action","at","before","after"]} for a in db.scalars(query.order_by(Audit.at.desc()).limit(limit).offset(offset)).all()],"total":db.scalar(select(func.count()).select_from(query.subquery()))}
@api.get("/notifications")
def notifications(user=Depends(current_user),db=Depends(get_db, scope="function")):
    rows=db.scalars(select(Notification).join(Event).where(Event.farm_id==user.farm_id).order_by(Notification.created_at.desc()).limit(500)).all()
    return {"items":[{"id":n.id,"event_id":n.event_id,"channel":n.channel,"status":n.status,"created_at":n.created_at,"attempts":[{k:getattr(a,k) for k in ["attempt","at","status","provider_id","error"]} for a in db.scalars(select(NotificationAttempt).where(NotificationAttempt.notification_id==n.id).order_by(NotificationAttempt.attempt)).all()]} for n in rows],"total":db.scalar(select(func.count()).select_from(Notification).join(Event).where(Event.farm_id==user.farm_id))}
@api.post("/telemetry",dependencies=[Depends(service_auth)],status_code=201)
@api.post("/ingest/telemetry",dependencies=[Depends(service_auth)],status_code=201)
def telemetry(body:TelemetryIn,db=Depends(get_db, scope="function")):return ingest(db,body)

@api.get("/reports/telemetry.csv")
def export_history(start:datetime|None=None,end:datetime|None=None,animal_id:UUID|None=None,user=Depends(current_user),db=Depends(get_db, scope="function")):
    period(start,end)
    if animal_id:accessible(db,Animal,animal_id,user)
    query=select(Telemetry).where(Telemetry.farm_id==user.farm_id)
    if start:query=query.where(Telemetry.observed_at>=start)
    if end:query=query.where(Telemetry.observed_at<end)
    if animal_id:query=query.where(Telemetry.animal_id==animal_id)
    rows=db.scalars(query.order_by(Telemetry.observed_at).limit(50000)).all()
    out=io.StringIO();writer=csv.writer(out)
    keys=["animal_id","device_id","observed_at","received_at","longitude","latitude","gnss_valid","surface_temperature_c","activity_index","battery_mv","source"]
    writer.writerow(keys)
    for row in rows:writer.writerow([getattr(row,k) for k in keys])
    return Response(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=geocattle-telemetria.csv","X-Export-Limit":"50000"})
@api.get("/reports")
def report(start:datetime|None=None,end:datetime|None=None,user=Depends(current_user),db=Depends(get_db, scope="function")):
    period(start,end)
    query=select(Telemetry).where(Telemetry.farm_id==user.farm_id)
    if start:query=query.where(Telemetry.observed_at>=start)
    if end:query=query.where(Telemetry.observed_at<end)
    data=query.subquery()
    return {"start":start,"end":end,"telemetry_count":db.scalar(select(func.count()).select_from(data)),"valid_positions":db.scalar(select(func.count()).select_from(data).where(data.c.gnss_valid)),"simulated_samples":db.scalar(select(func.count()).select_from(data).where(data.c.source=="sim")),"surface_temperature_label":"Temperatura superficial, no diagnóstica","retention":"No hay borrado automático; ventana disponible depende de las capturas existentes"}

@api.post("/simulation/scenarios")
def simulation(body:ScenarioIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    if settings().app_env!="simulation" or not settings().simulation_enabled:raise HTTPException(403,"Sólo ambiente de simulación aislado")
    from .simulation import run_scenario
    return run_scenario(db,user,body)
@api.get("/maintenance")
def maintenance(device_id:UUID|None=None,limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),user=Depends(current_user),db=Depends(get_db, scope="function")):
    query=select(Maintenance).where(Maintenance.farm_id==user.farm_id)
    if device_id:accessible(db,Device,device_id,user);query=query.where(Maintenance.device_id==device_id)
    rows=db.scalars(query.order_by(Maintenance.at.desc()).limit(limit).offset(offset)).all()
    return {"items":[{"id":m.id,"device_id":m.device_id,"device_name":db.get(Device,m.device_id).name,"battery_id":m.battery_id,"kind":m.kind,"at":m.at,"responsible_id":m.responsible_id,"responsible_name":db.get(User,m.responsible_id).username,"result":m.result} for m in rows],"total":db.scalar(select(func.count()).select_from(query.subquery()))}
@api.post("/maintenance",status_code=201)
def create_maintenance(body:MaintenanceIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    d=accessible(db,Device,body.device_id,user)
    at=valid_effective(body.at)
    m=Maintenance(id=uuid4(),farm_id=user.farm_id,device_id=d.id,battery_id=body.battery_id,kind=body.kind,at=at,responsible_id=user.id,result=body.result)
    db.add(m);db.flush();append_audit(db,user.farm_id,user.id,"maintenance",m.id,"create",after=body.model_dump(mode="json"))
    return {"id":m.id,"device_id":d.id,"device_name":d.name,"battery_id":m.battery_id,"kind":m.kind,"at":m.at,"responsible_id":user.id,"responsible_name":user.username,"result":m.result}
@api.patch("/devices/{device_id}")
def update_device(device_id:UUID,body:DevicePatch,user=Depends(owner),db=Depends(get_db, scope="function")):
    d=accessible(db,Device,device_id,user,True)
    before={"enabled":d.enabled};d.enabled=body.enabled
    if not d.enabled:
        for e in db.scalars(select(Event).where(Event.device_id==d.id,Event.type=="communication_timeout",Event.condition=="active").with_for_update()).all():
            e.condition="resolved";e.resolved_at=utcnow();e.detail={**e.detail,"resolution":"Retiro explícito: comunicación deja de ser esperada"}
    db.flush();append_audit(db,user.farm_id,user.id,"device",d.id,"set_enabled",before,{"enabled":d.enabled})
    return device_json(db,d)
@api.patch("/sectors/{ident}")
def patch_sector(ident:UUID,body:SectorPatch,user=Depends(owner),db=Depends(get_db,scope="function")):
    sector=accessible(db,Sector,ident,user,True)
    changes=body.model_dump(exclude_unset=True)
    if 'usage' in changes:
        if 'land_use' in changes and changes['usage']!=changes['land_use']:raise HTTPException(422,"Uso inconsistente")
        changes['land_use']=changes.pop('usage')
    if changes.get('active') is False and db.scalar(select(Geofence).where(Geofence.sector_id==ident,Geofence.active)):
        raise HTTPException(409,"Desactiva/reasigna la geocerca antes de retirar el sector")
    for key,value in changes.items():
        if key in ('name','land_use','active') and value is None:raise HTTPException(422,"Campo obligatorio no puede ser nulo")
        setattr(sector,key,value)
    append_audit(db,user.farm_id,user.id,"sector",ident,"update",after=changes)
    return {"id":sector.id,"name":sector.name,"land_use":sector.land_use,"description":sector.description,"active":sector.active}

app.include_router(api)
from .v3_auth import router as auth_v3_router
from .v3_api import router as v3_router
from .v3_operation_auth import router as operation_auth_router
from .v3_account import router as account_auth_router
app.include_router(auth_v3_router)
app.include_router(operation_auth_router)
app.include_router(account_auth_router)
app.include_router(v3_router)
