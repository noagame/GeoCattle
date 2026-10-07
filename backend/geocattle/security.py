import hashlib
import hmac
import secrets
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from sqlalchemy import select
from .db import get_db
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
    session=LoginSession(token_hash=token_hash(token),user_id=user.id,csrf_token=secrets.token_urlsafe(32),expires_at=utcnow()+timedelta(hours=settings().session_hours))
    db.add(session)
    return token,session

def current_user(request: Request,db=Depends(get_db, scope="function")):
    token=request.cookies.get("geocattle_session")
    session=db.get(LoginSession,token_hash(token)) if token else None
    if not session or session.expires_at<=utcnow(): raise HTTPException(401,"Sesión requerida")
    user=db.get(User,session.user_id)
    if not user or not user.active: raise HTTPException(401,"Sesión requerida")
    request.state.session=session
    if request.method not in ("GET","HEAD","OPTIONS"):
        csrf=request.headers.get("X-CSRF-Token","")
        if not hmac.compare_digest(csrf,session.csrf_token): raise HTTPException(403,"Token CSRF inválido")
        origin=request.headers.get("origin")
        allowed={s.strip() for s in settings().allowed_origins.split(",") if s.strip()}
        if origin and origin not in allowed: raise HTTPException(403,"Origen no autorizado")
    return user

def owner(user=Depends(current_user)):
    if user.role!="owner": raise HTTPException(403,"Se requiere perfil propietario")
    return user

def operator(user=Depends(current_user)):
    if user.role not in ("owner","operator"): raise HTTPException(403,"Sin permiso de escritura")
    return user

def service_auth(request:Request):
    if not hmac.compare_digest(request.headers.get("X-Ingest-Key",""),settings().ingest_key): raise HTTPException(401,"Credencial de ingestión inválida")
