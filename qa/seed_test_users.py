#!/usr/bin/env python3
"""Provisiona cuentas QA aisladas usando el runtime/dependencias del backend.

Ejecutar con PYTHONPATH=backend y configuración privada de simulación.
No imprime ni modifica contraseñas existentes; nunca se ejecuta en piloto.
"""
from uuid import uuid4
import os

from sqlalchemy import select
from geocattle.db import SessionLocal
from geocattle.domain import append_audit
from geocattle.models import Farm, LoginSession, RuleSettings, User
from geocattle.security import hash_password
from geocattle.settings import settings


def main():
    cfg = settings()
    if cfg.app_env != "simulation" or not cfg.simulation_enabled:
        raise SystemExit("Fixtures QA requieren simulación explícitamente habilitada")
    if not cfg.demo_password or len(cfg.demo_password) < 12:
        raise SystemExit("Fixtures QA requieren DEMO_PASSWORD privado válido")
    names = {"viewer": "qa-viewer@geocattle.local", "operator": "qa-operator@geocattle.local",
             "other": "qa-other@geocattle.local"}
    with SessionLocal.begin() as db:
        owner = db.scalar(select(User).where(User.username == "demo@geocattle.local"))
        if not owner or db.get(Farm, owner.farm_id).environment != "simulation":
            raise SystemExit("Primero crear predio demo de simulación")
        existing = db.scalar(select(User).where(User.username == names["other"]))
        if existing:
            other_farm = db.get(Farm, existing.farm_id)
            if other_farm.environment != "simulation" or other_farm.id == owner.farm_id:
                raise SystemExit("Fixture otro predio incompatible; se conserva sin modificación")
        else:
            other_farm = Farm(id=uuid4(), name="QA aislamiento · Datos simulados", environment="simulation")
            db.add(other_farm)
            db.flush()
            db.add(RuleSettings(farm_id=other_farm.id))
        for role, name in names.items():
            if db.scalar(select(User).where(User.username == name)):
                continue
            user = User(id=uuid4(), username=name, farm_id=other_farm.id if role == "other" else owner.farm_id,
                        role="owner" if role == "other" else role, active=True,
                        password_hash=hash_password(cfg.demo_password))
            db.add(user)
            db.flush()
            append_audit(db, user.farm_id, owner.id, "user", user.id, "qa_fixture",
                         after={"role": user.role, "source": "simulation", "purpose": "SW08"})
        # Optional browser-only fixture: no .env password enters CUA/browser logs.
        browser_password = os.environ.get("QA_BROWSER_PASSWORD")
        if browser_password:
            if len(browser_password) < 12:
                raise SystemExit("QA_BROWSER_PASSWORD requiere al menos 12 caracteres")
            browser_name = "qa-browser@geocattle.local"
            browser = db.scalar(select(User).where(User.username == browser_name))
            if browser:
                if browser.farm_id != owner.farm_id or browser.role != "owner":
                    raise SystemExit("Fixture browser incompatible; se conserva sin cambios")
                # Existing password and active state are always preserved.
            else:
                browser = User(id=uuid4(), username=browser_name, farm_id=owner.farm_id,
                               role="owner", active=True, password_hash=hash_password(browser_password))
                db.add(browser)
                db.flush()
                append_audit(db, owner.farm_id, owner.id, "user", browser.id, "qa_browser_fixture",
                             after={"role": "owner", "source": "simulation", "purpose": "browser QA"})
    for role, name in names.items():
        print(f"SMOKE_{role.upper()}_USERNAME={name}")
    if os.environ.get("QA_BROWSER_PASSWORD"):
        print("Fixture browser: qa-browser@geocattle.local; contraseña sólo del entorno QA temporal")


def revoke_browser():
    """Revoca la cuenta temporal y sus sesiones, preservando datos y auditoría."""
    cfg = settings()
    if cfg.app_env != "simulation" or not cfg.simulation_enabled:
        raise SystemExit("Revocación QA requiere simulación explícitamente habilitada")
    with SessionLocal.begin() as db:
        owner = db.scalar(select(User).where(User.username == "demo@geocattle.local"))
        browser = db.scalar(select(User).where(User.username == "qa-browser@geocattle.local"))
        if not browser:
            print("No existe fixture browser; sin cambios")
            return
        if not owner or browser.farm_id != owner.farm_id or db.get(Farm, browser.farm_id).environment != "simulation":
            raise SystemExit("Fixture browser incompatible; se conserva sin cambios")
        before = browser.active
        browser.active = False
        for session in db.scalars(select(LoginSession).where(LoginSession.user_id == browser.id)):
            db.delete(session)
        append_audit(db, browser.farm_id, owner.id, "user", browser.id, "qa_browser_revoke",
                     before={"active": before}, after={"active": False, "source": "simulation"})
    print("Fixture browser desactivada y sesiones revocadas; auditoría conservada")


if __name__ == "__main__":
    main()
