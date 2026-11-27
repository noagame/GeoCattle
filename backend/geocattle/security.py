import hashlib
import hmac
import secrets
from datetime import timedelta
from types import SimpleNamespace
from fastapi import Depends, HTTPException, Request
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from sqlalchemy import select
from .db import get_db
from .mirror_replay import replay_for
from .models import LoginSession, User, utcnow
from .settings import settings
hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
def hash_password(password): return hasher.hash(password)
def verify_password(encoded,password):
    try: return hasher.verify(encoded,password)
    except (VerifyMismatchError,InvalidHashError,VerificationError): return False
def token_hash(token): return hmac.new(settings().session_secret.encode(),token.encode(),hashlib.sha256).hexdigest()
def create_session(db,user):
    token=secrets.token_urlsafe(48)
    session=LoginSession(token_hash=token_hash(token),user_id=user.id,active_farm_id=user.farm_id,authenticated_at=utcnow(),last_seen_at=utcnow(),csrf_token=secrets.token_urlsafe(32),expires_at=utcnow()+timedelta(hours=settings().session_hours))
    db.add(session)
    return token,session

def admin_login_requires_mfa(request: Request) -> bool:
    """Permite sesiones de administrador solo con contraseña en la aplicación nativa de loopback habilitada."""
    config = settings()
    if config.admin_login_requires_mfa:
        return True
    if not config.local_admin_password_only:
        return False
    return not (
        getattr(request.app.state, "native_local_app", False)
        and request.client is not None
        and request.client.host in {"127.0.0.1", "::1"}
    )


def check_session_csrf(request, session):
    if not matches_secret_header(request, "X-CSRF-Token", session.csrf_token):
        raise HTTPException(403, "Token CSRF inválido")
    origin = request.headers.get("origin")
    allowed = {s.strip() for s in settings().allowed_origins.split(",") if s.strip()}
    if origin and origin not in allowed:
        raise HTTPException(403, "Origen no autorizado")


def current_user(request: Request,db=Depends(get_db, scope="function")):
    replay = replay_for(request)
    if replay is not None:
        from .mirror_policy import WRITE_DENIED, kind_enabled
        from .v3_security import actor_for, one
        if settings().mirror_mode != 'field' or not kind_enabled(replay.kind):
            raise HTTPException(403, WRITE_DENIED)
        user = db.get(User, replay.actor_id, with_for_update=True)
        if not user or not user.active or user.mfa_enrollment_required:
            raise HTTPException(403, 'Cuenta no disponible en el PC del campo')
        actor = actor_for(db, user, SimpleNamespace(active_farm_id=replay.farm_id))
        if replay.kind != 'support_request':
            if (actor.farm_id != replay.farm_id
                    or (replay.kind == 'admin_order' and actor.base_role != 'admin')
                    or (replay.kind != 'admin_order' and (not actor.farm_id or actor.role != 'veterinarian'))):
                raise HTTPException(403, 'El actor ya no tiene el rol o el predio requerido')
            if replay.kind != 'admin_order' and not one(db, """SELECT id FROM farm_memberships
                WHERE user_id=:u AND farm_id=:f AND role_code='veterinarian' AND valid_from<=now()
                  AND (valid_to IS NULL OR valid_to>now()) FOR SHARE""", u=user.id, f=actor.farm_id):
                raise HTTPException(403, 'Membresía no vigente')
        request.state.identity = user
        request.state.actor = actor
        return actor
    token=request.cookies.get("geocattle_session")
    session=db.get(LoginSession,token_hash(token)) if token else None
    if not session or session.revoked_at is not None or session.expires_at<=utcnow() or (session.last_seen_at and utcnow()-session.last_seen_at>timedelta(minutes=30)): raise HTTPException(401,"Sesión requerida")
    user=db.get(User,session.user_id)
    if not user or not user.active: raise HTTPException(401,"Sesión requerida")
    if user.mfa_enrollment_required:
        raise HTTPException(401, "Se requiere inscribir un autenticador")
    if user.role == 'admin' and session.mfa_verified_at is None and admin_login_requires_mfa(request):
        raise HTTPException(401, "Se requiere MFA para administrador")
    request.state.identity=user
    request.state.session=session
    if request.url.path not in ('/api/v1/v3/activity-counts', '/api/v1/mirror/info'):
        session.last_seen_at=utcnow()
    if request.method not in ("GET","HEAD","OPTIONS"):
        check_session_csrf(request, session)
    from .v3_security import actor_for
    actor=actor_for(db,user,session)
    request.state.actor=actor
    return actor

def owner(user=Depends(current_user)):
    if user.role not in ("owner","admin"): raise HTTPException(403,"Se requiere perfil propietario")
    return user

def operator(user=Depends(current_user)):
    if user.role not in ("owner","admin","operator","worker","veterinarian"): raise HTTPException(403,"Sin permiso de escritura")
    return user

def matches_secret_header(request: Request, name: str, expected: str) -> bool:
    # ASGI exposes header bytes through Starlette's Latin-1 decoding.
    supplied = request.headers.get(name, "").encode("latin-1")
    return hmac.compare_digest(supplied, expected.encode("utf-8"))


def service_auth(request:Request):
    if not matches_secret_header(request, "X-Ingest-Key", settings().ingest_key):
        raise HTTPException(401, "Credencial de ingestión inválida")
