"""Conciliar datos V1 y, de forma explícita, provisionar el primer administrador V3.

No cambia contraseñas existentes, no crea colaboradores ficticios ni envía correo.
Uso: python -m geocattle.seed_v3 [--admin-email correo --admin-name nombre]
La contraseña nueva se toma únicamente de V3_ADMIN_PASSWORD.
"""
import argparse
import os
from uuid import uuid4
from sqlalchemy import text
from .db import SessionLocal
from .security import hash_password


def reconcile_legacy(db):
    """Backfill idempotente para seed/bootstrap V1 ejecutados después de 003."""
    db.execute(text("SELECT pg_advisory_xact_lock(804193814)"))
    if not db.scalar(text("SELECT 1 FROM schema_migrations WHERE version='003_application_v3.sql'")):
        raise RuntimeError("Ejecute geocattle.migrate antes de conciliar V3")
    db.execute(text("""UPDATE users u SET email=lower(btrim(username))
      WHERE email IS NULL AND position('@' in username)>1
      AND NOT EXISTS(SELECT 1 FROM users o WHERE o.id<>u.id AND
       (o.email=lower(btrim(u.username)) OR lower(btrim(o.username))=lower(btrim(u.username))))"""))
    db.execute(text("UPDATE users SET full_name=username WHERE full_name=''"))
    db.execute(text("""INSERT INTO owner_accounts(owner_user_id,display_name,max_farms,active)
      SELECT id,coalesce(nullif(full_name,''),username),1,active FROM users WHERE role='owner'
      ON CONFLICT(owner_user_id) DO NOTHING"""))
    db.execute(text("""UPDATE farms f SET account_id=(
      SELECT a.id FROM owner_accounts a JOIN users u ON u.id=a.owner_user_id
      WHERE u.farm_id=f.id ORDER BY u.username,u.id LIMIT 1)
      WHERE f.account_id IS NULL AND EXISTS(SELECT 1 FROM users u WHERE u.farm_id=f.id AND u.role='owner')"""))
    db.execute(text("""INSERT INTO farm_memberships(farm_id,user_id,role_code,granted_by,valid_from)
      SELECT u.farm_id,u.id,CASE WHEN u.role='operator' THEN 'worker' ELSE u.role END,
             coalesce(a.owner_user_id,u.id),u.created_at
      FROM users u JOIN farms f ON f.id=u.farm_id LEFT JOIN owner_accounts a ON a.id=f.account_id
      WHERE u.role IN ('owner','operator','worker','viewer','veterinarian')
      AND NOT EXISTS(SELECT 1 FROM farm_memberships m WHERE m.user_id=u.id AND m.farm_id=u.farm_id)"""))
    db.execute(text("""INSERT INTO animal_holdings(farm_id,animal_id,valid_from,reason)
      SELECT a.farm_id,a.id,least(a.created_at,
        coalesce((SELECT min(x.valid_from) FROM assignments x WHERE x.animal_id=a.id),a.created_at),
        coalesce((SELECT min(x.valid_from) FROM pasture_assignments x WHERE x.animal_id=a.id),a.created_at),
        coalesce((SELECT min(t.observed_at) FROM telemetry t WHERE t.animal_id=a.id),a.created_at)),
        'legacy_reconciliation'
      FROM animals a WHERE NOT EXISTS(SELECT 1 FROM animal_holdings h WHERE h.animal_id=a.id)"""))
    db.execute(text("""UPDATE assignments a SET animal_holding_id=h.id FROM animal_holdings h
      WHERE a.animal_holding_id IS NULL AND h.animal_id=a.animal_id AND h.farm_id=a.farm_id
      AND tstzrange(a.valid_from,a.valid_to,'[)') <@ tstzrange(h.valid_from,h.valid_to,'[)')"""))
    db.execute(text("""UPDATE pasture_assignments a SET animal_holding_id=h.id FROM animal_holdings h
      WHERE a.animal_holding_id IS NULL AND h.animal_id=a.animal_id AND h.farm_id=a.farm_id
      AND tstzrange(a.valid_from,a.valid_to,'[)') <@ tstzrange(h.valid_from,h.valid_to,'[)')"""))
    db.execute(text("""INSERT INTO farm_features(farm_id,feature_code)
      SELECT f.id,c.code FROM farms f CROSS JOIN features c WHERE c.code<>'fma' ON CONFLICT DO NOTHING"""))
    return dict(db.execute(text("""SELECT
      (SELECT count(*) FROM owner_accounts) AS owner_accounts,
      (SELECT count(*) FROM farm_memberships) AS memberships,
      (SELECT count(*) FROM animal_holdings) AS animal_holdings,
      (SELECT count(*) FROM farms WHERE account_id IS NULL) AS farms_pending_owner""")).mappings().one())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-email")
    parser.add_argument("--admin-name", default="Administrador de plataforma")
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        counts = reconcile_legacy(db)
        if args.admin_email:
            email = args.admin_email.strip().lower()
            if "@" not in email or len(email) > 254:
                parser.error("El administrador requiere correo válido")
            existing = db.execute(text("SELECT id,role FROM users WHERE username=:email OR email=:email"), {"email": email}).mappings().first()
            if existing:
                if existing["role"] != "admin":
                    parser.error("La cuenta existe con otro rol; no se elevó su acceso")
                print("El administrador ya existe; no se alteró contraseña ni MFA")
            else:
                password = os.environ.get("V3_ADMIN_PASSWORD", "")
                if len(password) < 12:
                    parser.error("Defina V3_ADMIN_PASSWORD único de al menos 12 caracteres")
                user_id = uuid4()
                db.execute(text("""INSERT INTO users(id,farm_id,username,email,password_hash,role,active,full_name)
                  VALUES(:id,NULL,:email,:email,:password_hash,'admin',true,:name)"""),
                  {"id":user_id,"email":email,"password_hash":hash_password(password),"name":args.admin_name})
                db.execute(text("INSERT INTO platform_admins(user_id) VALUES(:id)"), {"id":user_id})
                db.execute(text("""INSERT INTO audit_log(id,actor_id,actor_kind,object_type,object_id,action,at,after)
                  VALUES(:id,:actor,'user','user',:object_id,'admin_bootstrap',now(),CAST(:after AS jsonb))"""),
                  {"id":uuid4(),"actor":user_id,"object_id":str(user_id),"after":'{"role":"admin","mfa_setup_required":true}'})
                print("Administrador creado; debe completar enrolamiento MFA para acceder al panel")
        print("Conciliación V3:", counts)


if __name__ == "__main__":
    main()
