"""Enrollment, bus_v1 isolation and preservation of radio history."""
from datetime import timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from geocattle.models import utcnow
from geocattle.settings import settings
from test_gateway_management import create, login
from test_v3_api import development_v3, v3

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requires isolated PostgreSQL/PostGIS')
CANDIDATES = '/api/v1/v3/gateway-candidates'
GATEWAYS = '/api/v1/v3/gateways'
INGEST = '/api/v1/ingest/telemetry'


def usb(node=None, **changes):
    return {'gateway_eui': uuid4().hex[:16], 'node_id': node, 'firmware': 'gateway-test', **changes}


def capture_headers(farm):
    return {'X-Ingest-Key': settings().ingest_key, 'X-Farm-ID': str(farm.id)}


def send(client, path, body, status, **kwargs):
    response = client.post(path, json=body, **kwargs)
    assert response.status_code == status, response.text
    return response.json()


def bus_reading(hardware_id, seq, node=1, path=6, observed_at=None):
    return {
        'source': 'academic', 'hardware_id': hardware_id, 'session_id': 'BUSQA01', 'seq': seq,
        'observed_at': (observed_at or utcnow()).isoformat(), 'gnss_valid': False,
        'quality': {'period_ms': 45000, 'radio': {'rssi_dbm': -81.5, 'snr_db': 6.25},
                    'transport': {'bus_version': 1, 'origin_gateway': node, 'path': path,
                                  'hops': path.bit_count(), 'radio_scope': 'collar_to_first_receiver'}},
    }


@pytest.mark.parametrize('role', ['owner', 'admin'])
def test_usb_reserves_confirms_and_audits_in_active_farm(development_v3, role):
    fixtures = development_v3
    actor = login(fixtures, role)
    other = fixtures.client('other_owner')
    worker = fixtures.client('worker')
    service = fixtures.client('owner', login=False)
    body = usb()
    headers = capture_headers(fixtures.farms['owner'])
    send(service, CANDIDATES, body, 401)
    send(service, CANDIDATES, {**body, 'node_id': True}, 422, headers=headers)
    send(worker, CANDIDATES, body, 403)
    send(actor, CANDIDATES, body, 403, headers={'X-CSRF-Token': 'wrong'})
    initial = send(service, CANDIDATES, {**body, 'gateway_eui': body['gateway_eui'].upper()}, 201, headers=headers)
    assert initial['source'] == 'usb' and initial['gateway_eui'] == body['gateway_eui']
    updated = send(actor, CANDIDATES, body, 201, headers={'X-Farm-ID': str(fixtures.farms['other_owner'].id)})
    assert updated['id'] == initial['id'] and updated['seen_count'] == 2
    assert updated['first_seen_at'] == initial['first_seen_at']
    assert other.get(CANDIDATES).json() == {'items': []}
    assert worker.get(CANDIDATES).status_code == 403
    path = f"{CANDIDATES}/{initial['id']}"
    for suffix in ('reserve', 'approve', 'dismiss'):
        send(service, f'{path}/{suffix}', {}, 401, headers=headers)
        send(other, f'{path}/{suffix}', {}, 403)
        send(worker, f'{path}/{suffix}', {}, 403)
    send(actor, f'{path}/approve', {}, 409)
    reserved = send(actor, f'{path}/reserve', {}, 200)
    assert reserved['reserved_node_id'] == 1 and reserved['suggested_name'] == 'Gateway 01'
    assert reserved == send(actor, f'{path}/reserve', {}, 200)
    assert actor.get(GATEWAYS).json()['items'] == []
    confirm = {'confirmed_node_id': 1, 'confirmed_eui': body['gateway_eui']}
    send(actor, f'{path}/approve', {**confirm, 'latitude': -38.7}, 422)
    send(actor, f'{path}/approve', {**confirm, 'confirmed_node_id': 2}, 409)
    send(actor, f'{path}/approve', {**confirm, 'confirmed_eui': '0000000000000000'}, 409)
    approved = send(actor, f'{path}/approve', {**confirm, 'longitude': -72.64, 'latitude': -38.74}, 200)
    gateway = approved['gateway']
    assert (gateway['status'], gateway['node_id'], gateway['name'], gateway['longitude']) == ('installed', 1, 'Gateway 01', -72.64)
    assert approved['candidate']['status'] == 'approved' and approved['candidate']['reserved_node_id'] is None
    assert send(actor, f'{path}/approve', confirm, 200)['gateway']['id'] == gateway['id']
    send(actor, f'{path}/dismiss', {}, 409)
    assert 'EUI' in send(actor, CANDIDATES, body, 409)['detail']
    actions = fixtures.db.execute(text("SELECT action,actor_id FROM audit_log WHERE object_type='gateway_candidate' AND object_id=:id"),
                                  {'id': initial['id']}).all()
    assert set(actions) == {('detect', None), ('reserve', fixtures.users[role].id), ('approve', fixtures.users[role].id)}


def test_existing_node_is_kept_and_both_slots_are_reserved(development_v3):
    fixtures = development_v3
    owner = fixtures.client('owner')
    other = fixtures.client('other_owner')
    preferred = send(owner, CANDIDATES, usb(2), 201)
    assigned = f"{CANDIDATES}/{preferred['id']}"
    assert send(owner, f'{assigned}/reserve', {}, 200)['reserved_node_id'] == 2
    assert '02' in send(owner, CANDIDATES, usb(2), 409)['detail']
    unassigned = send(owner, CANDIDATES, usb(), 201)
    assert send(owner, f"{CANDIDATES}/{unassigned['id']}/reserve", {}, 200)['reserved_node_id'] == 1
    third = send(owner, CANDIDATES, usb(), 201)
    assert 'dos gateways' in send(owner, f"{CANDIDATES}/{third['id']}/reserve", {}, 409)['detail']
    unrelated = send(other, CANDIDATES, usb(2), 201)
    assert send(other, f"{CANDIDATES}/{unrelated['id']}/reserve", {}, 200)['reserved_node_id'] == 2
    dismissed = send(owner, f"{CANDIDATES}/{unassigned['id']}/dismiss", {}, 200)
    assert dismissed['status'] == 'dismissed' and dismissed['reserved_node_id'] is None
    assert send(owner, f"{CANDIDATES}/{third['id']}/reserve", {}, 200)['reserved_node_id'] == 1
    installed = send(owner, f'{assigned}/approve', {'confirmed_node_id': 2, 'confirmed_eui': preferred['gateway_eui']}, 200)['gateway']
    assert installed['node_id'] == 2 and installed['latitude'] is None
    archived = owner.request('DELETE', f"{GATEWAYS}/{installed['id']}", json={'expected_version': 1, 'confirm': True})
    assert archived.status_code == 200, archived.text
    send(owner, CANDIDATES, usb(2, gateway_eui=preferred['gateway_eui']), 409)
    replacement = send(owner, CANDIDATES, usb(2), 201)
    assert send(owner, f"{CANDIDATES}/{replacement['id']}/reserve", {}, 200)['reserved_node_id'] == 2


def test_radio_origin_deduplicates_and_links_only_new_first_hop_receptions(development_v3):
    fixtures = development_v3
    owner = fixtures.client('owner')
    foreign = fixtures.client('other_owner')
    service = fixtures.client('owner', login=False)
    headers = capture_headers(fixtures.farms['owner'])
    collar = f'GC-{uuid4().hex[:12]}'
    send(owner, '/api/v1/devices', {'hardware_id': collar, 'name': 'Collar QA', 'transport': 'academic'}, 201)
    direct = bus_reading(collar, 1, node=0, path=0)
    malformed = bus_reading(collar, 2, node=2, path=2)
    for packet in (direct, malformed):
        send(service, INGEST, packet, 201, headers=headers)
    assert owner.get(CANDIDATES).json() == {'items': []}
    first = bus_reading(collar, 3)
    result = send(service, INGEST, first, 201, headers=headers)
    assert send(service, INGEST, first, 201, headers=headers)['id'] == result['id']
    send(service, INGEST, bus_reading(collar, 4), 201, headers=headers)
    candidate, = owner.get(CANDIDATES).json()['items']
    assert (candidate['source'], candidate['gateway_eui'], candidate['node_id'], candidate['seen_count']) == ('radio', None, 1, 2)
    assert foreign.get(CANDIDATES).json() == {'items': []}
    gateway = send(owner, f"{CANDIDATES}/{candidate['id']}/approve", {}, 200)['gateway']
    assert gateway['latitude'] is None and gateway['gateway_eui'] is None
    history = f"{GATEWAYS}/{gateway['id']}/receptions"
    send(service, INGEST, first, 201, headers=headers)
    send(service, INGEST, bus_reading(collar, 5, observed_at=utcnow() - timedelta(minutes=30)), 201, headers=headers)
    assert owner.get(history).json()['total'] == 0
    new_packet = bus_reading(collar, 6)
    next_result = send(service, INGEST, new_packet, 201, headers=headers)
    assert not next_result['duplicate']
    date_before = owner.get(f"{GATEWAYS}/{gateway['id']}").json()['last_seen_at']
    assert send(service, INGEST, new_packet, 201, headers=headers)['duplicate']
    reception, = owner.get(history).json()['items']
    assert reception['telemetry_id'] == next_result['id'] and reception['gateway_id'] == gateway['id']
    assert float(reception['rssi_dbm']) == -81.5 and float(reception['snr_db']) == 6.25
    assert owner.get(f"{GATEWAYS}/{gateway['id']}").json()['last_seen_at'] == date_before
    assert owner.get(CANDIDATES).json() == {'items': []}
    assert foreign.get(history).status_code == 403


def test_unknown_collar_can_discover_gateway_and_existing_eui_can_bind_node(development_v3):
    fixtures = development_v3
    owner = fixtures.client('owner')
    service = fixtures.client('owner', login=False)
    existing = create(owner)
    collar = f'GC-{uuid4().hex[:12]}'
    packet = bus_reading(collar, 1, node=2, path=4)
    headers = capture_headers(fixtures.farms['owner'])
    assert send(service, INGEST, packet, 201, headers=headers)['status'] == 'candidate'
    assert send(service, INGEST, packet, 201, headers=headers)['duplicate']
    candidate, = owner.get(CANDIDATES).json()['items']
    assert candidate['node_id'] == 2 and candidate['seen_count'] == 1
    response = owner.patch(f"{GATEWAYS}/{existing['id']}", json={'expected_version': 1, 'node_id': 2})
    assert response.status_code == 200, response.text
    assert response.json()['node_id'] == 2
    assert owner.get(CANDIDATES).json() == {'items': []}
    candidate, = owner.get(CANDIDATES, params={'status': 'approved'}).json()['items']
    assert candidate['gateway_id'] == existing['id']


def test_usb_enriches_pending_radio_and_dismissed_radio_does_not_reappear(development_v3):
    fixtures = development_v3
    owner = fixtures.client('owner')
    service = fixtures.client('owner', login=False)
    headers = capture_headers(fixtures.farms['owner'])
    collar = f'GC-{uuid4().hex[:12]}'
    send(service, INGEST, bus_reading(collar, 1, node=1), 201, headers=headers)
    send(service, INGEST, bus_reading(collar, 2, node=2), 201, headers=headers)
    candidates = {item['node_id']: item for item in owner.get(CANDIDATES).json()['items']}
    enriched = send(owner, CANDIDATES, usb(1), 201)
    assert enriched['id'] == candidates[1]['id'] and enriched['source'] == 'usb' and enriched['seen_count'] == 2
    send(owner, f"{CANDIDATES}/{candidates[2]['id']}/dismiss", {}, 200)
    send(service, INGEST, bus_reading(collar, 3, node=2), 201, headers=headers)
    assert [item['id'] for item in owner.get(CANDIDATES).json()['items']] == [enriched['id']]
