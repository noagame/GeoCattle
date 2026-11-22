#!/usr/bin/env python3
"""Carga un rebaño ficticio de Temuco en la base indicada por --env-file."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from random import Random
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from psycopg.conninfo import make_conninfo
from sqlalchemy import URL, create_engine, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ZONE = ZoneInfo("America/Santiago")
FARM_NAME = "Predio de validación"
FARM_ADDRESS = "Datos de prueba · Temuco, Región de La Araucanía"
NAMESPACE = UUID("fa79781e-a43f-4ac2-9819-1cabdc26796a")
DEFAULT_SEED = 20261122
CATEGORIES = (
    ("Vaca", 14, "female", 1100, 2500),
    ("Vaquilla", 8, "female", 450, 780),
    ("Ternera", 5, "female", 80, 240),
    ("Ternero", 5, "male", 80, 240),
    ("Novillo", 6, "male", 480, 820),
    ("Toro", 2, "male", 1100, 2000),
)
BREEDS = (
    ("Holstein", "Negro y blanco", "milk", "milk"),
    ("Overo Colorado", "Colorado y blanco", "milk", "dual"),
    ("Hereford", "Colorado, cara blanca", "meat", "meat"),
    ("Angus", "Negro", "meat", "meat"),
    ("Clavel Alemán", "Colorado y blanco", "meat", "dual"),
)
COW_NAMES = (
    "Luma", "Quila", "Lluvia", "Canela", "Avellana", "Mora", "Lenga",
    "Rocío", "Queltehue", "Dalia", "Arrayán", "Nalca", "Tepa", "Calafate",
)


class SeedError(Exception):
    pass


@dataclass(frozen=True)
class Bovine:
    id: UUID
    diio: str
    name: str
    category: str
    sex: str
    birth_date: date
    breed: str
    color: str
    orientation: str
    production_type: str
    mother: Bovine | None


@dataclass(frozen=True)
class Entry:
    action: str
    payload: dict
    occurred_at: datetime | None = None


def local_time(day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour), ZONE)


def build_herd(farm_id: UUID, seed: int, today: date) -> list[Bovine]:
    rng = Random(seed)
    herd_id = uuid5(farm_id, str(seed))
    series = herd_id.int % 10**8
    herd: list[Bovine] = []
    for category, count, sex, min_age, max_age in CATEGORIES:
        for offset in range(count):
            index = len(herd)
            mother = None
            if category in ("Ternera", "Ternero"):
                mother = herd[offset + (5 if category == "Ternero" else 0)]
            breed, color, orientation, production = BREEDS[index % len(BREEDS)]
            if mother:
                breed, color, orientation, production = (
                    mother.breed, mother.color, mother.orientation, mother.production_type,
                )
            herd.append(Bovine(
                id=uuid5(herd_id, f"animal:{index}"),
                diio=f"VAL-09-{series:08d}{index + 1:02d}",
                name=COW_NAMES[offset] if category == "Vaca" else f"{category} {offset + 1:02d}",
                category=category, sex=sex,
                birth_date=today - timedelta(days=rng.randint(min_age, max_age)),
                breed=breed, color=color, orientation=orientation,
                production_type=production, mother=mother,
            ))
    return herd


def health_entry(animal: Bovine, event_type: str, description: str, occurred_at: datetime,
                 product: tuple[str, str, int, int] | None = None,
                 diagnosis: str | None = None) -> Entry:
    payload = {
        "event_type": event_type, "description": description,
        "occurred_at": occurred_at, "diagnosis": diagnosis,
    }
    if product:
        name, route, meat_days, milk_days = product
        day = occurred_at.date()
        payload["treatments"] = [{
            "product_name": f"{name} de prueba",
            "product_registration": f"SIM-{event_type.upper()}",
            "batch_number": f"SIM-{event_type[:3].upper()}-{day:%Y%m}",
            "dose_value": 2 if event_type == "vaccination" else 5,
            "dose_unit": "mL",
            "route": route,
            "administered_at": occurred_at,
            "withdrawal_meat_until": day + timedelta(days=meat_days),
            "withdrawal_milk_until": (
                day + timedelta(days=milk_days)
                if animal.category == "Vaca" and animal.orientation == "milk" else None
            ),
            "withdrawal_basis": "Ficha ficticia para validación",
        }]
    return Entry("health_record", payload)


def animal_history(animal: Bovine, index: int, herd: list[Bovine], today: date) -> list[Entry]:
    def past(days_ago: int, minimum_age: int) -> datetime:
        return local_time(max(today - timedelta(days=days_ago), animal.birth_date + timedelta(days=minimum_age)))

    entries: list[Entry] = []
    # Modela ganancia en animales jóvenes y variaciones moderadas en adultos.
    for weight_index, days_ago in enumerate((510, 285, 30)):
        measured_at = past(days_ago - index % 9, (12, 35, 55)[weight_index])
        age = (measured_at.date() - animal.birth_date).days
        adult_weight = 810 if animal.category == "Toro" else 590 if animal.category == "Vaca" else 515
        weight = min(adult_weight + (index % 9 - 4) * 5, 37 + age * 0.69)
        entries.append(Entry("animal_profile", {
            "weight_kg": round(weight + (2, -2, 4)[weight_index], 1),
            "height_cm": round(min(141 if animal.sex == "male" else 135, 72 + age * 0.085), 1),
        }, measured_at))

    entries.extend((
        health_entry(animal, "vaccination", "Jornada de vacunación clostridial del lote.",
                     past(320 - index % 12, 42), ("Vacuna clostridial", "Subcutánea", 0, 0)),
        health_entry(animal, "procedure", "Control antiparasitario según plan del lote.",
                     past(118 - index % 17, 57), ("Antiparasitario", "Oral", 14, 3)),
    ))
    if index % 5 == 0:
        entries.append(health_entry(
            animal, "antibiotic", "Tratamiento individual registrado tras examen veterinario.",
            past(55 - index % 8, 60), ("Antibiótico", "Intramuscular", 21, 5),
            diagnosis="Infección respiratoria individual",
        ))
    if index % 5 == 1:
        entries.append(health_entry(
            animal, "examination", "Control clínico del lote, apetito y condición corporal normales.",
            past(64 - index % 11, 59),
        ))

    description = (
        f"{animal.category}. Recorrido por la pradera de ballica y trébol. "
        + ("Buena aceptación del suplemento de heno." if index % 2 else "Se verificó consumo de agua en el bebedero.")
    )
    if animal.mother:
        description += f" Se observó la cría con su madre {animal.mother.name} ({animal.mother.diio})."
    entries.append(Entry("animal_report", {"description": description}, past(14 - index % 7, 65)))
    for calf in herd:
        if calf.mother is animal:
            entries.append(Entry("animal_report", {
                "description": f"Parto observado. Cría {calf.name} ({calf.diio}), con toma de calostro.",
            }, local_time(calf.birth_date, 12)))

    vaccination_due = index % 3 == 0
    entries.append(Entry("health_schedule", {
        "kind": "vaccination" if vaccination_due else "checkup",
        "description": "Refuerzo clostridial del lote." if vaccination_due else "Control de condición corporal y revisión clínica.",
        "due_at": local_time(today + timedelta(days=14 + index % 27)),
    }))
    return entries


def read_configuration(path: Path) -> URL:
    if not path.is_file():
        raise SeedError("No se encontró el archivo privado indicado en --env-file.")
    private = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8-sig").splitlines()
                   if "=" in line and not line.lstrip().startswith("#"))
    required = ("APP_ENV", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "DB_PORT")
    if not all(private.get(key) for key in required):
        raise SeedError("El archivo privado debe definir APP_ENV, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB y DB_PORT.")
    url = URL.create("postgresql+psycopg", username=private["POSTGRES_USER"],
                     password=private["POSTGRES_PASSWORD"], host="127.0.0.1",
                     port=int(private["DB_PORT"]), database=private["POSTGRES_DB"])
    os.environ.update(private)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    return url


def backup_database(url: URL) -> Path:
    bundled = ROOT / ".runtime" / "postgres16" / "pgsql" / "bin" / "pg_dump.exe"
    executable = str(bundled) if os.name == "nt" and bundled.is_file() else shutil.which("pg_dump")
    if not executable:
        raise SeedError("Instala pg_dump de la misma versión principal del servidor o una más reciente.")
    folder = ROOT / "backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(ZONE).strftime("%Y%m%d-%H%M%S")
    target = folder / f"geocattle-validacion-{stamp}-{uuid4().hex[:8]}.dump"
    partial = target.with_suffix(".part")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    env.update(PGPASSWORD=url.password, PGCONNECT_TIMEOUT="8")
    target_dsn = make_conninfo(host=url.host, port=url.port, user=url.username, dbname=url.database)
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            subprocess.run(
                [executable, "--no-password", "--format=custom", "--dbname", target_dsn],
                env=env, stdout=stream, check=True,
            )
        if partial.stat().st_size == 0:
            raise SeedError("pg_dump produjo un archivo vacío.")
        partial.rename(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def resolve_actor(db: Session, email: str, dry_run: bool):
    from geocattle.models import User

    email = email.strip().lower()
    query = select(User).where(User.active, or_(
        User.email == email,
        (User.email.is_(None) & (func.lower(User.username) == email)),
    ))
    matches = db.scalars(query if dry_run else query.with_for_update()).all()
    if len(matches) != 1 or matches[0].role not in ("owner", "admin"):
        raise SeedError("Indica el correo inequívoco de un dueño o administrador activo.")
    return matches[0]


def resolve_destination(db: Session, actor, environment: str, farm_id: UUID | None, dry_run: bool):
    from geocattle.models import Farm, OwnerAccount

    own_farm_id = uuid5(NAMESPACE, f"{environment}:{actor.id}")
    target_id = farm_id or own_farm_id
    farm = db.get(Farm, target_id, with_for_update=not dry_run)
    account = None
    if actor.role == "owner":
        query = select(OwnerAccount).where(OwnerAccount.owner_user_id == actor.id)
        account = db.scalar(query if dry_run else query.with_for_update())
        if account and not account.active:
            raise SeedError("La cuenta dueña está inactiva.")
    if farm_id or farm:
        if not farm or not farm.active or farm.environment != environment:
            raise SeedError("El destino debe ser un predio activo del entorno seleccionado.")
        if actor.role == "owner" and (not account or farm.account_id != account.id):
            raise SeedError("El actor no es dueño del predio de destino.")
        if not farm_id and farm.address != FARM_ADDRESS:
            raise SeedError("El predio reservado carece de la marca de validación. Revisa el destino.")
    return target_id, farm, account


def owner_capacity(db: Session, user, account) -> int:
    """Reserve the home farm's slot before V3 links a legacy owner account."""
    from geocattle.models import Farm

    home = db.get(Farm, user.farm_id) if user.farm_id else None
    unlinked_home = int(bool(home and home.active and home.account_id is None))
    if account is None:
        return 1 + unlinked_home
    active_count = db.scalar(select(func.count()).select_from(Farm).where(
        Farm.account_id == account.id, Farm.active,
    ))
    if active_count + unlinked_home >= account.max_farms:
        raise SeedError("La cuenta dueña alcanzó el cupo de predios. Usa un dueño con cupo o un administrador.")
    return account.max_farms


def create_validation_farm(db: Session, user, actor, environment: str, account, max_farms: int | None) -> None:
    from geocattle.models import Farm, OwnerAccount, RuleSettings
    from geocattle.v3_security import audit, execute

    if max_farms is not None and account is None:
        account = OwnerAccount(owner_user_id=user.id, display_name=user.full_name or user.username,
                               max_farms=max_farms)
        db.add(account)
        db.flush()
        audit(db, user, "create", "owner_account", account.id, after={"source": "seed_validation_data"})

    farm = Farm(id=actor.farm_id, name=FARM_NAME, environment=environment,
                account_id=account.id if account else None, address=FARM_ADDRESS,
                region="La Araucanía", commune="Temuco", timezone=ZONE.key)
    db.add(farm)
    db.flush()
    db.add(RuleSettings(farm_id=farm.id))
    execute(db, "INSERT INTO farm_features(farm_id,feature_code) SELECT :f,code FROM features WHERE code<>'fma'", f=farm.id)
    audit(db, actor, "create", "farm", farm.id, after={"name": farm.name, "address": farm.address, "validation": True})


def existing_herd(db: Session, farm_id: UUID, herd: list[Bovine]) -> bool:
    from geocattle.models import Animal

    expected = {animal.id: animal.diio for animal in herd}
    matches = db.execute(select(Animal.id, Animal.farm_id, Animal.diio).where(or_(
        Animal.id.in_(expected), Animal.diio.in_(expected.values()),
    ))).all()
    if any(farm != farm_id or expected.get(animal) != diio for animal, farm, diio in matches):
        raise SeedError("Hay una colisión de identidad o DIIO. Usa otra semilla tras revisar el destino.")
    if matches and len(matches) != len(herd):
        raise SeedError("Se encontró un lote incompleto. Revisa su historial antes de cargar otra semilla.")
    return bool(matches)


def active_fences(db: Session, farm_id: UUID) -> list[UUID]:
    from geocattle.models import Geofence, Sector

    return list(db.scalars(select(Geofence.id).join(Sector, Sector.id == Geofence.sector_id).where(
        Geofence.farm_id == farm_id, Sector.farm_id == farm_id,
        Geofence.active, Geofence.valid_to.is_(None),
        Geofence.created_at <= func.statement_timestamp(), Sector.active,
    ).order_by(Geofence.name, Geofence.id)))


def register_animal(db: Session, actor, bovine: Bovine, today: date):
    from geocattle.models import Animal, AnimalHolding
    from geocattle.schemas import AnimalIn
    from geocattle.v3_api import TechnicalPayload
    from geocattle.v3_security import audit

    base = AnimalIn(diio=bovine.diio, name=bovine.name, orientation=bovine.orientation)
    technical = TechnicalPayload(breed=bovine.breed, color=bovine.color, sex=bovine.sex,
                                 birth_date=bovine.birth_date)
    fields = {**base.model_dump(), **technical.model_dump(exclude_unset=True),
              "production_type": bovine.production_type}
    animal = Animal(id=bovine.id, farm_id=actor.farm_id, **fields)
    db.add(animal)
    db.flush()
    holding = AnimalHolding(
        animal_id=animal.id, farm_id=actor.farm_id, reason="seed_validation_data",
        valid_from=local_time(max(bovine.birth_date, today - timedelta(days=540)), 0),
    )
    db.add(holding)
    db.flush()
    audit(db, actor, "create", "animal", animal.id,
          after={**fields, "validation": True, "category": bovine.category})
    return animal, holding


def import_dated_entry(db: Session, actor, animal, holding, entry: Entry, key: UUID) -> None:
    """Write historical timestamps absent from the V3 measurement/report input."""
    from geocattle.v3_api import normalized_payload
    from geocattle.v3_security import audit, execute

    payload = normalized_payload(entry.action, entry.payload)
    at = entry.occurred_at
    if not holding.valid_from <= at < datetime.now(ZONE):
        raise SeedError("La fecha histórica debe estar dentro de la permanencia del bovino.")
    request, entity = uuid4(), uuid4()
    execute(db, """INSERT INTO change_requests
        (id,farm_id,requested_by,action,animal_holding_id,animal_id,expected_version,payload,idempotency_key)
        VALUES (:r,:f,:u,:action,:h,:a,:version,CAST(:p AS jsonb),:key)""",
        r=request, f=actor.farm_id, u=actor.id, action=entry.action, h=holding.id,
        a=animal.id, version=animal.version, p=json.dumps(payload), key=key)
    execute(db, "INSERT INTO change_decisions(request_id,decided_by,decision) VALUES (:r,:u,'direct')",
            r=request, u=actor.id)
    common = {"i": entity, "f": actor.farm_id, "h": holding.id, "r": request, "at": at}
    if entry.action == "animal_profile":
        execute(db, """INSERT INTO animal_measurements
            (id,farm_id,animal_holding_id,animal_id,request_id,measured_at,weight_kg,height_cm)
            VALUES (:i,:f,:h,:a,:r,:at,:weight_kg,:height_cm)""", **common, a=animal.id, **payload)
        kind, applied_entity = "animals", animal.id
    else:
        execute(db, """INSERT INTO animal_reports
            (id,farm_id,animal_holding_id,request_id,occurred_at,description)
            VALUES (:i,:f,:h,:r,:at,:description)""", **common, **payload)
        kind, applied_entity = "animal_reports", entity
    animal.version += 1
    db.flush()
    execute(db, "INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES (:r,:kind,:i)",
            r=request, kind=kind, i=applied_entity)
    audit(db, actor, "change_applied", kind, applied_entity,
          after={"request_id": str(request), "action": entry.action, "decision": "direct",
                 "validation": True, "occurred_at": at.isoformat()})


def persist_herd(db: Session, actor, herd: list[Bovine], histories: list[list[Entry]],
                 fences: list[UUID], today: date) -> None:
    from geocattle.main import assign_pasture
    from geocattle.schemas import PastureIn
    from geocattle.v3_api import ChangeIn, submit

    for index, (bovine, history) in enumerate(zip(herd, histories, strict=True)):
        animal, holding = register_animal(db, actor, bovine, today)
        for event_index, entry in enumerate(history):
            key = uuid5(animal.id, f"entry:{event_index}")
            if entry.occurred_at is not None:
                import_dated_entry(db, actor, animal, holding, entry, key)
            else:
                submit(ChangeIn(action=entry.action, animal_id=animal.id, payload=entry.payload,
                                expected_version=animal.version, idempotency_key=key), user=actor, db=db)
        if fences:
            assign_pasture(PastureIn(animal_id=animal.id, geofence_id=fences[index % len(fences)]),
                           user=actor, db=db)


def run_seed(db: Session, args: argparse.Namespace, backup) -> dict:
    from geocattle.settings import settings

    if not args.dry_run:
        db.execute(text("SELECT pg_advisory_xact_lock(804193899)"))
    user = resolve_actor(db, args.actor_email, args.dry_run)
    environment = settings().app_env
    farm_id, farm, account = resolve_destination(db, user, environment, args.farm_id, args.dry_run)
    actor = SimpleNamespace(id=user.id, farm_id=farm_id, role=user.role, base_role=user.role)
    today = datetime.now(ZONE).date()
    herd = build_herd(farm_id, args.seed, today)
    already_loaded = existing_herd(db, farm_id, herd)
    summary = {
        "predio": farm.name if farm else FARM_NAME, "predio_id": str(farm_id), "semilla": args.seed,
        "estado": "ya_cargado" if already_loaded else "vista_previa" if args.dry_run else "cargado",
        "creados": dict.fromkeys(("predios", "bovinos", "pesajes", "eventos_sanitarios",
                                 "productos", "agenda", "observaciones", "pastoreos", "collares",
                                 "asignaciones_collar", "telemetria"), 0),
    }
    if already_loaded:
        return summary

    fences = active_fences(db, farm_id) if farm else []
    max_farms = owner_capacity(db, user, account) if not farm and user.role == "owner" else None
    histories = [animal_history(animal, index, herd, today) for index, animal in enumerate(herd)]
    actions = Counter(entry.action for history in histories for entry in history)
    summary["creados"].update(
        predios=int(farm is None), bovinos=len(herd), pesajes=actions["animal_profile"],
        eventos_sanitarios=actions["health_record"], agenda=actions["health_schedule"],
        observaciones=actions["animal_report"], pastoreos=len(herd) if fences else 0,
        productos=sum(len(entry.payload.get("treatments", ())) for history in histories for entry in history),
    )
    summary["categorias"] = dict(Counter(animal.category for animal in herd))
    if args.dry_run:
        summary["bovinos"] = [
            {"diio": animal.diio, "nombre": animal.name, "categoría": animal.category,
             "raza": animal.breed, "nacimiento": animal.birth_date.isoformat()}
            for animal in herd
        ]
        return summary

    backup()
    if not farm:
        create_validation_farm(db, user, actor, environment, account, max_farms)
    persist_herd(db, actor, herd, histories, fences, today)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True, help="Archivo privado del entorno destino")
    parser.add_argument("--actor-email", help="Correo del dueño o administrador activo que firma la carga")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Semilla del lote de 40 bovinos")
    parser.add_argument("--farm-id", type=UUID, help="Predio existente del entorno seleccionado")
    parser.add_argument("--allow-existing-farm", action="store_true", help="Autoriza el uso de --farm-id")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Muestra el plan con una transacción de solo lectura")
    modes.add_argument("--backup-only", action="store_true", help="Genera un respaldo custom de la base seleccionada")
    args = parser.parse_args(argv)
    if not args.backup_only and not args.actor_email:
        parser.error("--actor-email es obligatorio para planificar o cargar")
    if bool(args.farm_id) != args.allow_existing_farm:
        parser.error("--farm-id y --allow-existing-farm se usan juntos")

    def backup():
        print(f"Respaldo creado en {backup_database(url)}", file=sys.stderr, flush=True)

    try:
        url = read_configuration(args.env_file)
        if args.backup_only:
            backup()
            return 0
        engine = create_engine(url, connect_args={"hostaddr": url.host, "connect_timeout": 8})
        try:
            with Session(engine) as db, db.begin():
                if args.dry_run:
                    db.execute(text("SET TRANSACTION READ ONLY"))
                summary = run_seed(db, args, backup)
        finally:
            engine.dispose()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except (SeedError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except HTTPException as exc:
        print(f"Error de dominio ({exc.status_code}): {exc.detail}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        code = getattr(getattr(exc, "orig", None), "sqlstate", None)
        print(f"Error PostgreSQL: {type(exc).__name__}{f' ({code})' if code else ''}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
