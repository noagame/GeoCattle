"""Provision a real empty farm and administrator; never imports synthetic data."""
import argparse
import os
from uuid import uuid4
from sqlalchemy import select
from .db import SessionLocal
from .models import Farm, RuleSettings, User
from .security import hash_password
from .settings import settings

def bootstrap(username,farm_name,password):
    if len(password)<12:raise ValueError("ADMIN_PASSWORD requiere al menos 12 caracteres")
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.username==username.lower())):raise ValueError("Cuenta ya existente; no se cambió la contraseña")
        farm=Farm(id=uuid4(),name=farm_name,environment=settings().app_env);db.add(farm);db.flush()
        user=User(id=uuid4(),farm_id=farm.id,username=username.lower(),password_hash=hash_password(password),role="owner",active=True)
        db.add(user);db.add(RuleSettings(farm_id=farm.id));db.flush()
        print(f"Predio vacío creado: {farm.id}. Usuario: {username.lower()}")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username",required=True);parser.add_argument("--farm",required=True)
    args=parser.parse_args()
    password=os.environ.get("ADMIN_PASSWORD","")
    if not password:parser.error("Defina ADMIN_PASSWORD; no se muestran ni conservan contraseñas en logs")
    bootstrap(args.username,args.farm,password)
if __name__=="__main__":main()
