"""Carga de validación, historial V3 e inventario sobre PostgreSQL/PostGIS de QA."""

from argparse import Namespace
from datetime import datetime
import os
from pathlib import Path
import sys
from unittest.mock import Mock
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from geocattle.models import Farm
from test_v3_api import v3

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.seed_validation_data import DEFAULT_SEED, SeedError, run_seed

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="Requiere PostgreSQL/PostGIS de QA")
TABLES = {
    "animals": 40,
    "animal_holdings": 40,
    "animal_measurements": 120,
    "health_events": 96,
    "health_treatments": 88,
    "health_schedules": 40,
    "animal_reports": 50,
    "change_requests": 306,
    "devices": 0,
    "assignments": 0,
    "telemetry": 0,
    "telemetry_receptions": 0,
}


def execute_seed(db, email, backup, *, dry_run=False, farm_id=None):
    args = Namespace(actor_email=email, dry_run=dry_run, farm_id=farm_id, seed=DEFAULT_SEED)
    with db.begin_nested():
        return run_seed(db, args, backup)


def count_seed_rows(db, farm_id):
    return {
        table: db.scalar(text(f"SELECT count(*) FROM {table} WHERE farm_id=:farm"), {"farm": farm_id})
        for table in (*TABLES, "pasture_assignments", "audit_log")
    }


@pytest.mark.parametrize("with_geofence", [False, True])
def test_validation_seed_counts_author_and_idempotency(v3, with_geofence):
    db, actor = v3.db, v3.users["owner"]
    client = v3.client("owner")
    farm_id = None
    geofence_id = None
    if with_geofence:
        farm = client.post("/api/v1/v3/farms", json={"name": "Predio QA con pastoreo"})
        assert farm.status_code == 201, farm.text
        farm_id = UUID(farm.json()["id"])
        context = client.post("/api/v1/auth/context", json={"farm_id": str(farm_id)})
        assert context.status_code == 200, context.text
        sector = client.post("/api/v1/sectors", json={"name": "Potrero QA"})
        assert sector.status_code == 201, sector.text
        fence = client.post("/api/v1/geofences", json={
            "name": "Pradera QA", "sector_id": sector.json()["id"], "expected_version": 0,
            "confirm_impact": True,
            "geometry": {"type": "Polygon", "coordinates": [[
                [-72.62, -38.72], [-72.61, -38.72], [-72.61, -38.71],
                [-72.62, -38.71], [-72.62, -38.72],
            ]]},
        })
        assert fence.status_code == 201, fence.text
        geofence_id = UUID(fence.json()["id"])

    backup = Mock()
    preview = execute_seed(db, actor.email, backup, dry_run=True, farm_id=farm_id)
    target_id = UUID(preview["predio_id"])
    pastures = 40 if with_geofence else 0
    assert preview["estado"] == "vista_previa"
    assert preview["creados"]["bovinos"] == 40
    assert preview["creados"]["pastoreos"] == pastures
    backup.assert_not_called()
    initial = count_seed_rows(db, target_id)
    assert not any(initial[table] for table in TABLES)
    assert (db.get(Farm, target_id) is not None) == with_geofence

    def verify_pre_backup_state():
        assert count_seed_rows(db, target_id) == initial
        assert (db.get(Farm, target_id) is not None) == with_geofence

    backup.side_effect = verify_pre_backup_state
    result = execute_seed(db, actor.email, backup, farm_id=farm_id)
    backup.assert_called_once_with()
    assert result["estado"] == "cargado" and result["creados"] == preview["creados"]
    assert result["categorias"] == {
        "Vaca": 14, "Vaquilla": 8, "Ternera": 5, "Ternero": 5, "Novillo": 6, "Toro": 2,
    }
    saved = count_seed_rows(db, target_id)
    assert saved == {
        **TABLES, "pasture_assignments": pastures,
        "audit_log": initial["audit_log"] + 40 + 306 + pastures + int(not with_geofence),
    }
    repeat = execute_seed(db, actor.email, backup, farm_id=farm_id)
    assert repeat["estado"] == "ya_cargado" and not any(repeat["creados"].values())
    backup.assert_called_once_with()
    assert count_seed_rows(db, target_id) == saved
    db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    params = {"farm": target_id, "actor": actor.id, "geofence": geofence_id}
    assert db.scalar(text("""
        SELECT count(*) FROM change_requests r
        JOIN change_decisions d ON d.request_id=r.id
        JOIN change_applications a ON a.request_id=r.id
        WHERE r.farm_id=:farm AND r.requested_by=:actor
          AND d.decided_by=:actor AND d.decision='direct'
    """), params) == 306
    assert db.scalar(text("""
        SELECT count(*) FROM animal_reports WHERE farm_id=:farm AND description LIKE 'Parto observado.%'
    """), params) == 10
    assert db.scalar(text("""
        SELECT count(*) FROM health_schedules
        WHERE farm_id=:farm AND due_at>now() AND created_by=:actor
    """), params) == 40
    assert db.scalar(text("""
        SELECT count(*) FROM animal_measurements m JOIN animals a ON a.id=m.animal_id
        JOIN animal_holdings h ON h.id=m.animal_holding_id
        WHERE m.farm_id=:farm AND (m.measured_at<h.valid_from
          OR (h.valid_from AT TIME ZONE 'America/Santiago')::date<a.birth_date
          OR m.measured_at>=now() OR m.measured_at<now()-interval '18 months')
    """), params) == 0
    if geofence_id:
        assert db.scalar(text("""
            SELECT count(*) FROM pasture_assignments p JOIN animals a ON a.id=p.animal_id
            JOIN geofences g ON g.id=p.geofence_id
            WHERE p.farm_id=:farm AND p.assigned_by=:actor AND g.id=:geofence
              AND p.valid_from>=g.created_at AND p.valid_to IS NULL AND a.sector_id=g.sector_id
        """), params) == pastures

    user = client.get("/api/v1/auth/me").json()["user"]
    assert str(target_id) in {farm["id"] for farm in user["farms"]}
    context = client.post("/api/v1/auth/context", json={"farm_id": str(target_id)})
    assert context.status_code == 200, context.text
    inventory = client.get("/api/v1/animals").json()
    assert inventory["total"] == 40
    first = inventory["items"][0]
    assert first["diio"] == preview["bovinos"][0]["diio"]
    record = client.get(f"/api/v1/v3/animals/{first['id']}/record").json()
    assert record["animal"]["sex"] == "female" and record["animal"]["breed"] == "Holstein"
    assert len(record["measurements"]) == len(record["health_events"]) == 3
    assert len(record["treatments"]) == 3 and all(t["batch_number"] for t in record["treatments"])
    assert len(record["reports"]) == 2 and len(record["schedules"]) == 1

    report = client.get("/api/v1/v3/animal-reports/inventario").json()
    assert report["total"] == 40
    event_day = datetime.fromisoformat(record["health_events"][0]["occurred_at"]).astimezone(
        ZoneInfo("America/Santiago"),
    ).date()
    response = client.get("/api/v1/v3/animal-reports/sanidad", params={
        "animal_id": first["id"], "start": event_day.isoformat(), "format": "csv",
    })
    assert response.status_code == 200 and "SIM-ANT" in response.text


def test_destination_guard_and_backup_failure(v3):
    db, actor = v3.db, v3.users["owner"]
    backup = Mock(side_effect=SeedError("falló el respaldo"))
    with pytest.raises(SeedError, match="no es dueño"):
        execute_seed(db, actor.email, backup, farm_id=v3.farms["other_owner"].id)
    with pytest.raises(SeedError, match="dueño o administrador"):
        execute_seed(db, v3.users["worker"].email, backup)
    backup.assert_not_called()

    preview = execute_seed(db, actor.email, backup, dry_run=True)
    target_id = UUID(preview["predio_id"])
    with pytest.raises(SeedError, match="falló el respaldo"):
        execute_seed(db, actor.email, backup)
    backup.assert_called_once_with()
    assert not any(count_seed_rows(db, target_id).values())
    assert db.get(Farm, target_id) is None
