"""Session-bound MFA enrollment, login verification, context and step-up."""
from datetime import timedelta
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from .db import get_db
from .models import User,LoginSession,utcnow
from .security import current_user,create_session,token_hash,verify_password
from .settings import settings
from .v3_security import one,rows,execute,actor_for,user_json,create_challenge,check_code,audit
router=APIRouter(prefix='/api/v1/auth',tags=['Identity V3'])
class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class VerifyIn(Strict):
    challenge_token:str=Field(min_length=20,max_length=200)
    code:str=Field(min_length=6,max_length=6)
class PasswordIn(Strict):password:str=Field(min_length=1,max_length=256)
class StepIn(PasswordIn):code:str=Field(min_length=6,max_length=6)
class ContextIn(Strict):farm_id:UUID|None


def issue_session(db,user,response,mfa=False):
    token,session=create_session(db,user)
    if mfa:session.mfa_verified_at=utcnow();session.step_up_at=utcnow()
    actor=actor_for(db,user,session)
    if not actor.farms and user.role not in ('admin','owner'):
        raise HTTPException(403,'No tienes una membresía vigente; contacta al dueño')
    response.set_cookie('geocattle_session',token,httponly=True,secure=settings().cookie_secure,samesite='lax',max_age=settings().session_hours*3600,path='/')
    audit(db,actor,'login','session',user.id)
    return {'user':user_json(actor),'csrf_token':session.csrf_token}


@router.post('/mfa/verify')
def verify(body:VerifyIn,request:Request,response:Response,db=Depends(get_db,scope='function')):
    challenge=one(db,'SELECT * FROM auth_challenges WHERE token_hash=:t FOR UPDATE',t=token_hash(body.challenge_token))
    if not challenge or challenge['consumed_at'] or challenge['expires_at']<=utcnow() or challenge['attempts']>=5:
        raise HTTPException(401,'Desafío inválido o vencido')
    one(db,'SELECT id FROM users WHERE id=:u FOR UPDATE',u=challenge['user_id'])
    failures=one(db,"SELECT coalesce(sum(attempts),0) AS n FROM auth_challenges WHERE user_id=:u AND purpose IN ('login','mfa_setup') AND created_at>now()-interval '5 minutes' AND verified_at IS NULL",u=challenge['user_id'])['n']
    if failures>=5:raise HTTPException(429,'Demasiados intentos MFA; espera cinco minutos')
    user=db.get(User,challenge['user_id'])
    if not user or not user.active:raise HTTPException(401,'Cuenta no disponible')
    if challenge['session_token_hash']:
        cookie=request.cookies.get('geocattle_session','')
        session=db.get(LoginSession,token_hash(cookie))
        if not session or session.token_hash!=challenge['session_token_hash'] or session.user_id!=user.id or session.expires_at<=utcnow() or session.revoked_at:
            raise HTTPException(401,'El desafío pertenece a otra sesión')
        if request.headers.get('X-CSRF-Token','')!=session.csrf_token:raise HTTPException(403,'Token CSRF inválido')
    factor=one(db,"SELECT * FROM mfa_factors WHERE user_id=:u AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1 FOR UPDATE",u=user.id)
    if not factor:raise HTTPException(401,'Factor no disponible')
    execute(db,'UPDATE auth_challenges SET attempts=attempts+1 WHERE id=:i',i=challenge['id'])
    try:check_code(db,factor,body.code)
    except HTTPException:
        db.commit() # Failed-attempt budget must survive the HTTP error transaction.
        raise
    execute(db,'UPDATE auth_challenges SET consumed_at=now(),verified_at=now() WHERE id=:i',i=challenge['id'])
    if challenge['session_token_hash']:
        session.mfa_verified_at=utcnow();session.step_up_at=utcnow()
        actor=actor_for(db,user,session);audit(db,actor,'mfa_enrolled','security')
        return {'user':user_json(actor),'csrf_token':session.csrf_token}
    return issue_session(db,user,response,mfa=True)


@router.post('/mfa/setup')
def setup(body:PasswordIn,request:Request,user=Depends(current_user),db=Depends(get_db,scope='function')):
    identity=db.get(User,user.id)
    if not verify_password(identity.password_hash,body.password):raise HTTPException(401,'Credencial inválida')
    if one(db,'SELECT id FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL',u=user.id):
        raise HTTPException(409,'MFA ya está activado; usa la doble verificación')
    return create_challenge(db,identity,'mfa_setup',session_hash=request.state.session.token_hash,setup=True)


@router.post('/step-up')
def stepup(body:StepIn,request:Request,user=Depends(current_user),db=Depends(get_db,scope='function')):
    one(db,'SELECT id FROM users WHERE id=:u FOR UPDATE',u=user.id)
    identity=db.get(User,user.id)
    factor=one(db,'SELECT * FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL FOR UPDATE',u=user.id)
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
    request.state.session.step_up_at=utcnow();audit(db,user,'step_up','security')
    return {'verified':True,'expires_at':utcnow()+timedelta(minutes=10)}


@router.post('/context')
def context(body:ContextIn,request:Request,user=Depends(current_user),db=Depends(get_db,scope='function')):
    if body.farm_id is None and user.base_role!='admin':raise HTTPException(403,'Solo administrador puede usar contexto global')
    if body.farm_id is not None and str(body.farm_id) not in {str(f['id']) for f in user.farms}:raise HTTPException(403,'Predio no autorizado')
    request.state.session.active_farm_id=body.farm_id
    actor=actor_for(db,db.get(User,user.id),request.state.session)
    audit(db,actor,'select_context','farm',body.farm_id)
    return {'user':user_json(actor),'csrf_token':request.state.session.csrf_token}
