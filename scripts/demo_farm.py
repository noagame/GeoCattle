#!/usr/bin/env python3
"""Carga, consulta o retira el predio sintético de demostración."""

import argparse
import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid5

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from seed_validation_data import (
    DEFAULT_SEED, ROOT, ZONE, SeedError, animal_history, build_herd,
    health_entry, import_dated_entry, read_configuration, register_animal, resolve_actor,
)
from geocattle.demo_farm import DEMO_FARM_ID

FARM_NAME = "Predio Demostración · La Araucanía"
MARKER = "seed_demo"
GATEWAYS = ("02000000de000001", "02000000de000002")
SECTORS = (
    ("Potrero Las Quilas", -72.688, -38.739),
    ("Pradera El Estero", -72.677, -38.739),
    ("Loma Los Robles", -72.688, -38.730),
    ("Vega Los Tilos", -72.677, -38.730),
)
COUNTS = (
    "animals", "sectors", "geofences", "geofence_sectors", "pasture_assignments",
    "devices", "assignments", "gateways", "telemetry", "telemetry_receptions",
    "events", "maintenance", "health_events", "health_treatments", "health_schedules",
    "animal_measurements", "animal_reports", "change_requests", "notifications", "audit_log",
)


def polygon(west, south, width, height):
    return {"type": "Polygon", "coordinates": [[
        [west, south], [west + width, south], [west + width, south + height],
        [west, south + height], [west, south],
    ]]}


def postgis_polygon(geometry):
    return func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), 4326)


def load_sectors(db, actor, since, revised_at):
    from geocattle.main import create_sector
    from geocattle.models import Geofence, GeofenceSector
    from geocattle.schemas import SectorIn
    from geocattle.v3_security import audit

    fences = []
    for index, (name, west, south) in enumerate(SECTORS):
        sector = create_sector(SectorIn(name=name, description="Pradera de uso demostrativo."),
                               user=actor, db=db)["id"]
        key = uuid5(DEMO_FARM_ID, f"geofence:{index}")
        versions = []
        for version in (1, 2) if index < 2 else (1,):
            historical = index < 2 and version == 1
            geometry = polygon(west, south, 0.007 if historical else 0.008, 0.007)
            fence = Geofence(
                id=uuid5(key, str(version)), geofence_key=key, farm_id=DEMO_FARM_ID,
                sector_id=sector, name=name, version=version, geometry=postgis_polygon(geometry),
                created_at=since if version == 1 else revised_at,
                valid_to=revised_at if historical else None, active=not historical, created_by=actor.id,
            )
            db.add(fence)
            db.flush()
            db.add(GeofenceSector(geofence_id=fence.id, sector_id=sector, farm_id=DEMO_FARM_ID))
            audit(db, actor, "version_create", "geofence", fence.id, after={
                "geofence_key": key, "sector_ids": [sector], "version": version, "geometry": geometry,
            })
            versions.append(fence)
        fences.append(versions)
    return fences


def load_herd(db, actor, fences, now):
    from geocattle.main import assign_pasture
    from geocattle.models import PastureAssignment
    from geocattle.schemas import PastureIn
    from geocattle.v3_api import ChangeIn, submit
    from geocattle.v3_security import audit

    today = now.astimezone(ZONE).date()
    herd = build_herd(DEMO_FARM_ID, DEFAULT_SEED, today)
    animals = []
    for index, bovine in enumerate(herd):
        animal, holding = register_animal(db, actor, bovine, today)
        versions = fences[index % len(fences)]
        if len(versions) == 2:
            old = PastureAssignment(
                id=uuid5(animal.id, "pastoreo-histórico"), farm_id=DEMO_FARM_ID,
                animal_id=animal.id, animal_holding_id=holding.id, assigned_by=actor.id,
                geofence_id=versions[0].id, valid_from=versions[0].created_at,
                valid_to=versions[0].valid_to,
            )
            db.add(old)
            audit(db, actor, "close", "pasture_assignment", old.id, after={
                "geofence_id": old.geofence_id, "valid_to": old.valid_to,
            })
        fence = versions[-1]
        assign_pasture(PastureIn(animal_id=animal.id, geofence_id=fence.id,
                                 effective_at=fence.created_at), user=actor, db=db)
        for entry_index, entry in enumerate(animal_history(bovine, index, herd, today)):
            key = uuid5(animal.id, f"entry:{entry_index}")
            if entry.occurred_at is not None:
                import_dated_entry(db, actor, animal, holding, entry, key)
            else:
                submit(ChangeIn(action=entry.action, animal_id=animal.id, payload=entry.payload,
                                expected_version=animal.version, idempotency_key=key), user=actor, db=db)
        if index < 12:
            entry = health_entry(bovine, "vaccination", "Refuerzo clostridial registrado en la manga.",
                                 now - timedelta(days=1 + index % 5),
                                 ("Vacuna clostridial", "Subcutánea", 0, 0))
            submit(ChangeIn(action=entry.action, animal_id=animal.id, payload=entry.payload,
                            expected_version=animal.version, idempotency_key=uuid5(animal.id, "refuerzo")),
                   user=actor, db=db)
        if index < 6:
            due_offset = (-24, -3, 21, 27, 33, 39)[index]
            submit(ChangeIn(action="health_schedule", animal_id=animal.id, expected_version=animal.version,
                            idempotency_key=uuid5(animal.id, "agenda-próxima"), payload={
                                "kind": "checkup",
                                "description": "Control de condición corporal del lote en la manga.",
                                "due_at": now + timedelta(hours=due_offset),
                            }), user=actor, db=db)
        animals.append(animal)
    return animals


def load_devices(db, actor, animals, since, now):
    from geocattle.device_inventory import create_inventory_device
    from geocattle.main import assign, create_maintenance
    from geocattle.schemas import AssignmentIn, DeviceIn, MaintenanceIn
    from geocattle.v3_api import insert_gateway

    for index, eui in enumerate(GATEWAYS):
        insert_gateway(db, actor, eui, ("Gateway simulado · Las Quilas", "Gateway simulado · El Estero")[index],
                       -72.686 + index * 0.013, -38.737)

    devices = []
    for index in range(28):
        spec = DeviceIn(hardware_id=f"DEMO-COLLAR-{index + 1:03d}", name=f"Collar simulado {index + 1:02d}",
                        interval_seconds=86400, transport="academic")
        device = create_inventory_device(db, actor, spec, installed_at=since, origin={"source": "sim"})
        devices.append(device)
        if index < 26:
            effective_at = now - timedelta(days=6) if index == 24 else since
            assign(AssignmentIn(animal_id=animals[index].id, device_id=device.id, effective_at=effective_at),
                   user=actor, db=db)
    prior_animal = animals[26]
    prior = assign(AssignmentIn(animal_id=prior_animal.id, device_id=devices[26].id, effective_at=since),
                   user=actor, db=db)
    for index, kind, result in (
        (1, "inspection", "Carcasa y sujeción revisadas en la manga."),
        (7, "recharge", "Recarga efectuada. Collar reinstalado en el potrero."),
        (26, "replacement", "Unidad retirada de la vaquilla y devuelta al inventario."),
    ):
        create_maintenance(MaintenanceIn(device_id=devices[index].id, kind=kind,
                                         at=now - timedelta(hours=18), result=result), user=actor, db=db)
    return devices, prior["id"]


def replay(db, animals, devices, now):
    from geocattle.domain import condition, ingest
    from geocattle.schemas import TelemetryIn

    for index, (animal, device) in enumerate(zip(animals[:27], devices[:27], strict=True)):
        _, west, south = SECTORS[index % len(SECTORS)]
        sequence = 0

        def sample(at, *, outside=False, battery=None, fix=True):
            nonlocal sequence
            sequence += 1
            jitter = (sequence % 8) * 0.00007
            lng = west + (0.0086 + jitter if outside else 0.001 + (index % 7) * 0.00075 + jitter)
            lat = south + 0.0015 + (index % 9) * 0.00042 + jitter
            activity = round(0.22 + (index % 9) * 0.027 + (sequence % 7) * 0.058, 2)
            ingest(db, TelemetryIn(
                hardware_id=device.hardware_id, session_id="geocattle-demostracion", seq=sequence,
                observed_at=at, longitude=lng if fix else None, latitude=lat if fix else None,
                gnss_valid=fix, battery_mv=battery or 3710 + (index * 29 + sequence * 3) % 160,
                surface_temperature_c=round(34.0 + (index % 9) * 0.31 + (sequence % 5) * 0.22, 1),
                activity_index=activity, source="sim", quality={
                    "simulation": True, "origin": "demostración",
                    "movement_state": "moving" if activity >= 0.52 else "rest",
                },
                receptions=[{"gateway_eui": GATEWAYS[index % 2], "rssi_dbm": -78.0 - index,
                             "snr_db": 8.0 - (index % 10) * 0.45}],
            ), received_at=at + timedelta(seconds=3))

        offline = index in (4, 5, 11, 12)
        last_day = 5 if offline else 3 if index == 26 else 0
        first_day = 5 if index == 24 else 6
        for day in range(first_day, last_day - 1, -1):
            for hour in (15, 9, 3):
                sample(now - timedelta(days=day, hours=hour),
                       outside=(index in (9, 10, 18) and day == 3 and hour != 3),
                       battery=3190 if index in (14, 15, 19) and day == 2 and hour == 9 else None)
        if offline:
            detected = now - timedelta(days=1, hours=index)
            sample(now - timedelta(days=5), fix=False)
            condition(db, device, animal.id, "communication_timeout", True, at=detected, detail={
                "last_received_at": device.last_received_at.isoformat(),
                "threshold_seconds": 3 * device.interval_seconds + 30,
            })
            if index in (4, 5):
                continue
        if index == 26:
            continue
        for minutes in (19, 9, 2):
            sample(now - timedelta(minutes=minutes + index), outside=index in (0, 1, 2),
                   battery=3130 + index * 5 if index in (3, 6, 7, 8) else None,
                   fix=index != 13)


def load_followup(db, actor, now):
    from geocattle.main import action
    from geocattle.schemas import ActionIn
    from geocattle.v3_api import notify
    from geocattle.v3_security import execute, rows

    cases = rows(db, """SELECT e.id,e.type,e.condition,a.name FROM events e
        JOIN animals a ON a.id=e.animal_id WHERE e.farm_id=:f
        ORDER BY e.condition,e.opened_at,e.id""", f=DEMO_FARM_ID)
    for index, event in enumerate(cases):
        if event["condition"] == "resolved":
            state, note = "conclude", "Caso revisado en terreno y cerrado en el registro de demostración."
        elif index % 3 == 0:
            state, note = "acknowledge", "Aviso recibido durante la ronda de supervisión."
        elif index % 3 == 1:
            state, note = "review", "Se programa verificación en terreno en la próxima ronda."
        else:
            continue
        action(event["id"], ActionIn(action=state, note=note), user=actor, db=db)

    owners_and_admins = rows(db, "SELECT id FROM users WHERE active AND (id=:u OR role='admin')", u=actor.id)
    labels = {"escape": "Salida de geocerca", "low_battery": "Batería baja",
              "communication_timeout": "Desconexión de collar"}
    for recipient in owners_and_admins:
        for event in cases:
            if event["condition"] == "active":
                notify(db, DEMO_FARM_ID, recipient["id"],
                       f'{labels[event["type"]]} · {event["name"]}. Predio de demostración.')
        notify(db, DEMO_FARM_ID, recipient["id"], "Revisar las próximas atenciones de la agenda sanitaria.")
        execute(db, """INSERT INTO notifications
          (id,farm_id,recipient_id,channel,status,message,read_at,created_at,next_attempt_at)
          VALUES (gen_random_uuid(),:f,:u,'in_app','read',:m,:at,:at,:at)""",
                f=DEMO_FARM_ID, u=recipient["id"], at=now - timedelta(days=1),
                m="Jornada de pesaje completada y registrada en las fichas del rebaño.")


def populate(db, owner, account):
    from geocattle.main import close_assignment
    from geocattle.models import Farm, RuleSettings, utcnow
    from geocattle.schemas import AssignmentClose
    from geocattle.v3_security import audit, execute

    actor = SimpleNamespace(id=owner.id, username=owner.username, farm_id=DEMO_FARM_ID,
                            role="owner", base_role="owner")
    now = utcnow()
    since = now - timedelta(days=10)
    db.add(Farm(id=DEMO_FARM_ID, name=FARM_NAME, environment="simulation", account_id=account["id"],
                address="Ubicación ficticia · Temuco", region="La Araucanía", commune="Temuco",
                timezone=ZONE.key, boundary=func.ST_Multi(postgis_polygon(polygon(-72.690, -38.741, 0.024, 0.020)))))
    db.flush()
    db.add(RuleSettings(farm_id=DEMO_FARM_ID))
    execute(db, """INSERT INTO farm_features(farm_id,feature_code)
                   SELECT :f,code FROM features WHERE code<>'fma'""", f=DEMO_FARM_ID)
    audit(db, actor, MARKER, "farm", DEMO_FARM_ID, after={"name": FARM_NAME, "source": "sim"})
    fences = load_sectors(db, actor, since, now - timedelta(days=7))
    animals = load_herd(db, actor, fences, now)
    devices, historical_assignment = load_devices(db, actor, animals, since, now)
    replay(db, animals, devices, now)
    close_assignment(historical_assignment, AssignmentClose(effective_at=now - timedelta(days=2)),
                     user=actor, db=db)
    load_followup(db, actor, now)


# Las tablas hijas sin farm_id se acotan mediante las filas de su padre.
# El orden satisface las FK y mantiene activas sus comprobaciones.
PURGE = (
    ("notification_attempts", "notification_id IN (SELECT id FROM notifications WHERE {notice})",
     "notification_attempts_immutable"),
    ("notifications", "{notice}", None),
    ("event_actions", "event_id IN (SELECT id FROM events WHERE farm_id=:f)", "actions_immutable"),
    ("events", "farm_id=:f", None),
    ("animal_states", "animal_id IN (SELECT id FROM animals WHERE farm_id=:f)", None),
    ("telemetry_receptions", "farm_id=:f", "immutable"),
    ("device_configs", "device_id IN (SELECT id FROM devices WHERE farm_id=:f)", None),
    ("telemetry", "farm_id=:f", "telemetry_immutable"),
    ("maintenance", "farm_id=:f", "maintenance_immutable"),
    ("health_schedules", "farm_id=:f", "immutable"),
    ("health_treatments", "farm_id=:f", "immutable"),
    ("health_events", "farm_id=:f", "immutable"),
    ("animal_reports", "farm_id=:f", "immutable"),
    ("animal_measurements", "farm_id=:f", "immutable"),
    ("change_applications", "request_id IN (SELECT id FROM change_requests WHERE farm_id=:f)", "immutable"),
    ("change_decisions", "request_id IN (SELECT id FROM change_requests WHERE farm_id=:f)", "immutable"),
    ("change_requests", "farm_id=:f", "immutable"),
    ("trust_grants", "farm_id=:f", None),
    ("invitation_mail", "invitation_id IN (SELECT id FROM invitations WHERE farm_id=:f)", None),
    ("invitations", "farm_id=:f", None),
    ("farm_memberships", "farm_id=:f", None),
    ("pasture_assignments", "farm_id=:f", None),
    ("assignments", "farm_id=:f", None),
    ("geofence_sectors", "farm_id=:f", None),
    ("geofences", "farm_id=:f", None),
    ("animal_holdings", "farm_id=:f", None),
    ("animals", "farm_id=:f", None),
    ("sectors", "farm_id=:f", None),
    ("devices", "farm_id=:f", None),
    ("gateways", "farm_id=:f", None),
    ("farm_features", "farm_id=:f", None),
    ("rule_settings", "farm_id=:f", None),
    ("request_metrics", "farm_id=:f", "immutable"),
    ("audit_log", "farm_id=:f", "audit_immutable"),
    ("farms", "id=:f AND is_demonstration_farm(id,environment)", None),
)


def purge(db):
    from geocattle.v3_security import execute, one

    execute(db, "SET LOCAL lock_timeout='3s'")
    if one(db, "SELECT id FROM telemetry WHERE farm_id=:f AND source<>'sim' LIMIT 1", f=DEMO_FARM_ID):
        raise SeedError("El predio de demostración contiene telemetría física. Se canceló el retiro.")
    execute(db, "UPDATE login_sessions SET active_farm_id=NULL WHERE active_farm_id=:f", f=DEMO_FARM_ID)
    execute(db, "UPDATE devices SET last_telemetry_id=NULL WHERE farm_id=:f", f=DEMO_FARM_ID)
    for table, predicate, immutable_trigger in PURGE:
        # Solo suspende la inmutabilidad bajo el bloqueo exclusivo y en la misma transacción.
        if immutable_trigger:
            execute(db, f"ALTER TABLE {table} DISABLE TRIGGER {immutable_trigger}")
        where = predicate.format(notice="farm_id=:f OR event_id IN (SELECT id FROM events WHERE farm_id=:f)")
        execute(db, f"DELETE FROM {table} WHERE {where}", f=DEMO_FARM_ID)
        if immutable_trigger:
            execute(db, f"ALTER TABLE {table} ENABLE TRIGGER {immutable_trigger}")


def summary(db):
    from geocattle.v3_security import one, rows

    counts = {}
    for table in COUNTS:
        scope = "farm_id=:f"
        if table == "notifications":
            scope += " OR event_id IN (SELECT id FROM events WHERE farm_id=:f)"
        counts[table] = one(db, f"SELECT count(*) AS n FROM {table} WHERE {scope}", f=DEMO_FARM_ID)["n"]
    counts["event_actions"] = one(db, """SELECT count(*) AS n FROM event_actions a
        JOIN events e ON a.event_id=e.id WHERE e.farm_id=:f""", f=DEMO_FARM_ID)["n"]
    counts["events_by_state"] = rows(db, """SELECT type,condition,attention,count(*) AS n
        FROM events WHERE farm_id=:f GROUP BY type,condition,attention ORDER BY 1,2,3""", f=DEMO_FARM_ID)
    counts["health_by_type"] = rows(db, """SELECT event_type,count(*) AS n FROM health_events
        WHERE farm_id=:f GROUP BY event_type ORDER BY 1""", f=DEMO_FARM_ID)
    return counts


def backup_native():
    from compartir_base import native, stamp

    pg = native()
    directory = ROOT / ".runtime" / "backups"
    directory.mkdir(exist_ok=True)
    archive = directory / f"geocattle-antes-demostracion-{stamp()}.dump"
    pg.dump(pg.database, archive)
    catalog = pg.run("pg_restore", None, "--list", str(archive), stdout=subprocess.PIPE)
    if b"TABLE DATA public farms " not in catalog or b"TABLE DATA public telemetry " not in catalog:
        raise SeedError("No se pudo verificar el catálogo del respaldo. La base se conserva.")
    print(f"Respaldo verificado ({archive.stat().st_size} bytes): {archive}", flush=True)


def run(db, args, live):
    from geocattle.v3_security import execute, one

    if args.action != "estado":
        execute(db, "SELECT pg_advisory_xact_lock(804193896)")
    farm = one(db, "SELECT name,is_demonstration_farm(id,environment) AS demo FROM farms WHERE id=:f",
               f=DEMO_FARM_ID)
    if farm and (not farm["demo"] or not one(db, """SELECT id FROM audit_log
             WHERE farm_id=:f AND object_type='farm' AND object_id=CAST(:f AS text) AND action=:marker""",
                                            f=DEMO_FARM_ID, marker=MARKER)):
        raise SeedError("El identificador reservado está ocupado por un predio sin la marca de la carga.")
    if args.action == "cargar" and not farm:
        owner = resolve_actor(db, args.owner, False)
        account = one(db, "SELECT id FROM owner_accounts WHERE owner_user_id=:u AND active FOR UPDATE",
                      u=owner.id)
        if owner.role != "owner" or not account:
            raise SeedError("Indica una cuenta dueña activa con cuenta de propietario en V3.")
        if live:
            backup_native()
        populate(db, owner, account)
        return "cargado", summary(db)
    if args.action == "eliminar" and farm:
        if live:
            backup_native()
        purge(db)
        return "eliminado", None
    if farm:
        return "ya_cargado" if args.action == "cargar" else "presente", summary(db)
    return "ausente", None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("cargar", "estado", "eliminar"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--owner", help="Correo del dueño activo al que se vincula el predio")
    args = parser.parse_args()
    if args.action == "cargar" and not args.owner:
        parser.error("cargar requiere --owner")
    from compartir_base import ShareError, native
    from docker_project import ProjectError

    try:
        url = read_configuration(args.env_file)
        live = args.env_file.resolve() == (ROOT / ".env.academic").resolve()
        if live:
            native()
        elif os.environ["APP_ENV"] != "simulation":
            raise SeedError("Usa .env.academic para el prototipo o una configuración aislada de simulación.")
        os.environ.update(APP_ENV="simulation", SIMULATION_ENABLED="true",
                          LOCAL_ADMIN_PASSWORD_ONLY="false", CONFIG_DOWNLINK_ENABLED="false")
        engine = create_engine(url, hide_parameters=True)
        with Session(engine) as db, db.begin():
            if args.action == "estado":
                db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
            if not live:
                from prototype_windows import PG_DATA
                data_directory = Path(db.connection().exec_driver_sql("SHOW data_directory").scalar_one())
                if data_directory.resolve() == PG_DATA.resolve():
                    raise SeedError("La configuración de QA apunta al PostgreSQL del prototipo.")
            state, counts = run(db, args, live)
        print(json.dumps({"estado": state, "predio": FARM_NAME, "id": str(DEMO_FARM_ID), "conteos": counts},
                         ensure_ascii=False, indent=2))
    except ValidationError:
        print("Error: revisa la configuración privada y los datos de la carga.")
        return 1
    except (SeedError, ShareError, ProjectError, ValueError, OSError) as error:
        print(f"Error: {error}")
        return 1
    except HTTPException as error:
        print(f"Error de dominio ({error.status_code}): {error.detail}")
        return 1
    except SQLAlchemyError as error:
        original = getattr(error, "orig", None)
        print(f"Error de base de datos ({getattr(original, 'sqlstate', None) or type(error).__name__}). "
              "Se revirtió la operación. Comprueba las migraciones y las referencias del predio.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
