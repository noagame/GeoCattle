"""Role panels backed by real, tenant-scoped persistence and atomic change review."""
import json
import os
import shutil
from pathlib import Path
import secrets
from datetime import date,datetime,timedelta
from typing import Literal
from types import SimpleNamespace
from uuid import UUID,uuid4
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from sqlalchemy import select,text
from .db import get_db
from .models import User,Farm,Animal,RuleSettings,utcnow
from .security import current_user,owner,hash_password,token_hash
from .v3_security import rows,one,execute,audit,require_step_up
from .v3_operation_auth import require_operation
router=APIRouter(prefix='/api/v1/v3',tags=['Role workspaces V3'])
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class ProfileIn(Strict):
    full_name:str=Field(min_length=1,max_length=150)
    phone:str|None=Field(default=None,max_length=40)
class FarmIn(Strict):
    name:str=Field(min_length=1,max_length=150)
    rup:str|None=Field(default=None,max_length=30)
    address:str|None=Field(default=None,max_length=300)
class FarmPatch(Strict):
    name:str|None=Field(default=None,min_length=1,max_length=150)
    rup:str|None=Field(default=None,max_length=30)
    address:str|None=Field(default=None,max_length=300)
    active:bool|None=None
class OwnerIn(Strict):
    email:str=Field(min_length=5,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    full_name:str=Field(min_length=1,max_length=150)
    password:str=Field(min_length=12,max_length=256)
    max_farms:int=Field(default=1,ge=1,le=1000)
class OwnerPatch(Strict):
    active:bool|None=None
    full_name:str|None=Field(default=None,min_length=1,max_length=150)
    max_farms:int|None=Field(default=None,ge=1,le=1000)
class InviteIn(Strict):
    email:str=Field(min_length=5,max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    role_code:Literal['worker','veterinarian']
class EnrolIn(Strict):
    token:str=Field(min_length=20,max_length=200)
    password:str=Field(min_length=12,max_length=256)
    full_name:str=Field(min_length=1,max_length=150)
class MembershipPatch(Strict):
    role_code:Literal['worker','veterinarian']|None=None
    active:bool|None=None
class TrustIn(Strict):
    membership_id:UUID
    action:Literal['animal_status','animal_report','health_record','battery_replacement']
class DecisionIn(Strict):
    decision:Literal['approved','rejected']
    reason:str|None=Field(default=None,max_length=2000)
class ChangeIn(Strict):
    action:Literal['animal_profile','animal_status','animal_report','health_record','battery_replacement','health_schedule']
    animal_id:UUID|None=None
    device_id:UUID|None=None
    expected_version:int|None=Field(default=None,ge=1)
    payload:dict
    idempotency_key:UUID
class TechnicalPayload(Strict):
    breed:str|None=Field(default=None,max_length=100)
    color:str|None=Field(default=None,max_length=100)
    sex:Literal['female','male','unknown']|None=None
    birth_date:date|None=None
    weight_kg:float|None=Field(default=None,gt=0,le=3000)
    height_cm:float|None=Field(default=None,gt=0,le=300)
class StatusPayload(Strict):status:Literal['active','missing','dead','slaughtered','retired']
class ReportPayload(Strict):description:str=Field(min_length=1,max_length=5000)
class BatteryPayload(Strict):
    battery_id:str|None=Field(default=None,max_length=120)
    result:str=Field(min_length=1,max_length=3000)
class TreatmentPayload(Strict):
    product_name:str=Field(min_length=1,max_length=200)
    dose_value:float=Field(gt=0,le=100000)
    dose_unit:str=Field(min_length=1,max_length=40)
    route:str=Field(min_length=1,max_length=80)
    administered_at:datetime|None=None
    withdrawal_meat_until:date|None=None
    withdrawal_milk_until:date|None=None
    product_registration:str|None=None
    batch_number:str|None=None
    withdrawal_basis:str|None=None
class HealthPayload(Strict):
    event_type:Literal['examination','vaccination','antibiotic','pathology','diagnosis','procedure','injury','death','observation']
    description:str=Field(min_length=1,max_length=5000)
    operation:Literal['record','correct','void']='record'
    target_event_id:UUID|None=None
    occurred_at:datetime|None=None
    diagnosis:str|None=Field(default=None,max_length=5000)
    treatments:list[TreatmentPayload]=Field(default_factory=list,max_length=20)
    @model_validator(mode='after')
    def target(self):
        if (self.operation=='record') != (self.target_event_id is None):raise ValueError('Corrección/anulación requiere evento original; registro nuevo no lo admite')
        return self
class SchedulePayload(Strict):
    kind:Literal['vaccination','antibiotic','checkup']
    description:str=Field(min_length=1,max_length=3000)
    due_at:datetime
    operation:Literal['plan','replace','cancel','complete']='plan'
    target_schedule_id:UUID|None=None
    completed_event_id:UUID|None=None
    @model_validator(mode='after')
    def target(self):
        if (self.operation=='plan') != (self.target_schedule_id is None):raise ValueError('Operación de agenda requiere plan original')
        if (self.operation=='complete') != (self.completed_event_id is not None):raise ValueError('Completar requiere evento sanitario administrado')
        return self
class GatewayIn(Strict):
    gateway_eui:str=Field(pattern=r'^[0-9a-fA-F]{16}$')
    name:str=Field(min_length=1,max_length=150)
    longitude:float|None=Field(default=None,ge=-180,le=180)
    latitude:float|None=Field(default=None,ge=-90,le=90)
    @model_validator(mode='after')
    def coordinates(self):
        if (self.longitude is None)!=(self.latitude is None):raise ValueError('Latitud y longitud se informan juntas')
        return self
class GatewayPatch(Strict):
    name:str|None=Field(default=None,min_length=1,max_length=150)
    status:Literal['installed','maintenance','retired']|None=None


def listing(data):return {'items':data,'total':len(data)}
def admin(user=Depends(current_user)):
    if user.base_role!='admin':raise HTTPException(403,'Se requiere administrador de plataforma')
    return user

def farm_scope(user):
    if not user.farm_id:raise HTTPException(409,'Selecciona un predio autorizado para continuar')
    return user.farm_id

def owned_account(db,user):
    result=one(db,'SELECT * FROM owner_accounts WHERE owner_user_id=:u AND active FOR UPDATE',u=user.id)
    if not result:raise HTTPException(403,'Cuenta de dueño no disponible')
    return result

def membership(db,user):
    return one(db,'SELECT * FROM farm_memberships WHERE user_id=:u AND farm_id=:f AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now())',u=user.id,f=farm_scope(user))

def active_holding(db,animal_id,farm_id):
    result=one(db,'SELECT * FROM animal_holdings WHERE animal_id=:a AND farm_id=:f AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now()) FOR UPDATE',a=animal_id,f=farm_id)
    if not result:raise HTTPException(403,'Animal sin permanencia vigente en este predio')
    return result

def scoped(db,table,ident,user,lock=False):
    assert table in ('farms','farm_memberships','trust_grants','change_requests','gateways','animals','devices','health_events','health_schedules')
    key='id' if table=='farms' else 'farm_id'
    result=one(db,f'SELECT * FROM {table} WHERE id=:i AND {key}=:f'+(' FOR UPDATE' if lock else ''),i=ident,f=farm_scope(user))
    if not result:raise HTTPException(403,'Recurso no autorizado en este predio')
    return result

def notify(db,farm_id,recipient,message,request_id=None,schedule_id=None):
    execute(db,"INSERT INTO notifications(id,farm_id,recipient_id,request_id,schedule_id,channel,status,message,next_attempt_at,created_at) VALUES(:i,:f,:u,:r,:s,'in_app','pending',:m,now(),now())",i=uuid4(),f=farm_id,u=recipient,r=request_id,s=schedule_id,m=message)

def owner_id(db,farm_id):
    result=one(db,'SELECT a.owner_user_id FROM farms f JOIN owner_accounts a ON a.id=f.account_id WHERE f.id=:f',f=farm_id)
    return result['owner_user_id'] if result else None

def global_audit(db,user,*args,**kwargs):audit(db,SimpleNamespace(id=user.id,farm_id=None),*args,**kwargs)


@router.get('/profile')
def profile(user=Depends(current_user)):
    return {k:getattr(user,k) for k in ('id','username','email','full_name','phone')}
@router.patch('/profile')
def update_profile(body:ProfileIn,user=Depends(current_user),db=Depends(get_db,scope='function')):
    dbuser=db.get(User,user.id);dbuser.full_name=body.full_name;dbuser.phone=body.phone;dbuser.version+=1
    audit(db,user,'profile_update','user',user.id,after=body.model_dump())
    return {**profile(user),**body.model_dump()}

@router.get('/farms')
def farms(user=Depends(current_user),db=Depends(get_db,scope='function')):
    if user.base_role=='admin':
        return listing(rows(db,'SELECT id,account_id,name,rup,address,active,timezone FROM farms WHERE environment=:e ORDER BY name',e=settings_env()))
    if user.base_role=='owner':
        return listing(rows(db,'SELECT f.id,f.account_id,f.name,f.rup,f.address,f.active,f.timezone FROM farms f JOIN owner_accounts a ON a.id=f.account_id WHERE a.owner_user_id=:u AND a.active AND f.environment=:e ORDER BY f.name',u=user.id,e=settings_env()))
    ids=[f['id'] for f in user.farms]
    if not ids:return listing([])
    return listing(rows(db,'SELECT id,account_id,name,rup,address,active,timezone FROM farms WHERE id=ANY(:ids) ORDER BY name',ids=ids))
@router.post('/farms',status_code=201)
def create_farm(body:FarmIn,user=Depends(owner),db=Depends(get_db,scope='function')):
    if user.base_role=='admin':raise HTTPException(422,'Crea predios desde el contexto de una cuenta dueña')
    account=owned_account(db,user)
    count=one(db,'SELECT count(*) AS n FROM farms WHERE account_id=:a AND active',a=account['id'])['n']
    if count>=account['max_farms']:raise HTTPException(409,'Se alcanzó el cupo de predios autorizado')
    farm=Farm(id=uuid4(),name=body.name,environment=settings_env(),account_id=account['id'],rup=body.rup,address=body.address,active=True)
    db.add(farm);db.flush();db.add(RuleSettings(farm_id=farm.id));execute(db,"INSERT INTO farm_features(farm_id,feature_code) SELECT :f,code FROM features WHERE code<>'fma'",f=farm.id);audit(db,user,'create','farm',farm.id,after=body.model_dump())
    return {'id':farm.id,**body.model_dump(),'active':True}
@router.patch('/farms/{ident}')
def update_farm(ident:UUID,body:FarmPatch,user=Depends(owner),db=Depends(get_db,scope='function')):
    farm=db.get(Farm,ident)
    permitted=farm and farm.environment==settings_env() and (user.base_role=='admin' or one(db,'SELECT id FROM owner_accounts WHERE id=:a AND owner_user_id=:u AND active',a=farm.account_id,u=user.id))
    if not permitted:raise HTTPException(403,'Predio no autorizado')
    changes=body.model_dump(exclude_unset=True)
    if changes.get('active') is False and one(db,'SELECT id FROM assignments WHERE farm_id=:f AND valid_to IS NULL LIMIT 1',f=ident):raise HTTPException(409,'Cierra las asignaciones antes de desactivar el predio')
    for k,v in changes.items():
        if k in ('name','active') and v is None:raise HTTPException(422,'Nombre y estado no pueden ser nulos')
        setattr(farm,k,v)
    audit(db,user,'update','farm',ident,after=changes)
    return {'id':farm.id,'name':farm.name,'rup':farm.rup,'address':farm.address,'active':farm.active}

def settings_env():
    from .settings import settings
    return settings().app_env

@router.get('/admin/owners')
def owners(user=Depends(admin),db=Depends(get_db,scope='function')):
    return listing(rows(db,'SELECT a.*,u.email,u.username,u.full_name,u.active AS user_active FROM owner_accounts a JOIN users u ON u.id=a.owner_user_id ORDER BY a.created_at DESC'))
@router.post('/admin/owners',status_code=201)
def create_owner(body:OwnerIn,user=Depends(admin),db=Depends(get_db,scope='function')):
    email=body.email.strip().lower()
    identity=User(id=uuid4(),username=email,email=email,full_name=body.full_name,password_hash=hash_password(body.password),role='owner',active=True,farm_id=None)
    db.add(identity);db.flush();ident=uuid4()
    execute(db,'INSERT INTO owner_accounts(id,owner_user_id,display_name,max_farms) VALUES(:i,:u,:n,:m)',i=ident,u=identity.id,n=body.full_name,m=body.max_farms)
    global_audit(db,user,'create_owner','owner_account',ident,after={'email':email,'max_farms':body.max_farms})
    return {'id':ident,'owner_user_id':identity.id,'email':email,'full_name':body.full_name,'max_farms':body.max_farms,'active':True}
@router.patch('/admin/owners/{ident}')
def change_owner(ident:UUID,body:OwnerPatch,user=Depends(admin),db=Depends(get_db,scope='function')):
    account=one(db,'SELECT * FROM owner_accounts WHERE id=:i FOR UPDATE',i=ident)
    if not account:raise HTTPException(404,'Cuenta no encontrada')
    if body.max_farms is not None:
        count=one(db,'SELECT count(*) n FROM farms WHERE account_id=:i AND active',i=ident)['n']
        if body.max_farms<count:raise HTTPException(409,'El cupo no puede ser menor que los predios activos')
        execute(db,'UPDATE owner_accounts SET max_farms=:m WHERE id=:i',m=body.max_farms,i=ident)
    if body.active is not None:
        execute(db,'UPDATE owner_accounts SET active=:v WHERE id=:i',v=body.active,i=ident)
        execute(db,'UPDATE users SET active=:v WHERE id=:u',v=body.active,u=account['owner_user_id'])
        if not body.active:execute(db,'UPDATE login_sessions SET revoked_at=now() WHERE user_id=:u',u=account['owner_user_id'])
    if body.full_name:
        execute(db,'UPDATE users SET full_name=:n WHERE id=:u',n=body.full_name,u=account['owner_user_id'])
        execute(db,'UPDATE owner_accounts SET display_name=:n WHERE id=:i',n=body.full_name,i=ident)
    global_audit(db,user,'update_owner','owner_account',ident,after=body.model_dump(exclude_unset=True))
    return one(db,'SELECT * FROM owner_accounts WHERE id=:i',i=ident)
@router.get('/admin/users')
def admin_users(user=Depends(admin),db=Depends(get_db,scope='function')):
    return listing(rows(db,'SELECT id,username,email,full_name,phone,role,active FROM users ORDER BY username LIMIT 500'))
@router.patch('/admin/users/{ident}')
def change_user(ident:UUID,body:OwnerPatch,user=Depends(admin),db=Depends(get_db,scope='function')):
    target=db.get(User,ident)
    if not target:raise HTTPException(404,'Usuario no encontrado')
    if target.role=='admin' or target.id==user.id:raise HTTPException(403,'Este formulario no modifica administradores')
    if body.full_name:target.full_name=body.full_name
    if body.active is not None:
        target.active=body.active
        if not body.active:execute(db,'UPDATE login_sessions SET revoked_at=now() WHERE user_id=:u',u=ident)
    global_audit(db,user,'update_user','user',ident,after=body.model_dump(exclude_unset=True))
    return {'id':ident,'active':target.active,'full_name':target.full_name}
def query_period(start,end,days,now):
    if start and (start.tzinfo is None or start.utcoffset() is None):raise HTTPException(422,'Inicio requiere zona horaria')
    if end and (end.tzinfo is None or end.utcoffset() is None):raise HTTPException(422,'Fin requiere zona horaria')
    end=end or now
    start=start or end-timedelta(days=days)
    if start>=end or end-start>timedelta(days=366):raise HTTPException(422,'El período debe ser positivo y no superar 366 días')
    return start,end

@router.get('/admin/kpis')
def kpis(account_id:UUID|None=None,farm_id:UUID|None=None,start:datetime|None=None,end:datetime|None=None,user=Depends(admin),db=Depends(get_db,scope='function')):
    now=utcnow()
    alert_start,alert_end=query_period(start,end,30,now)
    usage_start,usage_end=query_period(start,end,1,now)
    filt=(' AND f.account_id=:a' if account_id else '')+(' AND f.id=:f' if farm_id else '')
    p={**({'a':account_id} if account_id else {}),**({'f':farm_id} if farm_id else {})}
    if farm_id and not one(db,'SELECT id FROM farms WHERE id=:f'+(' AND account_id=:a' if account_id else ''),**p):raise HTTPException(422,'El predio no pertenece a la cuenta seleccionada')
    count=lambda q:db.execute(text(q),p).scalar_one()
    alerts=rows(db,"SELECT (e.opened_at AT TIME ZONE f.timezone)::date AS day,count(*) AS count FROM events e JOIN farms f ON f.id=e.farm_id WHERE e.opened_at>=:start AND e.opened_at<:end"+filt+' GROUP BY 1 ORDER BY 1',start=alert_start,end=alert_end,**p)
    if account_id or farm_id:
        users_count=count("SELECT count(DISTINCT u.id) FROM users u WHERE u.active AND (EXISTS(SELECT 1 FROM owner_accounts a JOIN farms f ON f.account_id=a.id WHERE a.owner_user_id=u.id"+filt+") OR EXISTS(SELECT 1 FROM farm_memberships m JOIN farms f ON f.id=m.farm_id WHERE m.user_id=u.id AND m.valid_from<=now() AND (m.valid_to IS NULL OR m.valid_to>now())"+filt+"))")
    else:users_count=count('SELECT count(*) FROM users WHERE active')
    usage=one(db,"SELECT count(*) AS requests,count(*) FILTER(WHERE m.status_code>=400) AS error_requests,coalesce(sum(m.request_bytes),0) AS request_bytes,coalesce(sum(m.response_bytes),0) AS response_bytes,percentile_cont(0.95) WITHIN GROUP(ORDER BY m.duration_ms) AS p95_ms FROM request_metrics m LEFT JOIN farms f ON f.id=m.farm_id WHERE m.occurred_at>=:start AND m.occurred_at<:end"+filt,start=usage_start,end=usage_end,**p)
    disk=shutil.disk_usage('/app' if os.path.exists('/app') else '/')
    resources={'database_bytes':db.scalar(text('SELECT pg_database_size(current_database())')),'disk_free_bytes':disk.free,'load_1m':os.getloadavg()[0]}
    try:resources['api_rss_bytes']=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
    except (OSError,ValueError,IndexError):resources['api_rss_bytes']=None
    return {'generated_at':now,'period':{'start':alert_start,'end':alert_end},'usage_period':{'start':usage_start,'end':usage_end},'usage_24h':usage,'instance_resources':resources,'users':users_count,
      'animals':count('SELECT count(*) FROM animals a JOIN farms f ON f.id=a.farm_id WHERE a.enabled AND EXISTS(SELECT 1 FROM animal_holdings h WHERE h.animal_id=a.id AND h.farm_id=f.id AND h.valid_from<=now() AND (h.valid_to IS NULL OR h.valid_to>now()))'+filt),
      'farms':count('SELECT count(*) FROM farms f WHERE f.active'+filt),'sectors':count('SELECT count(*) FROM sectors s JOIN farms f ON f.id=s.farm_id WHERE s.active'+filt),
      'installed_devices':count('SELECT count(DISTINCT x.device_id) FROM assignments x JOIN farms f ON f.id=x.farm_id WHERE x.valid_from<=now() AND (x.valid_to IS NULL OR x.valid_to>now())'+filt),
      'inventoried_devices':count('SELECT count(*) FROM devices d JOIN farms f ON f.id=d.farm_id WHERE true'+filt),
      'software_modules':count('SELECT count(DISTINCT x.feature_code) FROM farm_features x JOIN farms f ON f.id=x.farm_id WHERE x.enabled'+filt),
      'alerts_by_day':alerts,'requests':usage['requests'],'error_requests':usage['error_requests'],
      'farm_options':rows(db,'SELECT id,name,account_id FROM farms WHERE environment=:e ORDER BY name,id',e=settings_env()),
      'accounts':rows(db,'SELECT id,display_name FROM owner_accounts ORDER BY display_name,id')}
@router.get('/audit')
def audits(user=Depends(current_user),db=Depends(get_db,scope='function'),limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0),q:str|None=Query(None,max_length=200),actor_id:UUID|None=None,action:str|None=Query(None,max_length=100),entity:str|None=Query(None,max_length=100),farm_id:UUID|None=None,start:datetime|None=None,end:datetime|None=None):
    if user.role not in ('admin','owner'):raise HTTPException(403,'Sin permiso de auditoría')
    predicates=[];p={}
    if user.role!='admin':
        if farm_id and farm_id!=farm_scope(user):raise HTTPException(403,'Predio no autorizado')
        farm_id=farm_scope(user)
    if farm_id:predicates.append('a.farm_id=:f');p['f']=farm_id
    for name,value,column in [('actor',actor_id,'a.actor_id'),('action',action,'a.action'),('entity',entity,'a.object_type')]:
        if value:predicates.append(column+'=:'+name);p[name]=value
    if start or end:
        period_start,period_end=query_period(start,end,30,utcnow())
        predicates.extend(['a.at>=:start','a.at<:end']);p.update(start=period_start,end=period_end)
    if q and q.strip():
        predicates.append("concat_ws(' ',a.action,a.object_type,a.actor_id::text,u.username,u.full_name) ILIKE :q")
        p['q']='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    where=' WHERE '+' AND '.join(predicates) if predicates else ''
    source=' FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id'
    data=rows(db,'SELECT a.id,a.farm_id,a.actor_id,a.object_type,a.object_id,a.action,a.at,u.username AS actor_name,u.username AS username,a.before,a.after'+source+where+' ORDER BY a.at DESC,a.id LIMIT :n OFFSET :offset',n=limit,offset=offset,**p)
    total=one(db,'SELECT count(*) AS n'+source+where,**p)['n']
    audit(db,user,'read_audit','audit_log');return {'items':data,'total':total}

@router.get('/invitations')
def invitations(request:Request,user=Depends(owner),db=Depends(get_db,scope='function')):
    require_step_up(request)
    return listing(rows(db,'SELECT id,email,role_code,expires_at,accepted_at,revoked_at,created_at FROM invitations WHERE farm_id=:f ORDER BY created_at DESC LIMIT 100',f=farm_scope(user)))
@router.post('/invitations',status_code=201)
def invite(body:InviteIn,request:Request,user=Depends(owner),db=Depends(get_db,scope='function')):
    require_operation(request,db,user,body.model_dump(mode='json',exclude_unset=True));farm_id=farm_scope(user);token=secrets.token_urlsafe(40);ident=uuid4()
    execute(db,"INSERT INTO invitations(id,farm_id,email,role_code,token_hash,invited_by,expires_at) VALUES(:i,:f,:e,:r,:t,:u,now()+interval '48 hours')",i=ident,f=farm_id,e=body.email.lower().strip(),r=body.role_code,t=token_hash(token),u=user.id)
    audit(db,user,'invite','invitation',ident,after={'email':body.email,'role':body.role_code})
    return {'id':ident,'email':body.email.lower().strip(),'role_code':body.role_code,'invitation_token':token,'delivery':'manual','message':'Comparte el enlace de forma privada con el destinatario; correo externo no configurado'}
@router.post('/enrol',status_code=201)
def enrol(body:EnrolIn,request:Request,db=Depends(get_db,scope='function')):
    item=one(db,'SELECT * FROM invitations WHERE token_hash=:t FOR UPDATE',t=token_hash(body.token))
    if not item or item['accepted_at'] or item['revoked_at'] or item['expires_at']<=utcnow():raise HTTPException(401,'Invitación inválida o vencida')
    if not one(db,'SELECT f.id FROM farms f JOIN owner_accounts a ON a.id=f.account_id WHERE f.id=:f AND f.active AND a.active',f=item['farm_id']):raise HTTPException(403,'La cuenta o el predio no están disponibles')
    target=db.scalar(select(User).where(User.username==item['email']))
    if target:
        from .security import verify_password
        if not target.active or not verify_password(target.password_hash,body.password):raise HTTPException(401,'Usa la contraseña de la cuenta existente para aceptar esta invitación')
        if target.role=='admin':raise HTTPException(403,'La identidad administrativa no se enrola como colaborador')
    else:
        target=User(id=uuid4(),username=item['email'],email=item['email'],full_name=body.full_name,password_hash=hash_password(body.password),role=item['role_code'],farm_id=item['farm_id'],active=True)
        db.add(target);db.flush()
    existing=one(db,'SELECT id FROM farm_memberships WHERE farm_id=:f AND user_id=:u AND valid_to IS NULL',f=item['farm_id'],u=target.id)
    if existing:raise HTTPException(409,'Ya existe una membresía en este predio')
    execute(db,'INSERT INTO farm_memberships(id,farm_id,user_id,role_code,granted_by,valid_from) VALUES(:i,:f,:u,:r,:g,now())',i=uuid4(),f=item['farm_id'],u=target.id,r=item['role_code'],g=item['invited_by'])
    execute(db,'UPDATE invitations SET accepted_at=now(),accepted_user_id=:u WHERE id=:i',u=target.id,i=item['id'])
    audit(db,SimpleNamespace(id=target.id,farm_id=item['farm_id']),'accept_invitation','membership',target.id)
    notify(db,item['farm_id'],item['invited_by'],f'{target.full_name} aceptó la invitación')
    return {'enrolled':True,'username':target.username}
@router.get('/memberships')
def members(request:Request,user=Depends(owner),db=Depends(get_db,scope='function')):
    require_step_up(request)
    return listing(rows(db,"SELECT m.*,u.full_name,u.email,u.username,(m.valid_to IS NULL OR m.valid_to>now()) AND m.valid_from<=now() AS active FROM farm_memberships m JOIN users u ON u.id=m.user_id WHERE m.farm_id=:f ORDER BY m.valid_from DESC LIMIT 100",f=farm_scope(user)))
@router.patch('/memberships/{ident}')
def update_member(ident:UUID,body:MembershipPatch,request:Request,user=Depends(owner),db=Depends(get_db,scope='function')):
    require_operation(request,db,user,body.model_dump(mode='json',exclude_unset=True));member=scoped(db,'farm_memberships',ident,user,True)
    if member['role_code']=='owner' or member['user_id']==user.id:raise HTTPException(403,'Este formulario no modifica al dueño')
    if member['valid_to'] is not None:raise HTTPException(409,'Membresía cerrada; envía una nueva invitación')
    execute(db,'UPDATE farm_memberships SET valid_to=now() WHERE id=:i',i=ident)
    execute(db,'UPDATE trust_grants SET valid_to=now() WHERE membership_id=:i AND valid_to IS NULL',i=ident)
    if body.active is not False:
        new_id=uuid4()
        execute(db,'INSERT INTO farm_memberships(id,farm_id,user_id,role_code,granted_by,valid_from) VALUES(:i,:f,:u,:r,:g,now())',i=new_id,f=member['farm_id'],u=member['user_id'],r=body.role_code or member['role_code'],g=user.id)
    audit(db,user,'membership_update','membership',ident,after=body.model_dump(exclude_unset=True))
    return {'id':ident,'active':body.active is not False}
@router.get('/trust')
def trust(user=Depends(owner),db=Depends(get_db,scope='function')):
    return listing(rows(db,"SELECT t.*,u.full_name,u.email,t.valid_to AS revoked_at FROM trust_grants t JOIN farm_memberships m ON m.id=t.membership_id JOIN users u ON u.id=m.user_id WHERE t.farm_id=:f ORDER BY t.valid_from DESC LIMIT 100",f=farm_scope(user)))
@router.post('/trust',status_code=201)
def grant(body:TrustIn,request:Request,user=Depends(owner),db=Depends(get_db,scope='function')):
    require_operation(request,db,user,body.model_dump(mode='json',exclude_unset=True));member=scoped(db,'farm_memberships',body.membership_id,user,True)
    if member['role_code'] not in ('worker','operator') or member['valid_to'] is not None:raise HTTPException(422,'Selecciona un trabajador con membresía vigente')
    ident=uuid4();execute(db,'INSERT INTO trust_grants(id,farm_id,membership_id,action,granted_by) VALUES(:i,:f,:m,:a,:u)',i=ident,f=user.farm_id,m=body.membership_id,a=body.action,u=user.id)
    audit(db,user,'trust_granted','trust_grant',ident,after=body.model_dump(mode='json'))
    notify(db,user.farm_id,member['user_id'],'Se habilitó aplicación directa para '+body.action)
    return {'id':ident,**body.model_dump()}
@router.delete('/trust/{ident}',status_code=204)
def revoke(ident:UUID,request:Request,user=Depends(owner),db=Depends(get_db,scope='function')):
    require_operation(request,db,user,{});item=scoped(db,'trust_grants',ident,user,True)
    if item['valid_to'] is None:execute(db,'UPDATE trust_grants SET valid_to=now() WHERE id=:i',i=ident)
    audit(db,user,'trust_revoked','trust_grant',ident)


def change_rows(db,user):
    where='r.farm_id=:f'
    args={'f':farm_scope(user)}
    if user.role not in ('owner','admin'):where+=' AND r.requested_by=:u';args['u']=user.id
    return rows(db,"""SELECT r.*,coalesce(nullif(u.full_name,''),u.username) AS requester_name,
      CASE WHEN d.decision='rejected' THEN 'rejected' WHEN x.request_id IS NOT NULL THEN 'applied' ELSE 'pending' END AS status,
      d.decision,d.reason,x.entity_type,x.entity_id,a.diio FROM change_requests r JOIN users u ON u.id=r.requested_by
      LEFT JOIN change_decisions d ON d.request_id=r.id LEFT JOIN change_applications x ON x.request_id=r.id
      LEFT JOIN animals a ON a.id=r.animal_id WHERE """+where+' ORDER BY r.created_at DESC LIMIT 100',**args)
@router.get('/changes')
def changes(user=Depends(current_user),db=Depends(get_db,scope='function')):return listing(change_rows(db,user))

def normalized_payload(action,payload):
    from pydantic import ValidationError
    cls={'animal_profile':TechnicalPayload,'animal_status':StatusPayload,'animal_report':ReportPayload,'battery_replacement':BatteryPayload,'health_record':HealthPayload,'health_schedule':SchedulePayload}[action]
    try:obj=cls.model_validate(payload)
    except ValidationError as error:raise HTTPException(422,'; '.join(e['msg'] for e in error.errors()))
    if isinstance(obj,TechnicalPayload) and not obj.model_fields_set:raise HTTPException(422,'Indica al menos un dato técnico')
    for value in obj.model_dump().values():
        if isinstance(value,datetime) and value.tzinfo is None:raise HTTPException(422,'Las fechas requieren zona horaria')
    if isinstance(obj,TechnicalPayload) and obj.birth_date and obj.birth_date>utcnow().date():raise HTTPException(422,'Nacimiento no puede estar en el futuro')
    if isinstance(obj,HealthPayload):
        if obj.occurred_at and obj.occurred_at>utcnow()+timedelta(minutes=5):raise HTTPException(422,'Un evento ocurrido no puede estar en el futuro')
        for treatment in obj.treatments:
            if treatment.administered_at and (treatment.administered_at.tzinfo is None or treatment.administered_at>utcnow()+timedelta(minutes=5)):raise HTTPException(422,'La administración requiere fecha real con zona')
    return obj.model_dump(mode='json',exclude_unset=True)


def apply_change(db,r,actor,decision,reason=None,trust_id=None):
    # Parent animal lock serializes all clinical/profile updates and optimistic versions.
    animal=None
    if r['animal_id']:
        animal=db.scalar(select(Animal).where(Animal.id==r['animal_id'],Animal.farm_id==r['farm_id']).with_for_update())
        if not animal:raise HTTPException(403,'Animal fuera del predio')
        if r['expected_version'] is not None and animal.version!=r['expected_version']:raise HTTPException(409,'La ficha cambió; reformula o rechaza la solicitud sin sobrescribir datos')
        h=active_holding(db,animal.id,r['farm_id'])
        if h['id']!=r['animal_holding_id']:raise HTTPException(409,'La permanencia cambió desde la propuesta')
    execute(db,'INSERT INTO change_decisions(request_id,decided_by,decision,trust_grant_id,reason) VALUES(:r,:u,:d,:t,:n)',r=r['id'],u=actor.id,d=decision,t=trust_id,n=reason)
    p=r['payload'];entity_id=uuid4();entity_type=r['action']
    common={'i':entity_id,'f':r['farm_id'],'h':r['animal_holding_id'],'a':r['animal_id'],'r':r['id'],'u':r['requested_by']}
    if r['action']=='animal_profile':
        for k in ('breed','color','sex','birth_date'):
            if k in p:
                if k=='sex' and p[k] is None:raise HTTPException(422,'Sexo no puede ser nulo')
                setattr(animal,k,date.fromisoformat(p[k]) if k=='birth_date' and p[k] else p[k])
        if p.get('weight_kg') or p.get('height_cm'):
            execute(db,'INSERT INTO animal_measurements(id,farm_id,animal_holding_id,animal_id,request_id,weight_kg,height_cm) VALUES(:i,:f,:h,:a,:r,:w,:c)',**common,w=p.get('weight_kg'),c=p.get('height_cm'))
        entity_id=animal.id;entity_type='animals'
    elif r['action']=='animal_status':
        animal.status=p['status']
        if p['status'] in ('dead','slaughtered','retired'):
            animal.enabled=False
            execute(db,'UPDATE assignments SET valid_to=now() WHERE animal_id=:a AND valid_to IS NULL',a=animal.id)
            execute(db,'UPDATE pasture_assignments SET valid_to=now() WHERE animal_id=:a AND valid_to IS NULL',a=animal.id)
        elif p['status']=='active':animal.enabled=True
        entity_id=animal.id;entity_type='animals'
    elif r['action']=='animal_report':
        execute(db,'INSERT INTO animal_reports(id,farm_id,animal_holding_id,request_id,description) VALUES(:i,:f,:h,:r,:d)',**common,d=p['description']);entity_type='animal_reports'
    elif r['action']=='battery_replacement':
        scoped(db,'devices',r['device_id'],actor,True)
        execute(db,"INSERT INTO maintenance(id,farm_id,device_id,request_id,responsible_id,kind,battery_id,result,at) VALUES(:i,:f,:d,:r,:u,'replacement',:b,:n,now())",**common,d=r['device_id'],b=p.get('battery_id'),n=p['result']);entity_type='maintenance'
    elif r['action']=='health_record':
        target=p.get('target_event_id');occurred=p.get('occurred_at') or utcnow().isoformat()
        at=datetime.fromisoformat(occurred)
        h=one(db,'SELECT * FROM animal_holdings WHERE id=:i',i=r['animal_holding_id'])
        if at<h['valid_from'] or h['valid_to'] and at>=h['valid_to']:raise HTTPException(422,'Evento fuera de la permanencia del animal')
        if target:
            old=one(db,'SELECT * FROM health_events WHERE id=:i AND farm_id=:f AND animal_holding_id=:h FOR UPDATE',i=target,f=r['farm_id'],h=r['animal_holding_id'])
            if not old or one(db,'SELECT id FROM health_events WHERE target_event_id=:i',i=target):raise HTTPException(409,'Evento original ajeno o ya sustituido')
            author_member=one(db,'SELECT role_code FROM farm_memberships WHERE id=:i',i=r['membership_id']) if r['membership_id'] else None
            if author_member and author_member['role_code'] in ('worker','operator') and (old['event_type'] not in ('vaccination','antibiotic','observation') or old['recorded_by']!=r['requested_by']):raise HTTPException(403,'El trabajador solo puede corregir sus propios reportes sanitarios permitidos')
            if old['operation']=='void':raise HTTPException(409,'No se corrige una anulación; crea un registro documentado nuevo')
        execute(db,'INSERT INTO health_events(id,farm_id,animal_holding_id,request_id,event_type,operation,target_event_id,occurred_at,recorded_by,description,diagnosis) VALUES(:i,:f,:h,:r,:e,:o,:t,:at,:u,:d,:diag)',**common,e=p['event_type'],o=p.get('operation','record'),t=target,at=at,d=p['description'],diag=p.get('diagnosis'))
        for treatment in p.get('treatments',[]):
            execute(db,'INSERT INTO health_treatments(id,farm_id,health_event_id,product_name,product_registration,batch_number,dose_value,dose_unit,route,administered_at,withdrawal_meat_until,withdrawal_milk_until,withdrawal_basis) VALUES(:i,:f,:e,:n,:reg,:b,:d,:unit,:route,:at,:meat,:milk,:basis)',i=uuid4(),f=r['farm_id'],e=entity_id,n=treatment['product_name'],reg=treatment.get('product_registration'),b=treatment.get('batch_number'),d=treatment['dose_value'],unit=treatment['dose_unit'],route=treatment['route'],at=datetime.fromisoformat(treatment['administered_at']) if treatment.get('administered_at') else at,meat=date.fromisoformat(treatment['withdrawal_meat_until']) if treatment.get('withdrawal_meat_until') else None,milk=date.fromisoformat(treatment['withdrawal_milk_until']) if treatment.get('withdrawal_milk_until') else None,basis=treatment.get('withdrawal_basis'))
        entity_type='health_events'
    elif r['action']=='health_schedule':
        target=p.get('target_schedule_id');completed=p.get('completed_event_id')
        if target:
            old=one(db,'SELECT * FROM health_schedules WHERE id=:i AND farm_id=:f AND animal_holding_id=:h FOR UPDATE',i=target,f=r['farm_id'],h=r['animal_holding_id'])
            if not old or one(db,'SELECT id FROM health_schedules WHERE target_schedule_id=:i',i=target):raise HTTPException(409,'Plan ajeno o ya sustituido')
        if completed and not one(db,"SELECT id FROM health_events e WHERE e.id=:i AND e.animal_holding_id=:h AND e.operation<>'void' AND NOT EXISTS(SELECT 1 FROM health_events n WHERE n.target_event_id=e.id)",i=completed,h=r['animal_holding_id']):raise HTTPException(422,'Selecciona evento efectivo del mismo animal')
        execute(db,'INSERT INTO health_schedules(id,farm_id,animal_holding_id,request_id,kind,description,due_at,operation,target_schedule_id,completed_event_id,created_by) VALUES(:i,:f,:h,:r,:k,:d,:at,:o,:t,:e,:u)',**common,k=p['kind'],d=p['description'],at=datetime.fromisoformat(p['due_at']),o=p.get('operation','plan'),t=target,e=completed)
        entity_type='health_schedules'
    if animal:animal.version+=1;db.flush()
    execute(db,'INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES(:r,:k,:i)',r=r['id'],k=entity_type,i=entity_id)
    audit(db,actor,'change_applied',entity_type,entity_id,after={'request_id':str(r['id']),'action':r['action'],'decision':decision})
    recipient=owner_id(db,r['farm_id'])
    if recipient:notify(db,r['farm_id'],recipient,'Cambio aplicado: '+r['action'],r['id'])
    if recipient!=r['requested_by']:notify(db,r['farm_id'],r['requested_by'],'Tu solicitud fue aplicada',r['id'])
    return {'id':r['id'],'status':'applied','decision':decision,'entity_id':entity_id,'entity_type':entity_type}

@router.post('/changes',status_code=201)
def submit(body:ChangeIn,user=Depends(current_user),db=Depends(get_db,scope='function')):
    farm_id=farm_scope(user)
    if user.role not in ('admin','owner','worker','veterinarian'):raise HTTPException(403,'Sin permiso para proponer cambios')
    allowed={'worker':{'animal_status','animal_report','health_record','battery_replacement'},'veterinarian':{'animal_profile','health_record','health_schedule'}}
    if user.role in allowed and body.action not in allowed[user.role]:raise HTTPException(403,'Acción no permitida para tu perfil')
    p=normalized_payload(body.action,body.payload)
    if user.role=='worker' and body.action=='health_record':
        if p['event_type'] not in ('vaccination','antibiotic','observation'):raise HTTPException(403,'El trabajador reporta hechos administrados; diagnósticos requieren veterinario')
        if p.get('diagnosis'):raise HTTPException(403,'El trabajador no registra diagnósticos')
    old=one(db,'SELECT * FROM change_requests WHERE requested_by=:u AND idempotency_key=:k FOR UPDATE',u=user.id,k=body.idempotency_key)
    if old:
        if old['farm_id']!=farm_id or old['action']!=body.action or old['payload']!=p or old['animal_id']!=body.animal_id or old['device_id']!=body.device_id:raise HTTPException(409,'La clave de idempotencia ya representa otra operación')
        item=one(db,'SELECT decision FROM change_decisions WHERE request_id=:r',r=old['id'])
        return {'id':old['id'],'status':'rejected' if item and item['decision']=='rejected' else 'applied' if item else 'pending'}
    holding=None;animal=None
    if body.action=='battery_replacement':
        if not body.device_id:raise HTTPException(422,'Selecciona módulo')
        scoped(db,'devices',body.device_id,user,True)
    else:
        if not body.animal_id:raise HTTPException(422,'Selecciona bovino')
        animal=db.scalar(select(Animal).where(Animal.id==body.animal_id,Animal.farm_id==farm_id).with_for_update())
        if not animal:raise HTTPException(403,'Animal no autorizado')
        holding=active_holding(db,body.animal_id,farm_id)
        if body.expected_version is None:raise HTTPException(422,'Incluye expected_version de la ficha para evitar sobrescrituras')
        if body.expected_version!=animal.version:raise HTTPException(409,'Versión obsoleta; recarga la ficha')
    if user.role=='worker' and body.action=='health_record' and p.get('target_event_id'):
        original=one(db,'SELECT * FROM health_events WHERE id=:i AND animal_holding_id=:h AND farm_id=:f',i=p['target_event_id'],h=holding['id'],f=farm_id)
        if not original or original['event_type'] not in ('vaccination','antibiotic','observation') or original['recorded_by']!=user.id:raise HTTPException(403,'El trabajador solo puede corregir sus propios reportes sanitarios permitidos')
    m=membership(db,user) if user.role not in ('owner','admin') else None
    if user.role not in ('owner','admin') and not m:raise HTTPException(403,'Membresía no vigente')
    ident=uuid4()
    execute(db,'INSERT INTO change_requests(id,farm_id,requested_by,membership_id,action,animal_holding_id,animal_id,device_id,expected_version,payload,idempotency_key) VALUES(:i,:f,:u,:m,:a,:h,:animal,:d,:v,CAST(:p AS jsonb),:k)',i=ident,f=farm_id,u=user.id,m=m['id'] if m else None,a=body.action,h=holding['id'] if holding else None,animal=body.animal_id if holding else None,d=body.device_id,v=body.expected_version,p=json.dumps(p),k=body.idempotency_key)
    r=one(db,'SELECT * FROM change_requests WHERE id=:i',i=ident)
    trust=None
    if user.role=='worker':trust=one(db,'SELECT * FROM trust_grants WHERE membership_id=:m AND action=:a AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now()) FOR UPDATE',m=m['id'],a=body.action)
    if user.role in ('admin','owner','veterinarian') or trust:return apply_change(db,r,user,'direct',trust_id=trust['id'] if trust else None)
    recipient=owner_id(db,farm_id)
    if recipient:notify(db,farm_id,recipient,'Solicitud pendiente: '+body.action,ident)
    audit(db,user,'change_submitted','change_request',ident,after={'action':body.action})
    return {'id':ident,'status':'pending'}
@router.post('/changes/{ident}/decision')
def decide(ident:UUID,body:DecisionIn,user=Depends(owner),db=Depends(get_db,scope='function')):
    r=scoped(db,'change_requests',ident,user,True)
    existing=one(db,'SELECT * FROM change_decisions WHERE request_id=:r',r=ident)
    if existing:
        if existing['decision']!=body.decision:raise HTTPException(409,'La solicitud ya tiene otra decisión')
        return {'id':ident,'status':'rejected' if existing['decision']=='rejected' else 'applied','decision':existing['decision']}
    if body.decision=='approved':
        author=one(db,'SELECT active FROM users WHERE id=:u',u=r['requested_by'])
        if not author or not author['active']:raise HTTPException(409,'El solicitante fue desactivado; rechaza o regulariza la solicitud')
        if r['membership_id'] and not one(db,'SELECT id FROM farm_memberships WHERE id=:i AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now())',i=r['membership_id']):raise HTTPException(409,'La membresía del solicitante ya no está vigente')
        return apply_change(db,r,user,'approved',body.reason)
    if not body.reason or not body.reason.strip():raise HTTPException(422,'Rechazar requiere motivo')
    execute(db,"INSERT INTO change_decisions(request_id,decided_by,decision,reason) VALUES(:r,:u,'rejected',:n)",r=ident,u=user.id,n=body.reason)
    notify(db,r['farm_id'],r['requested_by'],'Solicitud rechazada: '+body.reason,ident)
    audit(db,user,'change_rejected','change_request',ident,after={'reason':body.reason})
    return {'id':ident,'status':'rejected'}

@router.get('/animals/{ident}/record')
def record(ident:UUID,user=Depends(current_user),db=Depends(get_db,scope='function')):
    a=scoped(db,'animals',ident,user)
    h=rows(db,'SELECT id FROM animal_holdings WHERE animal_id=:a AND farm_id=:f',a=ident,f=user.farm_id)
    ids=[x['id'] for x in h]
    if not ids:return {'animal':a,'health_events':[],'treatments':[],'schedules':[],'measurements':[],'reports':[],'pending':[]}
    events=rows(db,"SELECT e.*,coalesce(nullif(u.full_name,''),u.username) AS author_name,NOT EXISTS(SELECT 1 FROM health_events n WHERE n.target_event_id=e.id) AND e.operation<>'void' AS effective FROM health_events e JOIN users u ON u.id=e.recorded_by WHERE e.animal_holding_id=ANY(:ids) ORDER BY e.occurred_at DESC LIMIT 100",ids=ids)
    treatments=rows(db,'SELECT t.* FROM health_treatments t JOIN health_events e ON e.id=t.health_event_id WHERE e.animal_holding_id=ANY(:ids) ORDER BY t.administered_at DESC LIMIT 200',ids=ids)
    for event in events:event['treatments']=[t for t in treatments if t['health_event_id']==event['id']]
    schedules=rows(db,'SELECT s.*,NOT EXISTS(SELECT 1 FROM health_schedules n WHERE n.target_schedule_id=s.id) AND s.operation IN (\'plan\',\'replace\') AS effective FROM health_schedules s WHERE s.animal_holding_id=ANY(:ids) ORDER BY effective DESC,due_at LIMIT 100',ids=ids)
    pending=rows(db,"SELECT r.id,r.action,r.payload,r.created_at FROM change_requests r WHERE r.animal_id=:a AND r.farm_id=:f AND NOT EXISTS(SELECT 1 FROM change_decisions d WHERE d.request_id=r.id) ORDER BY r.created_at DESC LIMIT 100",a=ident,f=user.farm_id)
    return {'animal':a,'health_events':events,'treatments':treatments,'schedules':schedules,
      'measurements':rows(db,'SELECT * FROM animal_measurements WHERE animal_holding_id=ANY(:ids) ORDER BY measured_at DESC LIMIT 100',ids=ids),
      'reports':rows(db,'SELECT * FROM animal_reports WHERE animal_holding_id=ANY(:ids) ORDER BY occurred_at DESC LIMIT 100',ids=ids),'pending':pending,
      'pending_health_warning':any(x['action']=='health_record' for x in pending)}
@router.get('/gateways')
def gateways(user=Depends(current_user),db=Depends(get_db,scope='function')):
    return listing(rows(db,'SELECT id,farm_id,gateway_eui,name,status,last_seen_at,ST_X(position) AS longitude,ST_Y(position) AS latitude FROM gateways WHERE farm_id=:f ORDER BY name',f=farm_scope(user)))
@router.post('/gateways',status_code=201)
def create_gateway(body:GatewayIn,user=Depends(owner),db=Depends(get_db,scope='function')):
    ident=uuid4()
    execute(db,"INSERT INTO gateways(id,farm_id,gateway_eui,name,position,status,installed_at) VALUES(:i,:f,:e,:n,CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL ELSE ST_SetSRID(ST_Point(CAST(:lon AS double precision),CAST(:lat AS double precision)),4326) END,'installed',now())",i=ident,f=farm_scope(user),e=body.gateway_eui.lower(),n=body.name,lon=body.longitude,lat=body.latitude)
    audit(db,user,'create','gateway',ident,after=body.model_dump())
    return {'id':ident,**body.model_dump(),'status':'installed'}
@router.patch('/gateways/{ident}')
def update_gateway(ident:UUID,body:GatewayPatch,user=Depends(owner),db=Depends(get_db,scope='function')):
    scoped(db,'gateways',ident,user,True)
    for k,v in body.model_dump(exclude_unset=True).items():
        if v is None:raise HTTPException(422,'Nombre y estado no pueden ser nulos')
        execute(db,f'UPDATE gateways SET {k}=:v WHERE id=:i',v=v,i=ident)
    audit(db,user,'update','gateway',ident,after=body.model_dump(exclude_unset=True))
    return scoped(db,'gateways',ident,user)
@router.get('/notifications')
def notifications(user=Depends(current_user),db=Depends(get_db,scope='function')):
    return listing(rows(db,"SELECT id,message,channel,status,read_at,created_at,request_id,schedule_id FROM notifications WHERE recipient_id=:u AND farm_id=:f ORDER BY created_at DESC LIMIT 100",u=user.id,f=farm_scope(user)))
@router.post('/notifications/{ident}/read')
def read_notification(ident:UUID,user=Depends(current_user),db=Depends(get_db,scope='function')):
    result=execute(db,"UPDATE notifications SET status='read',read_at=now() WHERE id=:i AND recipient_id=:u AND farm_id=:f",i=ident,u=user.id,f=farm_scope(user))
    if result.rowcount!=1:raise HTTPException(403,'Notificación no autorizada')
    return {'read':True}


def queue_health_reminders(db):
    """Persist one reminder per owner and effective due plan, without fabricating administration."""
    if not db.scalar(text('SELECT pg_try_advisory_xact_lock(804193814)')):return
    execute(db,"""INSERT INTO notifications(id,farm_id,recipient_id,schedule_id,channel,status,message,next_attempt_at,created_at)
      SELECT gen_random_uuid(),s.farm_id,a.owner_user_id,s.id,'in_app','pending','Atención sanitaria próxima o vencida: '||s.description,now(),now()
      FROM effective_health_schedules s JOIN farms f ON f.id=s.farm_id JOIN owner_accounts a ON a.id=f.account_id
      WHERE f.active AND a.active AND s.due_at<=now()+interval '24 hours'
      AND NOT EXISTS(SELECT 1 FROM notifications n WHERE n.schedule_id=s.id AND n.recipient_id=a.owner_user_id AND n.channel='in_app')""")
