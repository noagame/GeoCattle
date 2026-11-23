import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text

from geocattle.domain import check_timeouts, condition
from geocattle.device_inventory import devices_json
from geocattle.models import AnimalState, Assignment, Audit, Device, Event, Maintenance, Telemetry, utcnow
from geocattle.settings import settings
from test_v3_api import PASSWORD, totp, v3
from test_v3_legacy_assignments import legacy_v3, receive_packet, register_animal, register_device

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS de QA')


def assign_collar(client, animal_id, device_id):
    result = client.post('/api/v1/assignments', json={'animal_id': str(animal_id), 'device_id': str(device_id)})
    assert result.status_code == 201, result.text
    return UUID(result.json()['id'])


def inventory_item(client, device_id):
    result = client.get('/api/v1/devices')
    assert result.status_code == 200, result.text
    return next(item for item in result.json()['items'] if item['id'] == str(device_id))


def test_inventory_reads_pending_config_assignment_and_history_in_one_query(legacy_v3):
    db, client, farm, _ = legacy_v3
    assigned, unused = (register_device(client) for _ in range(2))
    association = assign_collar(client, register_animal(client), assigned)
    configured = client.post(f'/api/v1/devices/{assigned}/config',
                             json={'interval_seconds': 180, 'expected_version': 0})
    assert configured.status_code == 201, configured.text
    db.flush()
    statements = []
    connection = db.connection()

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(connection, 'before_cursor_execute', capture)
    try:
        inventory = {row['id']: row for row in devices_json(db, farm.id)}
    finally:
        event.remove(connection, 'before_cursor_execute', capture)
    assert len(statements) == 1
    assert inventory[unused]['can_delete'] is True
    assert inventory[assigned]['assignment_id'] == association
    assert inventory[assigned]['can_delete'] is False
    assert inventory[assigned]['pending_config'] == {'interval_seconds': 180, 'version': 1, 'status': 'requested'}


def test_close_preserves_evidence_and_clears_monitoring(legacy_v3):
    db, client, farm, owner = legacy_v3
    animal, device = register_animal(client), register_device(client)
    assignment_id = assign_collar(client, animal, device)
    reading = receive_packet(db, device, 1)
    db.commit()
    assert inventory_item(client, device)['assignment_id'] == str(assignment_id)
    event = db.scalar(select(Event).where(Event.device_id == device, Event.condition == 'active'))
    assert event.telemetry_id == reading.id
    closed = client.post(f'/api/v1/assignments/{assignment_id}/close')
    assert closed.status_code == 200, closed.text
    db.expire_all()
    cutoff = datetime.fromisoformat(closed.json()['valid_to'])
    assert db.get(Assignment, assignment_id).valid_to == cutoff
    assert event.condition == 'resolved' and event.attention == 'pending'
    assert event.telemetry_id == reading.id and event.detail['resolution_reason'] == 'assignment_closed'
    assert db.scalar(select(Audit).where(Audit.object_id == str(event.id), Audit.action == 'resolved'))
    state = db.get(AnimalState, animal)
    assert state.telemetry_id is None and state.position_telemetry_id is None and state.observed_at is None
    assert state.geofence_status == 'unknown' and state.outside_count == 0
    assert db.get(Telemetry, reading.id).assignment_id == assignment_id and reading.animal_id == animal
    assert client.get(f'/api/v1/animals/{animal}').json()['collar_assignment'] is None
    assert client.get(f'/api/v1/animals/{animal}/assignments').json()['items'][0]['active'] is False
    assert inventory_item(client, device)['assignment_id'] is None
    later = receive_packet(db, device, 2, observed_at=cutoff)
    assert later.animal_id is None and later.assignment_id is None
    db.commit()
    assert client.post(f'/api/v1/assignments/{assignment_id}/close').status_code == 409
    audit = db.scalar(select(Audit).where(Audit.object_id == str(assignment_id), Audit.action == 'close'))
    assert audit.farm_id == farm.id and audit.actor_id == owner.id
    assert datetime.fromisoformat(audit.after['valid_to']) == cutoff


def test_close_checks_effective_time_and_already_attributed_readings(legacy_v3):
    db, client, _, _ = legacy_v3
    animal, device = register_animal(client), register_device(client)
    assignment_id = assign_collar(client, animal, device)
    assignment = db.get(Assignment, assignment_id)
    reading = receive_packet(db, device, 1)
    db.commit()
    route = f'/api/v1/assignments/{assignment_id}/close'
    invalid = client.post(route, json={'effective_at': assignment.valid_from.replace(tzinfo=None).isoformat()})
    assert invalid.status_code == 422, invalid.text
    future = client.post(route, json={'effective_at': (utcnow() + timedelta(seconds=2)).isoformat()})
    assert future.status_code == 422, future.text
    for at in (assignment.valid_from - timedelta(seconds=1), assignment.valid_from, reading.observed_at):
        result = client.post(route, json={'effective_at': at.isoformat()})
        assert result.status_code == 409, result.text
    assert 'lecturas históricas' in result.json()['detail']
    assert assignment.valid_to is None
    accepted = utcnow()
    valid = client.post(route, json={'effective_at': accepted.isoformat()})
    assert valid.status_code == 200, valid.text
    assert datetime.fromisoformat(valid.json()['valid_to']) == accepted


def test_inventory_lifecycle_requires_owner_active_farm_and_csrf(v3):
    owner = v3.client('owner')
    device = register_device(owner)
    assignment_id = assign_collar(owner, v3.animals['owner'].id, device)
    close = f'/api/v1/assignments/{assignment_id}/close'
    inventory = f'/api/v1/devices/{device}'
    operations = [('POST', close, {}), ('PATCH', inventory, {'enabled': False}), ('DELETE', inventory, None)]
    for role in ('worker', 'vet', 'viewer', 'other_owner'):
        client = v3.client(role)
        for method, route, payload in operations:
            assert client.request(method, route, json=payload).status_code == 403
    for method, route, payload in operations:
        assert owner.request(method, route, json=payload, headers={'X-CSRF-Token': 'invalid'}).status_code == 403
    admin = v3.client('admin', login=False)
    challenge = admin.post('/api/v1/auth/login', json={'username': v3.users['admin'].username, 'password': PASSWORD}).json()
    assert challenge['mfa_required'] and admin.post(close).status_code == 401
    verified = admin.post('/api/v1/auth/mfa/verify', json={
        'challenge_token': challenge['challenge_token'], 'code': totp(challenge['secret']),
    })
    assert verified.status_code == 200, verified.text
    admin.headers['X-CSRF-Token'] = verified.json()['csrf_token']
    assert admin.post(close).status_code == 403
    context = admin.post('/api/v1/auth/context', json={'farm_id': str(v3.farms['owner'].id)})
    assert context.status_code == 200, context.text
    admin.headers['X-CSRF-Token'] = context.json()['csrf_token']
    assert admin.post(close).status_code == 200
    assert admin.patch(inventory, json={'enabled': False}).status_code == 200
    unused = register_device(owner)
    assert admin.delete(f'/api/v1/devices/{unused}').status_code == 204


def test_retire_requires_close_and_stops_operational_monitoring(legacy_v3):
    db, client, _, owner = legacy_v3
    animal, device_id = register_animal(client), register_device(client)
    assignment_id = assign_collar(client, animal, device_id)
    route = f'/api/v1/devices/{device_id}'
    denied = client.patch(route, json={'enabled': False})
    assert denied.status_code == 409, denied.text
    assert db.get(Device, device_id).enabled
    assert client.post(f'/api/v1/assignments/{assignment_id}/close').status_code == 200
    device = db.get(Device, device_id)
    condition(db, device, None, 'communication_timeout', True, at=utcnow())
    db.commit()
    retired = client.patch(route, json={'enabled': False})
    assert retired.status_code == 200 and not retired.json()['enabled']
    db.expire_all()
    event = db.scalar(select(Event).where(Event.device_id == device_id, Event.type == 'communication_timeout'))
    assert event.condition == 'resolved'
    check_timeouts(db, utcnow() + timedelta(hours=2))
    assert event.condition == 'resolved'
    with pytest.raises(HTTPException) as rejected:
        receive_packet(db, device_id, 1)
    assert rejected.value.status_code == 422
    db.commit()
    reactivated = client.patch(route, json={'enabled': True})
    assert reactivated.status_code == 200 and reactivated.json()['enabled']
    assert reactivated.json()['assignment_id'] is None
    assert receive_packet(db, device_id, 2).animal_id is None
    assert len(db.scalars(select(Audit).where(Audit.object_id == str(device_id), Audit.action == 'set_enabled',
                                              Audit.actor_id == owner.id)).all()) == 2


@pytest.mark.parametrize('kind', ['assignments', 'telemetry', 'maintenance', 'config'])
def test_device_history_prevents_deletion(legacy_v3, kind):
    db, client, farm, owner = legacy_v3
    device = register_device(client)
    assert inventory_item(client, device)['can_delete']
    if kind == 'assignments':
        assignment_id = assign_collar(client, register_animal(client), device)
        assert client.post(f'/api/v1/assignments/{assignment_id}/close').status_code == 200
    elif kind == 'telemetry':
        assert receive_packet(db, device, 1).assignment_id is None
    elif kind == 'maintenance':
        db.add(Maintenance(id=uuid4(), farm_id=farm.id, device_id=device, kind='inspection',
                           responsible_id=owner.id, result='Inspección QA'))
    else:
        config = client.post(f'/api/v1/devices/{device}/config', json={'interval_seconds': 60, 'expected_version': 0})
        assert config.status_code == 201, config.text
    db.commit()
    assert not inventory_item(client, device)['can_delete']
    deleted = client.delete(f'/api/v1/devices/{device}')
    assert deleted.status_code == 409 and 'historial' in deleted.json()['detail']
    assert db.get(Device, device) is not None


def test_delete_approved_collar_preserves_candidate_receipt_and_audit(v3, monkeypatch):
    monkeypatch.setattr(settings(), 'app_env', 'development')
    farm = v3.farms['owner']
    farm.environment = 'development'
    v3.db.commit()
    owner = v3.client('owner')
    capture = v3.client('owner', login=False)
    hardware_id = f'qa-{uuid4()}'
    packet = {'hardware_id': hardware_id, 'session_id': 'qa-radio', 'seq': 1,
              'observed_at': utcnow().isoformat(), 'gnss_valid': False, 'source': 'academic'}
    headers = {'X-Ingest-Key': settings().ingest_key, 'X-Farm-ID': str(farm.id)}
    ingest = '/api/v1/ingest/telemetry'
    detected = capture.post(ingest, json=packet, headers=headers)
    assert detected.status_code == 201, detected.text
    receipt = detected.json()
    candidates = '/api/v1/v3/device-candidates'
    approved = owner.post(f"{candidates}/{receipt['id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    device = UUID(approved.json()['device']['id'])
    assert approved.json()['device']['can_delete']
    assert owner.delete(f'/api/v1/devices/{device}').status_code == 204
    assert v3.db.get(Device, device) is None
    dismissed = owner.get(candidates, params={'status': 'dismissed'}).json()['items']
    assert [item['id'] for item in dismissed] == [receipt['id']]
    assert capture.post(ingest, json=packet, headers=headers).json() == {**receipt, 'duplicate': True}
    fresh = capture.post(ingest, json={**packet, 'seq': 2}, headers=headers)
    assert fresh.status_code == 201 and fresh.json()['id'] != receipt['id']
    assert v3.db.scalar(text('SELECT count(*) FROM device_candidate_captures WHERE farm_id=:farm'), {'farm': farm.id}) == 2
    audit = v3.db.scalar(select(Audit).where(Audit.object_id == str(device), Audit.action == 'delete'))
    assert audit.actor_id == v3.users['owner'].id and audit.before['hardware_id'] == hardware_id
    reversal = v3.db.scalar(select(Audit).where(Audit.object_id == receipt['id'], Audit.action == 'dismiss'))
    assert reversal.after['reason'] == 'inventory_deleted'
