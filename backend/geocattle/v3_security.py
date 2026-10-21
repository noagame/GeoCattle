"""V3 identity, tenant context and TOTP. No caller-supplied actor is trusted."""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select, text
from .models import User, Farm, utcnow
from .settings import settings


def rows(db, sql, **params):
    return [dict(x) for x in db.execute(text(sql), params).mappings()]


def one(db, sql, **params):
    result = rows(db, sql, **params)
    return result[0] if result else None


def execute(db, sql, **params):
    return db.execute(text(sql), params)


def role(code):
    return {'operator': 'worker'}.get(code, code)


def farms_for(db, user):
    if user.role == 'admin':
        return rows(db, "SELECT id,name,'admin' AS role FROM farms WHERE active AND environment=:env ORDER BY name", env=settings().app_env)
    # Bootstrap compatibility: a legacy owner's home farm has not yet been linked.
    if user.role == 'owner' and user.farm_id:
        home = one(db, 'SELECT account_id FROM farms WHERE id=:id', id=user.farm_id)
        if home and home['account_id'] is None:
            account = one(db, 'SELECT id FROM owner_accounts WHERE owner_user_id=:u', u=user.id)
            account_id = account['id'] if account else uuid4()
            if not account:
                execute(db, 'INSERT INTO owner_accounts(id,owner_user_id,display_name,max_farms) VALUES(:i,:u,:n,1)', i=account_id,u=user.id,n=user.full_name or user.username)
            execute(db, 'UPDATE farms SET account_id=:a WHERE id=:f AND account_id IS NULL',a=account_id,f=user.farm_id)
    return rows(db, """SELECT DISTINCT f.id,f.name,
      CASE WHEN a.owner_user_id=:u THEN 'owner' ELSE CASE m.role_code WHEN 'operator' THEN 'worker' ELSE m.role_code END END AS role
      FROM farms f LEFT JOIN owner_accounts a ON a.id=f.account_id
      LEFT JOIN farm_memberships m ON m.farm_id=f.id AND m.user_id=:u
        AND now() >= m.valid_from AND (m.valid_to IS NULL OR now()<m.valid_to)
      WHERE f.active AND f.environment=:env AND (a.id IS NULL OR a.active) AND (a.active AND a.owner_user_id=:u OR m.id IS NOT NULL)
      ORDER BY f.name""",u=user.id,env=settings().app_env)


def actor_for(db, user, session):
    farms = farms_for(db,user)
    available = {str(f['id']): f for f in farms}
    selected = str(session.active_farm_id) if session.active_farm_id else None
    if selected not in available:
        selected = None if user.role=='admin' else str(user.farm_id) if user.farm_id and str(user.farm_id) in available else next(iter(available),None)
        session.active_farm_id = available[selected]['id'] if selected else None
    active_role = 'viewer' if user.role=='viewer' else 'admin' if user.role=='admin' else available[selected]['role'] if selected else role(user.role)
    return SimpleNamespace(id=user.id,username=user.username,email=user.email or user.username,
        full_name=user.full_name or user.username,phone=user.phone,role=active_role,base_role=role(user.role),
        farm_id=available[selected]['id'] if selected else None,active=user.active,farms=farms,
        mfa_enabled=bool(one(db,'SELECT id FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL',u=user.id)))


def user_json(user):
    return {k:getattr(user,k) for k in ('id','username','email','full_name','phone','role','farm_id','farms','mfa_enabled')}


def cipher():
    key = settings().mfa_encryption_key or settings().session_secret
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('geocattle-mfa-v3:'+key).encode()).digest()))


def totp(secret, counter=None):
    counter = int(time.time()//30) if counter is None else counter
    raw = hmac.new(base64.b32decode(secret),struct.pack('>Q',counter),hashlib.sha1).digest()
    offset=raw[-1]&15
    return str((struct.unpack('>I',raw[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)


def check_code(db, factor, code):
    if not isinstance(code,str) or not code.isdigit() or len(code)!=6:
        raise HTTPException(401,'Código de verificación inválido')
    secret=cipher().decrypt(bytes(factor['protected_data'])).decode()
    now_counter=int(time.time()//30)
    used=int(factor['credential_id'] or '-1')
    for counter in (now_counter-1,now_counter,now_counter+1):
        if counter>used and hmac.compare_digest(totp(secret,counter),code):
            execute(db,'UPDATE mfa_factors SET credential_id=:c,verified_at=coalesce(verified_at,now()) WHERE id=:i',c=str(counter),i=factor['id'])
            return
    raise HTTPException(401,'Código inválido, vencido o ya utilizado; espera el siguiente código')


def create_challenge(db,user,purpose,session_hash=None,setup=False):
    from .security import token_hash
    if purpose in ('login','mfa_setup'):
        one(db,'SELECT id FROM users WHERE id=:u FOR UPDATE',u=user.id)
        failed=one(db,"SELECT coalesce(sum(attempts),0) AS n FROM auth_challenges WHERE user_id=:u AND purpose IN ('login','mfa_setup') AND created_at>now()-interval '5 minutes' AND verified_at IS NULL",u=user.id)['n']
        issued=one(db,"SELECT count(*) AS n FROM auth_challenges WHERE user_id=:u AND purpose IN ('login','mfa_setup') AND created_at>now()-interval '5 minutes'",u=user.id)['n']
        if failed>=5 or issued>=10:raise HTTPException(429,'Demasiados intentos MFA; espera cinco minutos')
    token=secrets.token_urlsafe(40)
    execute(db,"INSERT INTO auth_challenges(id,user_id,token_hash,purpose,session_token_hash,expires_at) VALUES(:i,:u,:t,:p,:s,:e)",
        i=uuid4(),u=user.id,t=token_hash(token),p=purpose,s=session_hash,e=utcnow()+timedelta(minutes=5))
    result={'mfa_required':True,'challenge_token':token,'setup_required':setup}
    if setup:
        # A pending factor never authenticates; only the matching OTP activates it.
        secret=base64.b32encode(secrets.token_bytes(20)).decode()
        execute(db,'UPDATE mfa_factors SET revoked_at=now() WHERE user_id=:u AND verified_at IS NULL AND revoked_at IS NULL',u=user.id)
        execute(db,"INSERT INTO mfa_factors(id,user_id,kind,protected_data) VALUES(:i,:u,'totp',:s)",i=uuid4(),u=user.id,s=cipher().encrypt(secret.encode()))
        result.update(secret=secret,otpauth_uri=f'otpauth://totp/GeoCattle:{quote(user.username)}?secret={secret}&issuer=GeoCattle&algorithm=SHA1&digits=6&period=30')
    return result


def require_step_up(request):
    session=request.state.session
    if session.step_up_at is None or utcnow()-session.step_up_at>timedelta(minutes=10):
        raise HTTPException(403,'Se requiere doble verificación reciente para administrar colaboradores o confianza')


def audit(db,user,action,kind,ident=None,before=None,after=None):
    farm_id=getattr(user,'farm_id',None)
    account=one(db,'SELECT account_id FROM farms WHERE id=:f',f=farm_id) if farm_id else None
    execute(db,"""INSERT INTO audit_log(id,farm_id,account_id,actor_id,actor_kind,object_type,object_id,action,at,before,after)
       VALUES(:i,:f,:a,:u,'user',:k,:o,:c,now(),CAST(:b AS jsonb),CAST(:v AS jsonb))""",
       i=uuid4(),f=farm_id,a=account['account_id'] if account else None,u=user.id,k=kind,o=str(ident or user.id),c=action,
       b=json.dumps(before,default=str) if before is not None else None,v=json.dumps(after,default=str) if after is not None else None)
