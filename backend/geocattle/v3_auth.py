"""Inscripción MFA ligada a sesión, verificación de acceso, contexto y elevación de privilegio."""
from datetime import timedelta
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from .db import get_db
from .models import User,LoginSession,utcnow
from .mirror_policy import WRITE_DENIED
from .security import admin_login_requires_mfa, check_session_csrf, current_user,create_session,token_hash,verify_password
from .settings import settings
from .v3_security import (
    MFA_CHALLENGE_PURPOSES, actor_for, audit, check_code, create_challenge, execute,
    live_mfa_session, lock_factor_clause, lock_identity, mfa_challenge_budget, one, retire_mfa_access, user_json,
)
router=APIRouter(prefix='/api/v1/auth',tags=['Identity V3'])
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class VerifyIn(Strict):
    challenge_token:str=Field(min_length=20,max_length=200,repr=False)
    code:str=Field(min_length=6,max_length=6,repr=False)
class PasswordIn(Strict):password:str=Field(min_length=1,max_length=256,repr=False)
class StepIn(PasswordIn):code:str=Field(min_length=6,max_length=6,repr=False)
class ContextIn(Strict):farm_id:UUID|None


def audit_context(actor):
    if actor.farm_id:
        farm = next(f for f in actor.farms if f['id'] == actor.farm_id)
        return {'scope': 'farm', 'farm_id': actor.farm_id, 'farm_name': farm['name'], 'role': actor.role}
    return {'scope': 'platform' if actor.base_role == 'admin' else 'account', 'role': actor.role}


def issue_session(db,user,response,mfa=False):
    token,session=create_session(db,user)
    if mfa:session.mfa_verified_at=utcnow();session.step_up_at=utcnow()
    actor=actor_for(db,user,session)
    if not actor.farms and user.role not in ('admin','owner'):
        raise HTTPException(403,'No tienes una membresía vigente; contacta al dueño')
    response.set_cookie('geocattle_session',token,httponly=True,secure=settings().cookie_secure,samesite='lax',max_age=settings().session_hours*3600,path='/')
    audit(db,actor,'login','session',user.id,
          after={'status': 'active', 'mfa_verified': mfa, **audit_context(actor)})
    return {'user':user_json(actor),'csrf_token':session.csrf_token}


@router.post('/mfa/verify')
def verify(body:VerifyIn,request:Request,response:Response,db=Depends(get_db,scope='function')):
    hashed = token_hash(body.challenge_token)
    pending = one(db, 'SELECT user_id FROM auth_challenges WHERE token_hash=:t', t=hashed)
    if not pending:
        raise HTTPException(401,'Desafío inválido o vencido')
    lock_identity(db, pending['user_id'])
    challenge = one(db, 'SELECT * FROM auth_challenges WHERE token_hash=:t FOR UPDATE', t=hashed)
    if (not challenge or challenge['purpose'] not in MFA_CHALLENGE_PURPOSES or not challenge['factor_id']
            or challenge['consumed_at'] or challenge['expires_at']<=utcnow() or challenge['attempts']>=5):
        raise HTTPException(401,'Desafío inválido o vencido')
    if mfa_challenge_budget(db, challenge['user_id'])['failed'] >= 5:
        raise HTTPException(429,'Demasiados intentos MFA; espera cinco minutos')
    user=db.get(User,challenge['user_id'])
    if not user or not user.active:raise HTTPException(401,'Cuenta no disponible')
    purpose = challenge['purpose']
    if settings().mirror_mode == 'replica' and (purpose != 'login' or user.mfa_enrollment_required):
        raise HTTPException(403, WRITE_DENIED)
    session_hash = challenge['session_token_hash']
    session = None
    if session_hash:
        cookie = request.cookies.get('geocattle_session', '')
        if token_hash(cookie) != session_hash or not live_mfa_session(db, user.id, session_hash):
            raise HTTPException(401,'El desafío pertenece a otra sesión')
        session = db.get(LoginSession, session_hash)
        if user.mfa_enrollment_required or (user.role == 'admin' and session.mfa_verified_at is None and admin_login_requires_mfa(request)):
            raise HTTPException(401, 'Se requiere MFA para administrador')
        check_session_csrf(request, session)
    elif purpose == 'mfa_replace':
        raise HTTPException(401,'El desafío pertenece a otra sesión')
    execute(db,'UPDATE auth_challenges SET attempts=attempts+1 WHERE id=:i',i=challenge['id'])
    factor=one(db, """SELECT * FROM mfa_factors WHERE id=:f AND user_id=:u AND kind='totp'
        AND revoked_at IS NULL AND (verified_at IS NOT NULL)=:verified""" + lock_factor_clause(),
        u=user.id,f=challenge['factor_id'],verified=purpose=='login')
    try:
        if not factor:
            raise HTTPException(401,'Factor no disponible')
        check_code(db,factor,body.code)
    except HTTPException:
        db.commit() # Failed-attempt budget must survive the HTTP error transaction.
        raise
    execute(db,'UPDATE auth_challenges SET consumed_at=now(),verified_at=now() WHERE id=:i',i=challenge['id'])
    if purpose == 'mfa_replace':
        retire_mfa_access(db, user.id, keep_factor=factor['id'], keep_session=session_hash)
    if purpose == 'mfa_setup':
        user.mfa_enrollment_required = False
    if session:
        session.mfa_verified_at=utcnow();session.step_up_at=utcnow()
        actor=actor_for(db,user,session)
        if purpose == 'mfa_replace':
            audit(db,actor,'mfa_replaced','security',after={'mfa_enabled': True, 'other_sessions_revoked': True})
        else:
            audit(db,actor,'mfa_enrolled','security',after={'mfa_enabled': True})
        return {'user':user_json(actor),'csrf_token':session.csrf_token}
    return issue_session(db,user,response,mfa=True)


@router.post('/mfa/setup')
def setup(body:PasswordIn,request:Request,user=Depends(current_user),db=Depends(get_db,scope='function')):
    one(db,'SELECT id FROM users WHERE id=:u FOR UPDATE',u=user.id)
    identity=db.get(User,user.id)
    db.refresh(identity)
    session_hash = request.state.session.token_hash
    if not identity.active or not live_mfa_session(db, user.id, session_hash):
        raise HTTPException(401,'Sesión requerida')
    if not verify_password(identity.password_hash,body.password):raise HTTPException(401,'Credencial inválida')
    if one(db,'SELECT id FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL',u=user.id):
        raise HTTPException(409,'MFA ya está activado; usa la doble verificación')
    return create_challenge(db,identity,'mfa_setup',session_hash=session_hash,setup=True)


@router.post('/step-up')
def stepup(body:StepIn,request:Request,user=Depends(current_user),db=Depends(get_db,scope='function')):
    lock_identity(db, user.id)
    identity=db.get(User,user.id)
    if not live_mfa_session(db, user.id, request.state.session.token_hash):
        raise HTTPException(401, 'Sesión requerida')
    factor=one(db,'SELECT * FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL' + lock_factor_clause(),u=user.id)
    if not factor:raise HTTPException(409,'Activa MFA en tu perfil antes de administrar colaboradores')
    # Persistent session-wide attempts, successful login alone never sets step-up.
    failures=one(db,"SELECT count(*) AS n FROM auth_challenges WHERE user_id=:u AND purpose='step_up' AND created_at>now()-interval '5 minutes' AND verified_at IS NULL",u=user.id)['n']
    if failures>=5:raise HTTPException(429,'Demasiados intentos; espera cinco minutos')
    marker=create_challenge(db,identity,'step_up',session_hash=request.state.session.token_hash)
    try:
        if not verify_password(identity.password_hash,body.password):raise HTTPException(401,'Credencial inválida')
        check_code(db,factor,body.code)
    except HTTPException:
        db.commit();raise
    execute(db,'UPDATE auth_challenges SET consumed_at=now(),verified_at=now() WHERE token_hash=:t',t=token_hash(marker['challenge_token']))
    request.state.session.step_up_at=utcnow();audit(db,user,'step_up','security',after={'verified': True})
    return {'verified':True,'expires_at':utcnow()+timedelta(minutes=10)}


@router.post('/context')
def context(body:ContextIn,request:Request,user=Depends(current_user),db=Depends(get_db,scope='function')):
    if body.farm_id is None and user.base_role!='admin':raise HTTPException(403,'Solo administrador puede usar contexto global')
    if body.farm_id is not None and str(body.farm_id) not in {str(f['id']) for f in user.farms}:raise HTTPException(403,'Predio no autorizado')
    request.state.session.active_farm_id=body.farm_id
    actor=actor_for(db,db.get(User,user.id),request.state.session)
    audit(db,actor,'select_context','farm' if body.farm_id else 'platform',body.farm_id,
          before=audit_context(user),after=audit_context(actor))
    return {'user':user_json(actor),'csrf_token':request.state.session.csrf_token}
