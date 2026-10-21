"""Credential changes, closure requests and assisted recovery without external mail."""
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from .db import get_db
from .models import Farm, LoginSession, User, utcnow
from .security import current_user, hash_password, token_hash, verify_password
from .settings import settings
from .v3_auth import issue_session
from .v3_security import audit, check_code, create_challenge, execute, one


router = APIRouter(prefix='/api/v1/auth', tags=['Account and recovery V3'])
_unknown_attempts = defaultdict(deque)
_dummy_hash = hash_password(secrets.token_urlsafe(32))


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Reauthenticate(Strict):
    password: str = Field(min_length=1, max_length=256, repr=False)
    code: str | None = Field(default=None, pattern=r'^[0-9]{6}$', repr=False)


class PasswordChange(Strict):
    current_password: str = Field(min_length=1, max_length=256, repr=False)
    new_password: str = Field(min_length=12, max_length=256, repr=False)
    code: str | None = Field(default=None, pattern=r'^[0-9]{6}$', repr=False)


class CloseRequest(Reauthenticate):
    reason: str = Field(min_length=1, max_length=2000)


class ResetIssue(Reauthenticate):
    user_id: UUID


class ResetConsume(Strict):
    token: str = Field(min_length=20, max_length=200, repr=False)
    new_password: str = Field(min_length=12, max_length=256, repr=False)


class RecoveryLogin(Strict):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256, repr=False)
    recovery_code: str = Field(min_length=20, max_length=64, repr=False)


def _reauthenticate(db, request, actor, password, code, require_mfa=False):
    """Persistent identity budget; lock order matches all other MFA endpoints."""
    one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=actor.id)
    identity = db.get(User, actor.id)
    if not identity or not identity.active:
        raise HTTPException(401, 'Cuenta no disponible')
    db.refresh(identity)
    if not identity.active:
        raise HTTPException(401, 'Cuenta no disponible')
    failures = one(db, """SELECT count(*) AS n FROM auth_challenges WHERE user_id=:u
        AND purpose='step_up' AND created_at>now()-interval '5 minutes'
        AND verified_at IS NULL""", u=identity.id)['n']
    if failures >= 5:
        raise HTTPException(429, 'Demasiados intentos; espera cinco minutos')
    factor = one(db, """SELECT * FROM mfa_factors WHERE user_id=:u
        AND verified_at IS NOT NULL AND revoked_at IS NULL
        ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", u=identity.id)
    if require_mfa and not factor:
        raise HTTPException(409, 'Activa MFA antes de administrar recuperación de credenciales')
    marker = create_challenge(db, identity, 'step_up', session_hash=request.state.session.token_hash)
    hashed = token_hash(marker['challenge_token'])
    execute(db, 'UPDATE auth_challenges SET attempts=1 WHERE token_hash=:t', t=hashed)
    try:
        if not verify_password(identity.password_hash, password):
            raise HTTPException(401, 'Credencial inválida')
        if factor:
            if code is None:
                raise HTTPException(401, 'Se requiere el código TOTP vigente')
            check_code(db, factor, code)
    except HTTPException:
        db.commit()
        raise
    execute(db, 'UPDATE auth_challenges SET verified_at=now(),consumed_at=now() WHERE token_hash=:t', t=hashed)
    return identity


def _clear_cookie(response):
    response.delete_cookie('geocattle_session', path='/', httponly=True,
        secure=settings().cookie_secure, samesite='lax')


def _revoke_sessions(db, identity):
    # Synchronize any identity-map sessions too; authentication must observe
    # revocation immediately even when a caller reuses a unit of work.
    db.execute(update(LoginSession).where(LoginSession.user_id == identity.id,
        LoginSession.revoked_at.is_(None)).values(revoked_at=utcnow())
        .execution_options(synchronize_session='fetch'))


@router.post('/password/change')
def change_password(body: PasswordChange, request: Request, response: Response,
        user=Depends(current_user), db=Depends(get_db, scope='function')):
    identity = _reauthenticate(db, request, user, body.current_password, body.code)
    identity.password_hash = hash_password(body.new_password)
    identity.version += 1
    identity.updated_at = utcnow()
    _revoke_sessions(db, identity)
    execute(db, "UPDATE account_tokens SET consumed_at=now() WHERE user_id=:u AND purpose='reset_password' AND consumed_at IS NULL", u=identity.id)
    audit(db, user, 'password_changed', 'user', identity.id, after={'all_sessions_revoked': True})
    _clear_cookie(response)
    return {'changed': True, 'reauthentication_required': True}


@router.post('/account/close-request', status_code=201)
def request_closure(body: CloseRequest, request: Request, user=Depends(current_user), db=Depends(get_db, scope='function')):
    identity = _reauthenticate(db, request, user, body.password, body.code)
    pending = one(db, """SELECT id FROM account_tokens WHERE user_id=:u AND purpose='close_account'
        AND consumed_at IS NULL AND expires_at>now() ORDER BY created_at DESC LIMIT 1""", u=identity.id)
    ident = pending['id'] if pending else uuid4()
    if not pending:
        execute(db, """INSERT INTO account_tokens(id,user_id,purpose,token_hash,expires_at)
            VALUES(:i,:u,'close_account',:t,now()+interval '30 days')""",
            i=ident, u=identity.id, t=token_hash(secrets.token_urlsafe(40)))
    audit(db, user, 'account_closure_requested', 'account_request', ident,
        after={'reason': body.reason, 'status': 'pending_review', 'data_preserved': True})
    return {'requested': True, 'request_id': ident, 'status': 'pending_review'}


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
    # Unknown identities also have a bounded password-verification workload.
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
    failures = one(db, """SELECT coalesce(sum(attempts),0) AS n FROM auth_challenges WHERE user_id=:u
        AND purpose IN ('login','mfa_setup') AND created_at>now()-interval '5 minutes'
        AND verified_at IS NULL""", u=identity.id)['n']
    if failures >= 5:
        raise HTTPException(429, 'Demasiados intentos MFA; espera cinco minutos')
    marker = create_challenge(db, identity, 'login')
    hashed = token_hash(marker['challenge_token'])
    execute(db, 'UPDATE auth_challenges SET attempts=1 WHERE token_hash=:t', t=hashed)
    factor = one(db, """SELECT id FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL
        AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", u=identity.id)
    code_hash = _code_hash(body.recovery_code)
    record = one(db, 'SELECT * FROM mfa_recovery_codes WHERE user_id=:u AND code_hash=:h AND used_at IS NULL FOR UPDATE',
        u=identity.id, h=code_hash) if code_hash else None
    if not verify_password(identity.password_hash, body.password) or not identity.active or not factor or not record:
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
    # Two administrators resetting each other acquire both identities in one
    # deterministic order, before either authentication factor is locked.
    for ident in sorted({user.id, body.user_id}, key=str):
        one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=ident)
    _reauthenticate(db, request, user, body.password, body.code, require_mfa=True)
    # The consumer also locks the target user before its token, avoiding races.
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
    _revoke_sessions(db, identity)
    execute(db, "UPDATE account_tokens SET consumed_at=now() WHERE user_id=:u AND purpose='reset_password' AND consumed_at IS NULL", u=identity.id)
    audit(db, identity, 'password_reset_completed', 'user', identity.id,
        after={'all_sessions_revoked': True, 'mfa_preserved': True})
    _clear_cookie(response)
    return {'changed': True, 'reauthentication_required': True}
