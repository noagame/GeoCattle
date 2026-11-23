"""Seguridad de cuenta, solicitudes de soporte privadas y recuperación asistida."""
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import select

from .db import get_db
from .models import Farm, User, utcnow
from .security import admin_login_requires_mfa, current_user, hash_password, token_hash, verify_password
from .settings import settings
from .v3_auth import issue_session
from .v3_security import (
    audit, check_code, create_challenge, execute, live_mfa_session, mfa_challenge_budget,
    one, retire_mfa_access, revoke_sessions, rows,
)


router = APIRouter(prefix='/api/v1/auth', tags=['Account and recovery V3'])
_unknown_attempts = defaultdict(deque)
_dummy_hash = hash_password(secrets.token_urlsafe(32))


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


SupportText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Reauthenticate(Strict):
    password: str = Field(min_length=1, max_length=256, repr=False)
    code: str | None = Field(default=None, pattern=r'^[0-9]{6}$', repr=False)


class MfaChange(Reauthenticate):
    recovery_code: str | None = Field(default=None, min_length=20, max_length=64, repr=False)

    @model_validator(mode='after')
    def one_factor(self):
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError('Indica el código TOTP o un código de recuperación')
        return self


class PasswordChange(Strict):
    current_password: str = Field(min_length=1, max_length=256, repr=False)
    new_password: str = Field(min_length=12, max_length=256, repr=False)
    code: str | None = Field(default=None, pattern=r'^[0-9]{6}$', repr=False)


class CloseRequest(Reauthenticate):
    reason: SupportText


class SupportRequest(Strict):
    kind: Literal['change_email', 'access_issue']
    description: SupportText


class SupportDecision(Strict):
    status: Literal['resolved', 'rejected']
    response: SupportText


class ResetIssue(Reauthenticate):
    user_id: UUID


class ResetConsume(Strict):
    token: str = Field(min_length=20, max_length=200, repr=False)
    new_password: str = Field(min_length=12, max_length=256, repr=False)


class RecoveryLogin(Strict):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256, repr=False)
    recovery_code: str = Field(min_length=20, max_length=64, repr=False)


def _reauthenticate(db, request, actor, password, code, require_mfa=False, recovery_code=None):
    """Presupuesto de identidad persistente; el orden de bloqueo coincide con todos los demás endpoints MFA."""
    one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=actor.id)
    identity = db.get(User, actor.id)
    if not identity or not identity.active:
        raise HTTPException(401, 'Cuenta no disponible')
    db.refresh(identity)
    session_hash = request.state.session.token_hash
    if not identity.active or identity.mfa_enrollment_required or not live_mfa_session(db, actor.id, session_hash):
        raise HTTPException(401, 'Sesión requerida')
    failures = one(db, """SELECT count(*) AS n FROM auth_challenges WHERE user_id=:u
        AND purpose='step_up' AND created_at>now()-interval '5 minutes'
        AND verified_at IS NULL""", u=identity.id)['n']
    if failures >= 5:
        raise HTTPException(429, 'Demasiados intentos; espera cinco minutos')
    factor = one(db, """SELECT * FROM mfa_factors WHERE user_id=:u
        AND kind='totp' AND verified_at IS NOT NULL AND revoked_at IS NULL
        ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", u=identity.id)
    if require_mfa and not factor:
        raise HTTPException(409, 'Se requiere un autenticador activo para esta operación')
    marker = create_challenge(db, identity, 'step_up', session_hash=session_hash)
    hashed = token_hash(marker['challenge_token'])
    execute(db, 'UPDATE auth_challenges SET attempts=1 WHERE token_hash=:t', t=hashed)
    try:
        if not verify_password(identity.password_hash, password):
            raise HTTPException(401, 'Credencial inválida')
        if factor:
            if recovery_code is not None:
                code_hash = _code_hash(recovery_code)
                consumed = execute(db, """UPDATE mfa_recovery_codes SET used_at=now()
                    WHERE user_id=:u AND code_hash=:h AND used_at IS NULL""",
                    u=identity.id, h=code_hash)
                if consumed.rowcount != 1:
                    raise HTTPException(401, 'Credencial de recuperación inválida')
            elif code is None:
                raise HTTPException(401, 'Se requiere el código TOTP vigente')
            else:
                check_code(db, factor, code)
    except HTTPException:
        db.commit()
        raise
    execute(db, 'UPDATE auth_challenges SET verified_at=now(),consumed_at=now() WHERE token_hash=:t', t=hashed)
    return identity


def _clear_cookie(response):
    response.delete_cookie('geocattle_session', path='/', httponly=True,
        secure=settings().cookie_secure, samesite='lax')


@router.post('/mfa/replace')
def replace_mfa(body: MfaChange, request: Request,
        user=Depends(current_user), db=Depends(get_db, scope='function')):
    identity = _reauthenticate(db, request, user, body.password, body.code,
        require_mfa=True, recovery_code=body.recovery_code)
    return create_challenge(db, identity, 'mfa_replace',
        session_hash=request.state.session.token_hash, setup=True)


@router.post('/mfa/remove')
def remove_mfa(body: MfaChange, request: Request, response: Response,
        user=Depends(current_user), db=Depends(get_db, scope='function')):
    identity = _reauthenticate(db, request, user, body.password, body.code,
        require_mfa=True, recovery_code=body.recovery_code)
    identity.mfa_enrollment_required = identity.role == 'admin' and admin_login_requires_mfa(request)
    retire_mfa_access(db, identity.id)
    audit(db, user, 'mfa_removed', 'security', after={
        'all_sessions_revoked': True, 'enrollment_required': identity.mfa_enrollment_required,
    })
    _clear_cookie(response)
    return {'removed': True, 'enrollment_required': identity.mfa_enrollment_required}


@router.post('/password/change')
def change_password(body: PasswordChange, request: Request, response: Response,
        user=Depends(current_user), db=Depends(get_db, scope='function')):
    identity = _reauthenticate(db, request, user, body.current_password, body.code)
    identity.password_hash = hash_password(body.new_password)
    identity.version += 1
    identity.updated_at = utcnow()
    revoke_sessions(db, identity.id)
    execute(db, "UPDATE account_tokens SET consumed_at=now() WHERE user_id=:u AND purpose='reset_password' AND consumed_at IS NULL", u=identity.id)
    audit(db, user, 'password_changed', 'user', identity.id, after={'all_sessions_revoked': True})
    _clear_cookie(response)
    return {'changed': True, 'reauthentication_required': True}


@router.post('/account/close-request', status_code=201)
def request_closure(body: CloseRequest, request: Request, user=Depends(current_user), db=Depends(get_db, scope='function')):
    identity = _reauthenticate(db, request, user, body.password, body.code)
    pending = one(db, """SELECT id FROM support_requests WHERE requester_id=:u AND kind='close_account'
        AND status='pending' ORDER BY created_at DESC, id DESC LIMIT 1""", u=identity.id)
    ident = pending['id'] if pending else create_support_request(db, user, 'close_account', body.reason)
    return {'requested': True, 'request_id': ident, 'status': 'pending_review'}


def create_support_request(db, user, kind, description):
    ident = uuid4()
    execute(db, """INSERT INTO support_requests(id,requester_id,kind,description)
        VALUES(:i,:u,:k,:d)""", i=ident, u=user.id, k=kind, d=description)
    action = 'account_closure_requested' if kind == 'close_account' else 'support_request_created'
    audit(db, SimpleNamespace(id=user.id), action, 'account_request', ident,
          after={'kind': kind, 'status': 'pending'})
    return ident


def global_support_admin(user):
    if user.base_role != 'admin' or user.farm_id is not None:
        raise HTTPException(403, 'Abre el panel global de administración para gestionar solicitudes')


@router.get('/support-requests')
def support_requests(admin: bool = False, status: Literal['pending', 'resolved', 'rejected'] | None = None,
        limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
        user=Depends(current_user), db=Depends(get_db, scope='function')):
    if admin:
        global_support_admin(user)
    scope = 'true' if admin else 'r.requester_id=:user_id'
    where = ' WHERE ' + scope + (' AND r.status=:status' if status else '')
    params = {'user_id': user.id, 'status': status, 'limit': limit, 'offset': offset}
    items = rows(db, """SELECT r.id,r.kind,r.status,r.description,r.response,r.created_at,r.resolved_at,r.read_at,
        coalesce(nullif(u.full_name,''),u.username) AS requester_name,
        coalesce(u.email,u.username) AS requester_email
        FROM support_requests r JOIN users u ON u.id=r.requester_id""" + where +
        ' ORDER BY r.created_at DESC, r.id DESC LIMIT :limit OFFSET :offset', **params)
    total = one(db, 'SELECT count(*) AS n FROM support_requests r' + where, **params)['n']
    return {'items': items, 'total': total}


@router.post('/support-requests', status_code=201)
def submit_support_request(body: SupportRequest, user=Depends(current_user), db=Depends(get_db, scope='function')):
    ident = create_support_request(db, user, body.kind, body.description)
    return {'request_id': ident, 'status': 'pending'}


@router.post('/support-requests/{ident}/decision')
def decide_support_request(ident: UUID, body: SupportDecision,
        user=Depends(current_user), db=Depends(get_db, scope='function')):
    global_support_admin(user)
    item = one(db, 'SELECT kind,status,response FROM support_requests WHERE id=:i FOR UPDATE', i=ident)
    if not item:
        raise HTTPException(404, 'Solicitud de soporte no encontrada')
    if item['status'] != 'pending':
        if item['status'] != body.status or item['response'] != body.response:
            raise HTTPException(409, 'La solicitud ya fue respondida')
        return {'request_id': ident, 'status': body.status}
    execute(db, """UPDATE support_requests SET status=:s,response=:r,resolved_by=:u,resolved_at=now()
        WHERE id=:i""", i=ident, u=user.id, s=body.status, r=body.response)
    audit(db, user, 'support_request_decided', 'account_request', ident,
          before={'status': 'pending'}, after={'kind': item['kind'], 'status': body.status})
    return {'request_id': ident, 'status': body.status}


@router.post('/support-requests/{ident}/read')
def read_support_response(ident: UUID, user=Depends(current_user), db=Depends(get_db, scope='function')):
    result = execute(db, """UPDATE support_requests SET read_at=coalesce(read_at,now())
        WHERE id=:i AND requester_id=:u AND status<>'pending'""", i=ident, u=user.id)
    if result.rowcount != 1:
        raise HTTPException(404, 'Respuesta no disponible')
    return {'read': True}


def _code_hash(code):
    normalized = code.replace('-', '').replace(' ', '').upper()
    if not re.fullmatch(r'[0-9A-F]{20}', normalized):
        return None
    return token_hash('mfa-recovery:' + normalized)


@router.post('/mfa/recovery-codes')
def recovery_codes(body: Reauthenticate, request: Request, user=Depends(current_user), db=Depends(get_db, scope='function')):
    identity = _reauthenticate(db, request, user, body.password, body.code, require_mfa=True)
    execute(db, 'UPDATE mfa_recovery_codes SET used_at=now() WHERE user_id=:u AND used_at IS NULL', u=identity.id)
    codes = []
    while len(codes) < 8:
        raw = secrets.token_hex(10).upper()
        code = '-'.join(raw[i:i+5] for i in range(0, 20, 5))
        if code not in codes:
            codes.append(code)
    for code in codes:
        execute(db, 'INSERT INTO mfa_recovery_codes(id,user_id,code_hash) VALUES(:i,:u,:h)',
            i=uuid4(), u=identity.id, h=_code_hash(code))
    audit(db, user, 'mfa_recovery_codes_generated', 'security', identity.id,
        after={'count': 8, 'previous_codes_invalidated': True})
    return {'recovery_codes': codes, 'display_once': True}


def _public_origin(request):
    origin = request.headers.get('origin')
    if origin and origin not in {s.strip() for s in settings().allowed_origins.split(',')}:
        raise HTTPException(403, 'Origen no autorizado')


@router.post('/mfa/recovery-login')
def recovery_login(body: RecoveryLogin, request: Request, response: Response, db=Depends(get_db, scope='function')):
    _public_origin(request)
    # Las identidades desconocidas también tienen una carga de verificación de contraseña acotada.
    key = (request.client.host if request.client else 'unknown', body.username.strip().lower())
    attempts = _unknown_attempts[key]
    now = time.monotonic()
    while attempts and attempts[0] < now - 300:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(429, 'Demasiados intentos; espera cinco minutos')
    attempts.append(now)
    identity = db.scalar(select(User).where(User.username == key[1]))
    if not identity:
        verify_password(_dummy_hash, body.password)
        raise HTTPException(401, 'Credenciales de recuperación inválidas')
    one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=identity.id)
    db.refresh(identity)
    if mfa_challenge_budget(db, identity.id)['failed'] >= 5:
        raise HTTPException(429, 'Demasiados intentos MFA; espera cinco minutos')
    marker = create_challenge(db, identity, 'login')
    hashed = token_hash(marker['challenge_token'])
    execute(db, 'UPDATE auth_challenges SET attempts=1 WHERE token_hash=:t', t=hashed)
    factor = one(db, """SELECT id FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL
        AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", u=identity.id)
    code_hash = _code_hash(body.recovery_code)
    record = one(db, 'SELECT * FROM mfa_recovery_codes WHERE user_id=:u AND code_hash=:h AND used_at IS NULL FOR UPDATE',
        u=identity.id, h=code_hash) if code_hash else None
    if (not verify_password(identity.password_hash, body.password) or not identity.active
            or identity.mfa_enrollment_required or not factor or not record):
        db.commit()
        raise HTTPException(401, 'Credenciales de recuperación inválidas')
    home = db.get(Farm, identity.farm_id) if identity.farm_id else None
    if home and home.environment != settings().app_env:
        raise HTTPException(403, 'Cuenta de otro entorno')
    execute(db, 'UPDATE mfa_recovery_codes SET used_at=now() WHERE id=:i', i=record['id'])
    execute(db, 'UPDATE auth_challenges SET verified_at=now(),consumed_at=now() WHERE token_hash=:t', t=hashed)
    result = issue_session(db, identity, response, mfa=True)
    audit(db, request.state.actor if hasattr(request.state, 'actor') else identity,
        'mfa_recovery_login', 'security', identity.id, after={'recovery_code_consumed': True, 'mfa_preserved': True})
    attempts.clear()
    return result


@router.post('/password/reset-issue')
def issue_password_reset(body: ResetIssue, request: Request, user=Depends(current_user), db=Depends(get_db, scope='function')):
    if user.base_role != 'admin':
        raise HTTPException(403, 'Solo el administrador puede emitir recuperación asistida')
    # Dos administradores que se restablecen mutuamente adquieren ambas identidades en un
    # orden determinista, antes de que se bloquee cualquier factor de autenticación.
    for ident in sorted({user.id, body.user_id}, key=str):
        one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=ident)
    _reauthenticate(db, request, user, body.password, body.code, require_mfa=True)
    # El consumidor también bloquea al usuario objetivo antes de su token, evitando condiciones de carrera.
    one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=body.user_id)
    target = db.get(User, body.user_id)
    if not target:
        raise HTTPException(404, 'Usuario no encontrado')
    execute(db, "UPDATE account_tokens SET consumed_at=now() WHERE user_id=:u AND purpose='reset_password' AND consumed_at IS NULL", u=target.id)
    token = secrets.token_urlsafe(40)
    ident, expires = uuid4(), utcnow() + timedelta(minutes=15)
    execute(db, "INSERT INTO account_tokens(id,user_id,purpose,token_hash,expires_at) VALUES(:i,:u,'reset_password',:t,:e)",
        i=ident, u=target.id, t=token_hash(token), e=expires)
    audit(db, user, 'password_reset_issued', 'user', target.id,
        after={'request_id': str(ident), 'expires_at': expires.isoformat(), 'delivery': 'manual'})
    return {'reset_token': token, 'expires_at': expires, 'delivery': 'manual'}


@router.post('/password/reset')
def reset_password(body: ResetConsume, request: Request, response: Response, db=Depends(get_db, scope='function')):
    _public_origin(request)
    hashed = token_hash(body.token)
    candidate = one(db, "SELECT user_id FROM account_tokens WHERE token_hash=:t AND purpose='reset_password'", t=hashed)
    if not candidate:
        raise HTTPException(401, 'Enlace de recuperación inválido o vencido')
    one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=candidate['user_id'])
    token = one(db, "SELECT * FROM account_tokens WHERE token_hash=:t AND purpose='reset_password' FOR UPDATE", t=hashed)
    if not token or token['consumed_at'] or token['expires_at'] <= utcnow():
        raise HTTPException(401, 'Enlace de recuperación inválido o vencido')
    identity = db.get(User, token['user_id'])
    if not identity:
        raise HTTPException(401, 'Enlace de recuperación inválido o vencido')
    identity.password_hash = hash_password(body.new_password)
    identity.version += 1
    identity.updated_at = utcnow()
    revoke_sessions(db, identity.id)
    execute(db, "UPDATE account_tokens SET consumed_at=now() WHERE user_id=:u AND purpose='reset_password' AND consumed_at IS NULL", u=identity.id)
    audit(db, identity, 'password_reset_completed', 'user', identity.id,
        after={'all_sessions_revoked': True, 'mfa_preserved': True})
    _clear_cookie(response)
    return {'changed': True, 'reauthentication_required': True}
