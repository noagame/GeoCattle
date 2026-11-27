import json
import os
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from geocattle import hardware_api, mirror_sync, worker
from geocattle.db import SessionLocal
from geocattle.models import Farm, utcnow
from geocattle.settings import settings


@pytest.fixture
def field_db(monkeypatch):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Requiere PostgreSQL/PostGIS de QA')
    config = settings()
    assert config.database_url == url, 'DATABASE_URL y TEST_DATABASE_URL deben apuntar a la misma base aislada'
    monkeypatch.setattr(config, 'app_env', 'development')
    monkeypatch.setattr(config, 'mirror_mode', 'field')
    monkeypatch.delenv('INGEST_FARM_ID', raising=False)
    with SessionLocal() as db:
        yield db


def add_farm(db, environment='development', active=True):
    farm = Farm(id=uuid4(), name='QA capturadora USB', environment=environment, active=active)
    db.add(farm)
    db.flush()
    return farm.id


@pytest.fixture
def usb_status(monkeypatch, tmp_path):
    path = tmp_path / 'status.json'
    monkeypatch.setenv('USB_STATUS_PATH', str(path))
    return path


def write_usb_status(path, updated_at, *, captured=12):
    snapshot = {'connected': True, 'port': 'COM42', 'receiver_mode': 'direct', 'bus_version': 1,
                'captured': captured, 'delivered': 9, 'pending': 3,
                'last_capture': (updated_at - timedelta(seconds=5)).isoformat(),
                'updated_at': updated_at.isoformat()}
    path.write_text(json.dumps(snapshot), encoding='utf-8-sig')
    return snapshot


def saved_status(db, farm_id):
    return db.execute(text("""
        SELECT snapshot, received_at, ctid::text AS row_version FROM receiver_status WHERE farm_id = :farm
    """), {'farm': farm_id}).one_or_none()


def test_publishes_the_configured_farm_snapshot_without_rewriting_it(field_db, usb_status, monkeypatch):
    other_id = add_farm(field_db)
    destination_id = add_farm(field_db)
    monkeypatch.setenv('INGEST_FARM_ID', str(destination_id))
    updated_at = utcnow() - timedelta(seconds=10)
    snapshot = write_usb_status(usb_status, updated_at)
    monkeypatch.setattr(worker, 'SessionLocal', SimpleNamespace(begin=lambda: nullcontext(field_db)))
    monkeypatch.setattr(mirror_sync, 'run_mirror_cycle', lambda: None)
    worker.run_once()

    first = saved_status(field_db, destination_id)
    assert first.snapshot == snapshot
    assert first.received_at == updated_at
    assert saved_status(field_db, other_id) is None

    write_usb_status(usb_status, updated_at, captured=13)
    hardware_api.publish_usb_receiver_status(field_db)
    assert saved_status(field_db, destination_id) == first

    new_time = updated_at + timedelta(seconds=2)
    new_snapshot = write_usb_status(usb_status, new_time, captured=13)
    hardware_api.publish_usb_receiver_status(field_db)
    assert saved_status(field_db, destination_id).snapshot == new_snapshot

    write_usb_status(usb_status, updated_at)
    hardware_api.publish_usb_receiver_status(field_db)
    assert saved_status(field_db, destination_id).snapshot == new_snapshot


def test_infers_only_one_active_farm_in_the_physical_environment(field_db, usb_status, monkeypatch):
    destination_id = add_farm(field_db)
    simulation_id = add_farm(field_db, 'simulation')
    other_environment_id = add_farm(field_db, 'production')
    inactive_id = add_farm(field_db, active=False)
    updated_at = utcnow()
    snapshot = write_usb_status(usb_status, updated_at)
    hardware_api.publish_usb_receiver_status(field_db)
    assert saved_status(field_db, destination_id).snapshot == snapshot

    other_active_id = add_farm(field_db)
    write_usb_status(usb_status, updated_at + timedelta(seconds=1))
    hardware_api.publish_usb_receiver_status(field_db)
    for invalid_id in (simulation_id, other_environment_id, inactive_id, 'not-a-uuid', uuid4()):
        monkeypatch.setenv('INGEST_FARM_ID', str(invalid_id))
        hardware_api.publish_usb_receiver_status(field_db)
    assert saved_status(field_db, destination_id).snapshot == snapshot
    for farm_id in (simulation_id, other_environment_id, inactive_id, other_active_id):
        assert saved_status(field_db, farm_id) is None


def test_clamps_future_usb_timestamp_and_does_not_keep_refreshing_it(field_db, usb_status):
    farm_id = add_farm(field_db)
    before = utcnow()
    snapshot = write_usb_status(usb_status, before + timedelta(days=1))
    hardware_api.publish_usb_receiver_status(field_db)
    first = saved_status(field_db, farm_id)
    assert before <= first.received_at <= utcnow()
    assert first.snapshot == snapshot

    hardware_api.publish_usb_receiver_status(field_db)
    assert saved_status(field_db, farm_id) == first


@pytest.mark.parametrize('content', [None, b'\xff', b'{', b'[]', b'{"connected": true, "updated_at": "2026-01-01"}'])
def test_missing_or_unreadable_file_never_reaches_database(usb_status, content):
    if content is not None:
        usb_status.write_bytes(content)
    hardware_api.publish_usb_receiver_status(None)


def test_replica_worker_does_not_publish(monkeypatch, usb_status):
    write_usb_status(usb_status, utcnow())
    monkeypatch.setattr(settings(), 'mirror_mode', 'replica')
    monkeypatch.setattr(worker, 'SessionLocal', None)
    worker.run_once()


def test_replica_receiver_reads_usb_fields_and_expires_with_capture_time(field_db, usb_status, monkeypatch):
    farm_id = add_farm(field_db)
    other_farm_id = add_farm(field_db)
    monkeypatch.setenv('INGEST_FARM_ID', str(farm_id))
    snapshot = write_usb_status(usb_status, utcnow() - timedelta(seconds=45))
    hardware_api.publish_usb_receiver_status(field_db)
    write_usb_status(usb_status, utcnow(), captured=99)

    config = settings()
    monkeypatch.setattr(config, 'mirror_mode', 'replica')
    monkeypatch.setattr(config, 'mirror_source_environment', 'development')
    monkeypatch.setattr(config, 'app_env', 'production')
    user = SimpleNamespace(farm_id=farm_id, role='owner')
    app = FastAPI()
    app.include_router(hardware_api.router)
    app.dependency_overrides[hardware_api.current_user] = lambda: user
    app.dependency_overrides[hardware_api.get_db] = lambda: field_db

    with TestClient(app) as client:
        response = client.get('/api/v1/hardware/receiver')
        assert response.status_code == 200
        assert response.json() == {**snapshot, 'available': True}

        user.farm_id = other_farm_id
        assert client.get('/api/v1/hardware/receiver').json()['available'] is False
        user.farm_id = farm_id
        user.role = 'worker'
        assert client.get('/api/v1/hardware/receiver').status_code == 403

        user.role = 'owner'
        field_db.execute(text('UPDATE receiver_status SET received_at = :stale WHERE farm_id = :farm'),
                         {'stale': utcnow() - timedelta(seconds=91), 'farm': farm_id})
        response = client.get('/api/v1/hardware/receiver')
        assert response.json() == {**snapshot, 'available': False, 'connected': False}
