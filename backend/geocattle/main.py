import json
import secrets
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError as DatabaseTimeout
from sqlalchemy.orm import aliased
from .db import get_db
from .device_candidates import lock_device_identity
from .device_inventory import create_inventory_device, delete_inventory_device, device_json, devices_json
from .hardware_api import period as farm_day_period
from .mirror_api import blocks_write, router as mirror_router
from .mirror_policy import WRITE_DENIED
from .mirror_replay import replay_for
from .models import *
from .report_exports import CsvDelimiter, EXPORT_LIMIT, ExportFormat, export_response
from .schemas import *
from .security import admin_login_requires_mfa, current_user, owner, operator, service_auth, create_session, token_hash, verify_password, hash_password
from .domain import ingest, append_audit, freshness, at_time, check_timeouts, clear_animal_monitoring, resolve_assignment_events, reset_pasture_monitoring, temperature_alert, low_activity_alert
from .settings import settings

api_docs_enabled = settings().app_env != 'production'
app = FastAPI(
    title='GeoCattle API', version='0.1.0',
    docs_url='/api/docs' if api_docs_enabled else None,
    openapi_url='/api/openapi.json' if api_docs_enabled else None,
    redoc_url=None,
)


@app.middleware('http')
async def replica_write_policy(request, call_next):
    if blocks_write(request):
        return JSONResponse(status_code=403, content={'detail': WRITE_DENIED})
    return await call_next(request)


app.add_middleware(CORSMiddleware,allow_origins=[s.strip() for s in settings().allowed_origins.split(",")],allow_credentials=True,allow_methods=["GET","POST","PATCH","PUT","DELETE"],allow_headers=["Content-Type","X-CSRF-Token","X-Operation-Token"])
allowed_hosts = [host.strip() for host in settings().allowed_hosts.split(",") if host.strip()]
if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts, www_redirect=False)
api=APIRouter(prefix="/api/v1")
login_attempts=defaultdict(deque)
dummy_hash=hash_password(secrets.token_urlsafe(32))

@app.exception_handler(IntegrityError)
async def integrity_error(request,exc): return JSONResponse(status_code=409,content={"detail":"Conflicto de identidad, versión, geometría o intervalo temporal; no se guardaron cambios"})
@app.exception_handler(OperationalError)
@app.exception_handler(DatabaseTimeout)
async def unavailable(request,exc): return JSONResponse(status_code=503,content={"detail":"Base de datos temporalmente no disponible"})
from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    errors=[".".join(str(x) for x in e["loc"])+": "+e["msg"] for e in exc.errors()]
    return JSONResponse(status_code=422,content={"detail":"; ".join(errors)})

def persist_request_metrics(request,response,elapsed_ms):
    from .db import SessionLocal
    from .v3_security import execute
    actor=getattr(request.state,'actor',None)
    with SessionLocal.begin() as metrics_db:
        execute(metrics_db,"INSERT INTO request_metrics(id,account_id,farm_id,actor_id,request_id,method,route_template,status_code,duration_ms,request_bytes,response_bytes) VALUES(:i,(SELECT account_id FROM farms WHERE id=:f),:f,:u,:r,:m,:p,:s,:d,:b,:o)",
                i=uuid4(),f=getattr(actor,'farm_id',None),u=getattr(actor,'id',None),r=request.state.request_id,
                m=request.method,p=getattr(request.scope.get('route'),'path','unmatched'),s=response.status_code,
                d=elapsed_ms,b=int(request.headers.get('content-length','0')),o=int(response.headers.get('content-length','0')))

@app.middleware("http")
async def security_headers(request,call_next):
    request.state.started=time.monotonic()
    request.state.request_id=secrets.token_hex(12)
    response=await call_next(request)
    response.headers['X-Request-ID']=request.state.request_id
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Cache-Control"]="no-store"
    if replay_for(request) is not None:
        return response
    if getattr(app.state, 'native_local_app', False) and request.url.path.startswith(('/mapa-local/satelite/', '/mapa-local/osm/')):
        if response.status_code == 200 and request.url.path.endswith(('.webp', '.png')):
            response.headers["Cache-Control"]="public, max-age=86400"
        return response
    try:
        elapsed_ms=max(0,(time.monotonic()-request.state.started)*1000)
        await run_in_threadpool(persist_request_metrics,request,response,elapsed_ms)
    except Exception:
        import logging
        logging.getLogger('geocattle.metrics').warning('Métrica no persistida; revisar conexión/configuración de observabilidad')
    return response

def accessible(db,model,ident,user,lock=False,*,no_key_update=False):
    query=select(model).where(model.id==ident,model.farm_id==user.farm_id)
    row=db.scalar(query.with_for_update(key_share=no_key_update) if lock else query)
    if not row: raise HTTPException(403,"Recurso no autorizado para este predio")
    return row

from .v3_security import user_json
def telemetry_json(t):
    if t is None:return None
    keys=["id","device_id","animal_id","session_id","seq","observed_at","received_at","longitude","latitude","gnss_valid","surface_temperature_c","activity_index","battery_mv","source","quality","config_version"]
    return {k:getattr(t,k) for k in keys}
def events_json(db,events):
    if not events:
        return []
    ids=[event.id for event in events]
    position=aliased(Telemetry)
    sample=aliased(Telemetry)
    rows=db.execute(select(Event.id,Animal.name,Animal.diio,Device.name,Device.hardware_id,
                           Geofence.name,Geofence.version,sample,position).select_from(Event)
        .join(Device,Device.id==Event.device_id)
        .outerjoin(Animal,Animal.id==Event.animal_id)
        .outerjoin(Geofence,Geofence.id==Event.geofence_id)
        .outerjoin(sample,sample.id==Event.telemetry_id)
        .outerjoin(position,position.id==Event.last_position_id)
        .where(Event.id.in_(ids)))
    evidence={row[0]:row[1:] for row in rows}
    actions=defaultdict(list)
    for action in db.scalars(select(EventAction).where(EventAction.event_id.in_(ids)).order_by(EventAction.at)):
        actions[action.event_id].append({"id":action.id,"actor_id":action.actor_id,"action":action.action,
                                         "at":action.at,"note":action.note})

    result=[]
    for event in events:
        animal_name,diio,device_name,hardware_id,fence_name,fence_version,reading,fix=evidence[event.id]
        # Use the persisted position at detection, even if a newer fix exists.
        location=None
        if (fix and fix.farm_id==event.farm_id and fix.device_id==event.device_id
                and fix.animal_id==event.animal_id and fix.gnss_valid):
            location={"telemetry":telemetry_json(fix),"hardware_id":hardware_id,
                      "age_at_detection_seconds":max(0,(event.opened_at-fix.observed_at).total_seconds())}
        reading_data=telemetry_json(reading)
        result.append({"last_known_position":location,"id":event.id,"animal_id":event.animal_id,
                       "animal_name":animal_name,"diio":diio,"device_id":event.device_id,"device_name":device_name,
                       "telemetry_id":event.telemetry_id,"geofence_id":event.geofence_id,"telemetry":reading_data,
                       "evidence":reading_data,"geofence_name":fence_name,"geofence_version":fence_version,
                       "type":event.type,"severity":event.severity,"condition":event.condition,
                       "attention":event.attention,"opened_at":event.opened_at,"resolved_at":event.resolved_at,
                       "detail":event.detail,"actions":actions[event.id]})
    return result
def animals_json(db,animals):
    if not animals:
        return []
    now=utcnow()
    ids=[animal.id for animal in animals]
    alerts=(select(Event.animal_id,func.count().label("total"),func.bool_or(Event.severity=="critical").label("critical"))
            .where(Event.animal_id.in_(ids),Event.condition=="active").group_by(Event.animal_id).subquery())
    latest=aliased(Telemetry)
    position=aliased(Telemetry)
    rows=db.execute(select(Animal.id,AnimalState,Device,latest,position,Sector.name,alerts.c.total,alerts.c.critical)
        .select_from(Animal)
        .outerjoin(AnimalState,AnimalState.animal_id==Animal.id)
        .outerjoin(Assignment,(Assignment.animal_id==Animal.id)&at_time(Assignment,now))
        .outerjoin(Device,Device.id==Assignment.device_id)
        .outerjoin(latest,latest.id==AnimalState.telemetry_id)
        .outerjoin(position,position.id==AnimalState.position_telemetry_id)
        .outerjoin(Sector,Sector.id==Animal.sector_id)
        .outerjoin(alerts,alerts.c.animal_id==Animal.id)
        .where(Animal.id.in_(ids)))
    snapshots={row[0]:row[1:] for row in rows}

    result=[]
    for animal in animals:
        state,device,reading,fix,sector_name,active_count,critical=snapshots[animal.id]
        position_status,communication=freshness(fix.observed_at if fix else None,
            device.last_received_at if device else None,device.interval_seconds if device else 300,now)
        if device is None or not device.enabled or not animal.enabled:
            communication="unknown"
        geofence_status=state.geofence_status if state else "unknown"
        if critical:
            status="critical"
        elif active_count:
            status="warning"
        elif position_status!="fresh" or communication!="recent" or not reading or not reading.gnss_valid or geofence_status=="unknown":
            status="unknown"
        else:
            status="normal"
        result.append({"id":animal.id,"diio":animal.diio,"name":animal.name,"orientation":animal.orientation,
                       "version":animal.version,"vital_status":animal.status,"breed":animal.breed,"color":animal.color,
                       "sex":animal.sex,"birth_date":animal.birth_date,"enabled":animal.enabled,"sector_id":animal.sector_id,
                       "sector_name":sector_name,"device_id":device.id if device else None,"device_name":device.name if device else None,
                       "status":status,"position_status":position_status,"communication_status":communication,
                       "geofence_status":geofence_status,"last_telemetry":telemetry_json(reading),"last_position":telemetry_json(fix),
                       "position_age_seconds":max(0,(now-fix.observed_at).total_seconds()) if fix else None,
                       "active_events":active_count or 0})
    return result
def fence_sector_ids(db,g):
    return sorted(set(db.scalars(select(GeofenceSector.sector_id).where(GeofenceSector.geofence_id==g.id)).all()) | {g.sector_id},key=str)

def fence_json(db,g):
    geometry=db.scalar(select(func.ST_AsGeoJSON(Geofence.geometry)).where(Geofence.id==g.id))
    return {"id":g.id,"geofence_key":g.geofence_key,"sector_ids":fence_sector_ids(db,g),"sector_id":g.sector_id,"name":g.name,"version":g.version,"active":g.active,"geometry":json.loads(geometry),"created_at":g.created_at}
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
    if user.farm_id:
        home = db.get(Farm, user.farm_id)
        if not home or home.environment != settings().visible_farm_environment:
            raise HTTPException(403, 'Cuenta de otro entorno')
    from .v3_security import one,create_challenge,lock_identity
    from .v3_auth import issue_session
    # Serialize issuing a session or challenge with credential resets.
    password_hash = user.password_hash
    lock_identity(db, user.id)
    db.refresh(user)
    if not user.active or user.password_hash != password_hash:
        raise HTTPException(401, "Credenciales inválidas")
    if user.mfa_enrollment_required or (user.role == 'admin' and admin_login_requires_mfa(request)):
        factor=one(db,"SELECT id FROM mfa_factors WHERE user_id=:u AND kind='totp' AND verified_at IS NOT NULL AND revoked_at IS NULL ORDER BY created_at DESC,id DESC LIMIT 1",u=user.id)
        if settings().mirror_mode == 'replica' and (not factor or user.mfa_enrollment_required):
            raise HTTPException(403, WRITE_DENIED)
        return create_challenge(db,user,'login' if factor else 'mfa_setup',setup=not bool(factor),factor_id=factor['id'] if factor else None)
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
    animals=animals_json(db,db.scalars(select(Animal).where(Animal.farm_id==user.farm_id,Animal.enabled.is_(True)).order_by(Animal.diio)).all())
    events=db.scalars(select(Event).where(Event.farm_id==user.farm_id,Event.condition=="active").order_by(Event.opened_at.desc())).all()
    summary={"total":len(animals),**{s:sum(a["status"]==s for a in animals) for s in ("normal","warning","critical","unknown")},"active_events":len(events)}
    return {"farm":{"id":farm.id,"name":farm.name,"environment":farm.environment},"summary":summary,"animals":animals,"events":events_json(db,events),"sectors":[{"id":s.id,"name":s.name} for s in db.scalars(select(Sector).where(Sector.farm_id==farm.id)).all()]}
@api.get("/animals")
def animals(q:str=Query(default="",max_length=100),sector_id:UUID|None=None,limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),user=Depends(current_user),db=Depends(get_db, scope="function")):
    query=select(Animal).where(Animal.farm_id==user.farm_id)
    if q:query=query.where(or_(Animal.diio.ilike(f"%{q}%"),Animal.name.ilike(f"%{q}%")))
    if sector_id:accessible(db,Sector,sector_id,user);query=query.where(Animal.sector_id==sector_id)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {"items":animals_json(db,db.scalars(query.order_by(Animal.diio).limit(limit).offset(offset)).all()),"total":total}
@api.get("/animals/{animal_id}")
def animal(animal_id:UUID,user=Depends(current_user),db=Depends(get_db, scope="function")):
    a=accessible(db,Animal,animal_id,user)
    result=animals_json(db,[a])[0]
    at=utcnow()
    collar=db.scalar(select(Assignment).where(Assignment.animal_id==a.id,Assignment.farm_id==user.farm_id,at_time(Assignment,at)))
    zone=db.execute(text("""SELECT x.id,x.geofence_id,g.name AS geofence_name,g.version AS geofence_version,
        g.sector_id,s.name AS sector_name,x.valid_from,x.valid_to
        FROM pasture_assignments x JOIN geofences g ON g.id=x.geofence_id JOIN sectors s ON s.id=g.sector_id
        WHERE x.animal_id=:animal AND x.farm_id=:farm AND x.valid_from<=:at AND (x.valid_to IS NULL OR x.valid_to>:at)"""),{"animal":a.id,"farm":user.farm_id,"at":at}).mappings().first()
    result["collar_assignment"]={"id":collar.id,"device_id":collar.device_id,"valid_from":collar.valid_from,"valid_to":collar.valid_to} if collar else None
    result["pasture_assignment"]=dict(zone) if zone else None
    return result

@api.get("/animals/{animal_id}/assignments")
def association_history(animal_id:UUID,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),user=Depends(current_user),db=Depends(get_db,scope="function")):
    accessible(db,Animal,animal_id,user)
    params={"animal":animal_id,"farm":user.farm_id,"at":utcnow(),"limit":limit,"offset":offset}
    total=db.scalar(text("""SELECT (SELECT count(*) FROM assignments WHERE animal_id=:animal AND farm_id=:farm)
        +(SELECT count(*) FROM pasture_assignments WHERE animal_id=:animal AND farm_id=:farm)"""),params)
    items=db.execute(text("""SELECT history.*,(valid_from<=:at AND (valid_to IS NULL OR valid_to>:at)) AS active FROM (
        SELECT x.id,'collar' AS kind,x.valid_from,x.valid_to,x.assigned_by,
            coalesce(nullif(u.full_name,''),u.username) AS assigned_by_name,
            x.device_id,d.name AS device_name,d.hardware_id,
            NULL::uuid AS geofence_id,NULL::text AS geofence_name,NULL::integer AS geofence_version,NULL::uuid AS sector_id,NULL::text AS sector_name
        FROM assignments x JOIN devices d ON d.id=x.device_id LEFT JOIN users u ON u.id=x.assigned_by
        WHERE x.animal_id=:animal AND x.farm_id=:farm
        UNION ALL
        SELECT x.id,'pasture' AS kind,x.valid_from,x.valid_to,x.assigned_by,
            coalesce(nullif(u.full_name,''),u.username) AS assigned_by_name,
            NULL::uuid AS device_id,NULL::text AS device_name,NULL::text AS hardware_id,
            x.geofence_id,g.name AS geofence_name,g.version AS geofence_version,g.sector_id,s.name AS sector_name
        FROM pasture_assignments x JOIN geofences g ON g.id=x.geofence_id JOIN sectors s ON s.id=g.sector_id LEFT JOIN users u ON u.id=x.assigned_by
        WHERE x.animal_id=:animal AND x.farm_id=:farm
        ) history ORDER BY valid_from DESC,id DESC LIMIT :limit OFFSET :offset"""),params).mappings().all()
    return {"items":[dict(row) for row in items],"total":total}
@api.post("/animals",status_code=201)
def create_animal(body:AnimalIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    if body.sector_id:
        sector=accessible(db,Sector,body.sector_id,user)
        if not sector.active:raise HTTPException(409,"Seleccione un sector activo")
    a=Animal(id=uuid4(),farm_id=user.farm_id,**body.model_dump());db.add(a);db.flush()
    append_audit(db,user.farm_id,user.id,"animal",a.id,"create",after=body.model_dump(mode="json"))
    from .v3_security import execute
    execute(db,"INSERT INTO animal_holdings(id,animal_id,farm_id,valid_from,reason) VALUES(:id,:a,:f,now(),'registration')",id=uuid4(),a=a.id,f=a.farm_id)
    return animals_json(db,[a])[0]
@api.patch("/animals/{animal_id}")
def update_animal(animal_id:UUID,body:AnimalPatch,user=Depends(owner),db=Depends(get_db, scope="function")):
    a=accessible(db,Animal,animal_id,user,True)
    changes=body.model_dump(exclude_unset=True)
    if any(changes.get(k)==None for k in ("name","orientation","enabled") if k in changes):raise HTTPException(422,"Nombre orientación y habilitación no pueden ser nulos")
    if body.sector_id:
        sector=accessible(db,Sector,body.sector_id,user)
        if not sector.active and body.sector_id!=a.sector_id:raise HTTPException(409,"Seleccione un sector activo")
    if "sector_id" in changes:
        zone=db.scalar(select(PastureAssignment).where(PastureAssignment.animal_id==a.id,at_time(PastureAssignment,utcnow())))
        if zone and db.get(Geofence,zone.geofence_id).sector_id!=changes["sector_id"]:
            raise HTTPException(409,"El animal tiene una zona de pastoreo vigente. Cambia la zona de pastoreo para actualizar su sector y conservar el historial")
    before={k:str(getattr(a,k)) for k in changes}
    for k,v in changes.items():setattr(a,k,v)
    a.version+=1
    db.flush();append_audit(db,user.farm_id,user.id,"animal",a.id,"update",before,body.model_dump(mode="json",exclude_unset=True))
    return animals_json(db,[a])[0]
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
    items = devices_json(db, user.farm_id)
    return {"items": items, "total": len(items)}
@api.post("/devices",status_code=201)
def create_device(body:DeviceIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    return device_json(db, create_inventory_device(db, user, body))

def end_collar_assignment(db, assignment, user, at):
    if assignment.valid_from >= at:
        raise HTTPException(409,"El fin de la asociación debe ser posterior a su inicio")
    if db.scalar(select(Telemetry.id).where(Telemetry.assignment_id==assignment.id,Telemetry.observed_at>=at).limit(1)):
        raise HTTPException(409,"La vigencia recortaría lecturas históricas de la asociación anterior. Selecciona una fecha posterior a esas lecturas")
    assignment.valid_to=at
    resolve_assignment_events(db,assignment,user.id,at)
    append_audit(db,user.farm_id,user.id,"assignment",assignment.id,"close",after={"valid_to":at.isoformat()})

@api.post("/assignments/{assignment_id}/close")
def close_assignment(assignment_id:UUID,body:AssignmentClose|None=None,user=Depends(owner),db=Depends(get_db,scope="function")):
    target=db.execute(select(Assignment.animal_id,Assignment.device_id).where(
        Assignment.id==assignment_id,Assignment.farm_id==user.farm_id)).one_or_none()
    if target is None:
        raise HTTPException(403,"Recurso no autorizado para este predio")
    accessible(db,Animal,target.animal_id,user,True,no_key_update=True)
    accessible(db,Device,target.device_id,user,True)
    assignment=accessible(db,Assignment,assignment_id,user,True)
    now=utcnow()
    at=(body.effective_at if body else None) or now
    if at>now:
        raise HTTPException(422,"Vigencia futura no admitida")
    if assignment.valid_from>now or (assignment.valid_to is not None and assignment.valid_to<=now):
        raise HTTPException(409,"La asociación ya no está vigente. Actualiza la ficha del collar")
    end_collar_assignment(db,assignment,user,at)
    clear_animal_monitoring(db,assignment.animal_id)
    db.flush()
    return {"id":assignment.id,"animal_id":assignment.animal_id,"device_id":assignment.device_id,
            "valid_from":assignment.valid_from,"valid_to":assignment.valid_to}

@api.post("/assignments",status_code=201)
def assign(body:AssignmentIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    animal=accessible(db,Animal,body.animal_id,user,True)
    device=accessible(db,Device,body.device_id,user,True)
    if not animal.enabled or not device.enabled:raise HTTPException(422,"Animal y dispositivo deben estar habilitados")
    at=valid_effective(body.effective_at)
    existing=db.scalars(select(Assignment).where(or_(Assignment.animal_id==animal.id,Assignment.device_id==device.id),or_(Assignment.valid_to.is_(None),Assignment.valid_to>at)).with_for_update()).all()
    if existing and not body.replace:raise HTTPException(409,"Asociación existente; cierre explícito requerido")
    affected_animals={animal.id}
    for old in existing:
        end_collar_assignment(db,old,user,at)
        affected_animals.add(old.animal_id)
    db.flush()
    from .v3_api import active_holding
    holding=active_holding(db,animal.id,user.farm_id)
    row=Assignment(id=uuid4(),farm_id=user.farm_id,animal_id=animal.id,animal_holding_id=holding["id"],device_id=device.id,assigned_by=user.id,valid_from=at)
    db.add(row)
    for animal_id in sorted(affected_animals,key=str):clear_animal_monitoring(db,animal_id)
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
    ids=body.sector_ids or [body.sector_id]
    selected={sid:accessible(db,Sector,sid,user,True) for sid in sorted(ids,key=str)}
    if any(not sector.active for sector in selected.values()):raise HTTPException(409,"Seleccione sectores activos")
    if not body.confirm_impact:raise HTTPException(422,"Debe confirmar el impacto en asignaciones vigentes")
    old=None
    if body.geofence_key:
        old=db.scalar(select(Geofence).where(Geofence.geofence_key==body.geofence_key,Geofence.active).with_for_update())
        if old is None:raise HTTPException(409,"Geocerca inexistente o sin versión activa")
        accessible(db,Geofence,old.id,user)
    elif body.expected_version:
        # Compatibility with old clients is safe only with an unambiguous fence.
        candidates=db.scalars(select(Geofence).where(Geofence.sector_id==ids[0],Geofence.farm_id==user.farm_id,Geofence.active).with_for_update()).all()
        if len(candidates)!=1:raise HTTPException(409,"Seleccione la identidad de la geocerca que desea editar")
        old=candidates[0]
    if (old.version if old else 0)!=body.expected_version:raise HTTPException(409,"Versión obsoleta; recargue la geocerca")
    primary=body.sector_id or (old.sector_id if old and old.sector_id in ids else ids[0])
    zones=db.scalars(select(PastureAssignment).where(PastureAssignment.geofence_id==old.id,PastureAssignment.valid_to.is_(None)).with_for_update()).all() if old else []
    if zones and primary!=old.sector_id:raise HTTPException(409,"Transfiera las asignaciones de pastoreo antes de cambiar el sector principal")
    encoded=json.dumps(body.geometry)
    if not db.scalar(select(func.ST_IsValid(func.ST_SetSRID(func.ST_GeomFromGeoJSON(encoded),4326)))):raise HTTPException(422,"Polígono inválido: intersección o anillo inválido")
    now=utcnow()
    if old:old.active=False;old.valid_to=now;db.flush()
    g=Geofence(id=uuid4(),geofence_key=old.geofence_key if old else uuid4(),farm_id=user.farm_id,sector_id=primary,name=body.name,version=body.expected_version+1,geometry=func.ST_SetSRID(func.ST_GeomFromGeoJSON(encoded),4326),active=True,created_at=now,created_by=user.id)
    db.add(g);db.flush()
    db.add_all([GeofenceSector(geofence_id=g.id,sector_id=sid,farm_id=user.farm_id) for sid in ids]);db.flush()
    for zone in zones:
        zone.valid_to=now;db.flush()
        db.add(PastureAssignment(farm_id=user.farm_id,animal_id=zone.animal_id,animal_holding_id=zone.animal_holding_id,assigned_by=user.id,geofence_id=g.id,valid_from=now))
        reset_pasture_monitoring(db,zone.animal_id,user.farm_id,g.id,user.id,now)
    append_audit(db,user.farm_id,user.id,"geofence",g.id,"version_create",after={"geofence_key":str(g.geofence_key),"sector_ids":[str(sid) for sid in ids],"version":g.version,"geometry":body.geometry,"previous_id":str(old.id) if old else None})
    return fence_json(db,g)

@api.post("/pasture-assignments",status_code=201)
def assign_pasture(body:PastureIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    a=accessible(db,Animal,body.animal_id,user,True,no_key_update=True)
    g=accessible(db,Geofence,body.geofence_id,user,True)
    if not g.active:raise HTTPException(409,"Seleccione la versión activa de la geocerca")
    if not db.get(Sector,g.sector_id).active:raise HTTPException(409,"Seleccione un sector activo")
    if not a.enabled:raise HTTPException(409,"El animal debe estar habilitado para asignarle pastoreo")
    at=valid_effective(body.effective_at)
    if at<g.created_at:raise HTTPException(422,"Asignación precede a la versión de geocerca")
    if body.expected_device_id is not None and not db.scalar(select(Assignment.id).where(
        Assignment.animal_id==a.id,Assignment.device_id==body.expected_device_id,at_time(Assignment,utcnow()))):
        raise HTTPException(409,"El collar ya no está asociado a ese animal. Revisa el traslado")
    old=db.scalar(select(PastureAssignment).where(PastureAssignment.animal_id==a.id,PastureAssignment.valid_to.is_(None)).with_for_update())
    if old and old.geofence_id==g.id and body.effective_at is None:
        return {"id":old.id,"animal_id":a.id,"geofence_id":g.id,"valid_from":old.valid_from,"valid_to":None}
    if "expected_pasture_id" in body.model_fields_set and body.expected_pasture_id!=(old.id if old else None):
        raise HTTPException(409,"La zona vigente cambió. Revisa el traslado y vuelve a confirmarlo")
    if old:
        if old.valid_from>=at:raise HTTPException(409,"Inicio debe ser posterior al previo")
        old.valid_to=at;db.flush()
        append_audit(db,user.farm_id,user.id,"pasture_assignment",old.id,"close",after={"valid_to":at.isoformat()})
    from .v3_api import active_holding
    holding=active_holding(db,a.id,user.farm_id)
    row=PastureAssignment(id=uuid4(),farm_id=user.farm_id,animal_id=a.id,animal_holding_id=holding["id"],geofence_id=g.id,assigned_by=user.id,valid_from=at);db.add(row)
    a.sector_id=g.sector_id
    reset_pasture_monitoring(db,a.id,user.farm_id,g.id,user.id,at)
    db.flush();append_audit(db,user.farm_id,user.id,"pasture_assignment",row.id,"create",after={"animal_id":str(a.id),"geofence_id":str(g.id),"valid_from":at.isoformat()})
    return {"id":row.id,"animal_id":a.id,"geofence_id":g.id,"valid_from":at,"valid_to":None}
@api.get("/events")
def events(condition:Literal["active","resolved"]|None=None,attention:Literal["pending","acknowledged","in_review","concluded"]|None=None,limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),user=Depends(current_user),db=Depends(get_db, scope="function")):
    query=select(Event).where(Event.farm_id==user.farm_id)
    if condition:query=query.where(Event.condition==condition)
    if attention:query=query.where(Event.attention==attention)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    return {"items":events_json(db,db.scalars(query.order_by(Event.opened_at.desc()).limit(limit).offset(offset)).all()),"total":total}
@api.post("/events/{event_id}/actions")
def action(event_id:UUID,body:ActionIn,user=Depends(operator),db=Depends(get_db, scope="function")):
    e=accessible(db,Event,event_id,user,True);before={"attention":e.attention,"condition":e.condition}
    e.attention={"acknowledge":"acknowledged","review":"in_review","conclude":"concluded","reopen":"pending"}[body.action]
    db.add(EventAction(event_id=e.id,actor_id=user.id,action=body.action,note=body.note))
    append_audit(db,user.farm_id,user.id,"event",e.id,body.action,before,{"attention":e.attention,"condition":e.condition,"note":body.note});db.flush()
    return events_json(db,[e])[0]
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
def settings_response(r,user):
    config=settings()
    return {**settings_json(r),"capabilities":{
        "can_edit":bool(config.mirror_mode != 'replica' and user.farm_id and user.role in ("owner","admin")),
        "environment":config.app_env,
        "preventive_rules_validated":config.preventive_rules_validated,
        "preventive_rules_allowed":config.preventive_rules_allowed,
        "temperature_rule_allowed":config.temperature_rule_allowed}}

@api.get("/settings")
def get_settings(user=Depends(current_user),db=Depends(get_db, scope="function")):
    if not user.farm_id:raise HTTPException(409,"Selecciona un predio autorizado para consultar las reglas")
    r=db.get(RuleSettings,user.farm_id)
    if not r:raise HTTPException(503,"Reglas no inicializadas")
    return settings_response(r,user)
@api.post("/settings/preview")
def preview_sensor_rules(body:SensorPreviewIn,user=Depends(owner)):
    if not user.farm_id:raise HTTPException(409,"Selecciona un predio autorizado para probar las reglas")
    temp=temperature_alert(body.surface_temperature_c,body.temperature_high_c)
    activity=low_activity_alert(body.activity_average,body.activity_low_threshold)
    return {
        "temperature":"missing_data" if temp is None else "alert" if temp else "clear",
        "activity":"missing_data" if activity is None else "incomplete_window" if not body.activity_window_complete else "alert" if activity else "clear",
        "activity_window_minutes":body.activity_window_minutes,
    }

@api.put("/settings")
def update_settings(body:SettingsIn,user=Depends(owner),db=Depends(get_db, scope="function")):
    if not user.farm_id:raise HTTPException(409,"Selecciona un predio autorizado para configurar las reglas")
    r=db.get(RuleSettings,user.farm_id,with_for_update=True)
    if not r:raise HTTPException(503,"Reglas no inicializadas")
    if r.version!=body.expected_version:raise HTTPException(409,"Versión de reglas obsoleta")
    config=settings()
    if ((body.temperature_enabled and not config.temperature_rule_allowed)
            or (body.activity_enabled and not config.preventive_rules_allowed)):
        raise HTTPException(422,"Sensores preventivos requieren validación de campo PREVENTIVE_RULES_VALIDATED")
    before=settings_json(r)
    for k,v in body.model_dump(exclude={"expected_version"}).items():setattr(r,k,v)
    r.version+=1
    disabled_types=[kind for enabled,kind in ((r.temperature_enabled,"high_surface_temperature"),
                                              (r.activity_enabled,"low_activity")) if not enabled]
    if disabled_types:
        now=utcnow()
        active_events=db.scalars(select(Event).where(Event.farm_id==user.farm_id,Event.condition=="active",
                                                     Event.type.in_(disabled_types)).with_for_update()).all()
        for event in active_events:
            event.condition="resolved";event.resolved_at=max(now,event.opened_at)
            event.detail={**event.detail,"resolution_reason":"rule_disabled","resolution":"Regla desactivada en el predio",
                          "resolved_by_rule_version":r.version}
            append_audit(db,user.farm_id,user.id,"event",event.id,"resolved",after={"condition":"resolved","reason":"rule_disabled","rule_version":r.version})
    db.flush();append_audit(db,user.farm_id,user.id,"rule_settings",user.farm_id,"update",before,settings_json(r))
    return settings_response(r,user)
@api.get("/audit")
def audit(limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),user=Depends(owner),db=Depends(get_db, scope="function")):
    query=select(Audit).where(Audit.farm_id==user.farm_id)
    if user.role != "admin":
        query=query.where(Audit.object_type!="account_request", Audit.action!="account_closure_requested")
    return {"items":[{k:getattr(a,k) for k in ["id","actor_id","object_type","object_id","action","at","before","after"]} for a in db.scalars(query.order_by(Audit.at.desc()).limit(limit).offset(offset)).all()],"total":db.scalar(select(func.count()).select_from(query.subquery()))}
@api.get("/notifications")
def notifications(user=Depends(current_user),db=Depends(get_db, scope="function")):
    rows=db.scalars(select(Notification).join(Event).where(Event.farm_id==user.farm_id).order_by(Notification.created_at.desc()).limit(500)).all()
    read_ids = set()
    if rows and settings().mirror_mode == 'replica':
        read_ids = set(db.scalars(text("SELECT notification_id FROM mirror_notification_reads WHERE user_id=:u AND notification_id=ANY(:ids)"),
                                  {'u': user.id, 'ids': [notice.id for notice in rows]}))
    return {"items":[{"id":n.id,"event_id":n.event_id,"channel":n.channel,"status":'read' if n.id in read_ids else n.status,"created_at":n.created_at,"attempts":[{k:getattr(a,k) for k in ["attempt","at","status","provider_id","error"]} for a in db.scalars(select(NotificationAttempt).where(NotificationAttempt.notification_id==n.id).order_by(NotificationAttempt.attempt)).all()]} for n in rows],"total":db.scalar(select(func.count()).select_from(Notification).join(Event).where(Event.farm_id==user.farm_id))}
@api.post("/telemetry",dependencies=[Depends(service_auth)],status_code=201)
@api.post("/ingest/telemetry",dependencies=[Depends(service_auth)],status_code=201)
def telemetry(body:TelemetryIn,db=Depends(get_db, scope="function"),
              farm_id:UUID|None=Header(default=None,alias="X-Farm-ID")):
    if settings().app_env == 'production':
        raise HTTPException(403, 'En producción la T3 entrega en /api/v1/ingest/receiver-batch')
    return ingest(db, body, detect_candidates=True, capture_farm_id=farm_id)

@api.get("/reports/telemetry.{format}")
def export_history(format: ExportFormat, start: datetime | None = None, end: datetime | None = None,
                   animal_id: UUID | None = None, day: date | None = None, hardware_id: str | None = None,
                   delimiter: CsvDelimiter = 'comma', user=Depends(current_user), db=Depends(get_db, scope='function')):
    farm = db.get(Farm, user.farm_id) if user.farm_id else None
    if not farm:
        raise HTTPException(403, 'Seleccione un predio autorizado')
    if day is not None:
        if start is not None or end is not None or day == date.max:
            raise HTTPException(422, 'Selecciona un día válido o un intervalo, no ambos')
        start, end = farm_day_period(day, farm.timezone)
    period(start, end)
    if animal_id:
        accessible(db, Animal, animal_id, user)
    keys = ('animal_id', 'device_id', 'observed_at', 'received_at', 'longitude', 'latitude', 'gnss_valid',
            'surface_temperature_c', 'activity_index', 'battery_mv', 'source')
    statement = select(*(getattr(Telemetry, key) for key in keys)).where(Telemetry.farm_id == farm.id)
    if start:
        statement = statement.where(Telemetry.observed_at >= start)
    if end:
        statement = statement.where(Telemetry.observed_at < end)
    if animal_id:
        statement = statement.where(Telemetry.animal_id == animal_id)
    if hardware_id:
        statement = statement.where(Telemetry.device_id.in_(
            select(Device.id).where(Device.farm_id == farm.id, Device.hardware_id == hardware_id)))
    zone = ZoneInfo(farm.timezone)
    metadata = [('Predio', farm.name), ('ID del predio', farm.id), ('Zona horaria', farm.timezone),
                ('Generado', utcnow()), ('Período', day or ('Intervalo' if start or end else 'Todo el historial')),
                ('Desde (inclusive)', start or 'Sin límite'), ('Hasta (exclusivo)', end or 'Sin límite'),
                ('Bovino (ID)', animal_id or 'Todos'), ('Collar', hardware_id or 'Todos'),
                ('Máximo de filas', EXPORT_LIMIT)]
    filename = 'geocattle-telemetria'
    if day:
        filename += f'-{day}'
    elif start or end:
        first = start.astimezone(zone).date() if start else 'sin-inicio'
        last = end.astimezone(zone).date() if end else 'sin-fin'
        filename += f'-{first}_{last}'
    columns, formats, rows = keys, None, None
    if format == 'xlsx':
        # El libro es para personas: DIIO, bovino y collar en vez de identificadores internos.
        columns = ('DIIO', 'Bovino', 'Collar', 'Observado', 'Recibido', 'Latitud', 'Longitud', 'Posición GPS válida',
                   'Temperatura superficial (°C)', 'Índice de actividad', 'Batería (mV)', 'Origen')
        formats = {5: '0.000000', 6: '0.000000', 8: '0.0', 9: '0.000', 10: '0'}
        statement = (select(Animal.diio, Animal.name, Device.hardware_id, Telemetry.observed_at, Telemetry.received_at,
                            Telemetry.latitude, Telemetry.longitude, Telemetry.gnss_valid, Telemetry.surface_temperature_c,
                            Telemetry.activity_index, Telemetry.battery_mv, Telemetry.source)
                     .select_from(Telemetry).join(Device, Device.id == Telemetry.device_id)
                     .outerjoin(Animal, Animal.id == Telemetry.animal_id)
                     .where(Telemetry.id.in_(statement.with_only_columns(Telemetry.id))))
    statement = statement.order_by(Telemetry.observed_at, Telemetry.id).limit(EXPORT_LIMIT)
    sources = {'academic': 'Collar del prototipo', 'lorawan': 'LoRaWAN', 'sim': 'Simulado'}
    with db.execute(statement.execution_options(yield_per=1000)) as result:
        rows = result if format != 'xlsx' else ((*row[:-1], sources.get(row[-1], row[-1])) for row in result)
        return export_response(columns, rows, format=format, filename=filename, title='Telemetría', zone=zone,
                               metadata=metadata, delimiter=delimiter, legacy_telemetry=True,
                               headers={'X-Export-Limit': str(EXPORT_LIMIT)}, formats=formats)
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
    now=utcnow()
    if not body.enabled and db.scalar(select(Assignment.id).where(Assignment.device_id==d.id,
            or_(Assignment.valid_to.is_(None),Assignment.valid_to>now)).limit(1)):
        raise HTTPException(409,"Desvincula el collar del bovino antes de retirarlo")
    before={"enabled":d.enabled};d.enabled=body.enabled
    if not d.enabled:
        for e in db.scalars(select(Event).where(Event.device_id==d.id,Event.type=="communication_timeout",Event.condition=="active").with_for_update()).all():
            e.condition="resolved";e.resolved_at=utcnow();e.detail={**e.detail,"resolution":"Retiro explícito: comunicación deja de ser esperada"}
    db.flush();append_audit(db,user.farm_id,user.id,"device",d.id,"set_enabled",before,{"enabled":d.enabled})
    return device_json(db,d)
@api.delete("/devices/{device_id}",status_code=204)
def delete_device(device_id:UUID,user=Depends(owner),db=Depends(get_db,scope="function")):
    hardware_id=db.scalar(select(Device.hardware_id).where(Device.id==device_id,Device.farm_id==user.farm_id))
    if hardware_id is None:
        raise HTTPException(403,"Recurso no autorizado para este predio")
    lock_device_identity(db,hardware_id)
    device=accessible(db,Device,device_id,user,True)
    delete_inventory_device(db,user,device)
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
from .mirror_drafts import router as drafts_router
from .v3_device_candidates import router as device_candidates_router
from .v3_gateway_candidates import router as gateway_candidates_router
from .v3_operation_auth import router as operation_auth_router
from .v3_account import router as account_auth_router
app.include_router(auth_v3_router)
app.include_router(operation_auth_router)
app.include_router(account_auth_router)
app.include_router(v3_router)
app.include_router(mirror_router)
app.include_router(drafts_router)
app.include_router(device_candidates_router)
app.include_router(gateway_candidates_router)

from .hardware_api import capture_router, router as hardware_router
app.include_router(hardware_router)
app.include_router(capture_router)
from .v3_animal_reports import router as animal_reports_router
app.include_router(animal_reports_router)
from .v3_owner_exports import router as owner_exports_router
app.include_router(owner_exports_router)
