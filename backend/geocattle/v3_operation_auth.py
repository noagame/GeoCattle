"""One-use MFA authorization bound to an exact team-management operation."""
import hashlib
import hmac
import json
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .db import get_db
from .models import User, utcnow
from .security import current_user, token_hash, verify_password
from .v3_security import audit, check_code, create_challenge, execute, one


router = APIRouter(prefix='/api/v1/auth', tags=['Operation authorization V3'])
_PREFIX = '/api/v1/v3/'
_ITEM = re.compile(r'^/api/v1/v3/(memberships|trust)/([0-9a-fA-F-]{36})$')


def validate_target(method, path):
    """Only the four supported writes can receive an authorization token."""
    if (method, path) in (('POST', _PREFIX + 'invitations'), ('POST', _PREFIX + 'trust')):
        return
    match = _ITEM.fullmatch(path)
    if match:
        try:
            UUID(match[2])
        except ValueError:
            pass
        else:
            if (match[1], method) in (('memberships', 'PATCH'), ('trust', 'DELETE')):
                return
    raise HTTPException(422, 'La doble verificación solo autoriza una operación de equipo o confianza admitida')


def operation_digest(method, path, payload, farm_id):
    """Stable JSON also binds the operation to the selected tenant context."""
    try:
        canonical = json.dumps(
            {'method': method, 'path': path, 'payload': payload, 'farm_id': str(farm_id)},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError):
        raise HTTPException(422, 'La operación requiere un objeto JSON válido')
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


class OperationIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(pattern=r'^[0-9]{6}$')
    method: Literal['POST', 'PATCH', 'DELETE']
    path: str = Field(min_length=1, max_length=200)
    payload: dict

    @field_validator('method', mode='before')
    @classmethod
    def uppercase(cls, value):
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode='after')
    def target(self):
        validate_target(self.method, self.path)
        if self.method == 'DELETE' and self.payload:
            raise ValueError('Revocar confianza no admite campos adicionales')
        return self


@router.post('/operation')
def authorize_operation(body: OperationIn, request: Request, user=Depends(current_user), db=Depends(get_db, scope='function')):
    if user.role not in ('owner', 'admin'):
        raise HTTPException(403, 'Solo el dueño o administrador puede autorizar esta operación')
    if not user.farm_id:
        raise HTTPException(409, 'Selecciona un predio autorizado antes de administrar el equipo')
    # All MFA flows use user -> factor to serialize the identity-wide budget.
    one(db, 'SELECT id FROM users WHERE id=:u FOR UPDATE', u=user.id)
    identity = db.get(User, user.id)
    if not identity or not identity.active:
        raise HTTPException(401, 'Cuenta no disponible')
    failures = one(db, """SELECT count(*) AS n FROM auth_challenges
        WHERE user_id=:u AND purpose='step_up' AND created_at>now()-interval '5 minutes'
        AND verified_at IS NULL""", u=user.id)['n']
    if failures >= 5:
        raise HTTPException(429, 'Demasiados intentos; espera cinco minutos')
    factor = one(db, """SELECT * FROM mfa_factors WHERE user_id=:u
        AND verified_at IS NOT NULL AND revoked_at IS NULL
        ORDER BY created_at DESC LIMIT 1 FOR UPDATE""", u=user.id)
    if not factor:
        raise HTTPException(409, 'Activa MFA en tu perfil antes de administrar colaboradores')
    digest = operation_digest(body.method, body.path, body.payload, user.farm_id)
    marker = create_challenge(db, identity, 'step_up', session_hash=request.state.session.token_hash)
    hashed_token = token_hash(marker['challenge_token'])
    execute(db, 'UPDATE auth_challenges SET attempts=1,operation_digest=:d WHERE token_hash=:t', d=digest, t=hashed_token)
    try:
        if not verify_password(identity.password_hash, body.password):
            raise HTTPException(401, 'Credencial inválida')
        check_code(db, factor, body.code)
    except HTTPException:
        # Persist the failed attempt while leaving the challenge unverified.
        db.commit()
        raise
    execute(db, 'UPDATE auth_challenges SET verified_at=now() WHERE token_hash=:t', t=hashed_token)
    challenge = one(db, 'SELECT id,expires_at FROM auth_challenges WHERE token_hash=:t', t=hashed_token)
    audit(db, user, 'operation_verified', 'security', challenge['id'], after={'method': body.method, 'path': body.path, 'operation_digest': digest})
    return {'operation_token': marker['challenge_token'], 'expires_at': challenge['expires_at']}


def require_operation(request, db, user, payload: dict):
    """Consume only in the protected write's transaction; rollback restores it."""
    token = request.headers.get('X-Operation-Token', '')
    if user.role not in ('owner', 'admin') or not user.farm_id or not token or len(token) > 200:
        raise HTTPException(403, 'Verifica tu identidad para confirmar esta operación exacta')
    session = request.state.session
    if session.user_id != user.id or session.revoked_at or session.expires_at <= utcnow():
        raise HTTPException(403, 'La autorización requiere una sesión vigente')
    method, path = request.method.upper(), request.url.path
    validate_target(method, path)
    challenge = one(db, 'SELECT * FROM auth_challenges WHERE token_hash=:t FOR UPDATE', t=token_hash(token))
    expected = operation_digest(method, path, payload, user.farm_id)
    if (not challenge or challenge['purpose'] != 'step_up' or challenge['user_id'] != user.id
            or challenge['session_token_hash'] != session.token_hash or not challenge['verified_at']
            or challenge['consumed_at'] or challenge['expires_at'] <= utcnow()
            or not challenge['operation_digest'] or not hmac.compare_digest(challenge['operation_digest'], expected)):
        raise HTTPException(403, 'La doble verificación no corresponde a esta operación, venció o ya fue utilizada')
    execute(db, 'UPDATE auth_challenges SET consumed_at=now() WHERE id=:i', i=challenge['id'])
