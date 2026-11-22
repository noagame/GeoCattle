"""CSV and preview contracts for reports scoped to the active farm."""
import csv
import io
import os
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from geocattle.models import Assignment, Device, Event, utcnow
from geocattle.settings import settings
from test_v3_api import VACCINE_TREATMENT, body, v3


pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS de QA')
BASE = '/api/v1/v3/animal-reports'
CHANGES = '/api/v1/v3/changes'


def read_csv(response):
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'text/csv; charset=utf-8'
    assert response.headers['content-disposition'].startswith('attachment; filename="geocattle-')
    assert response.content.startswith(b'\xef\xbb\xbf')
    return list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'), newline='')))


def test_inventory_scope_permissions_and_empty_reports(v3):
    owner = v3.client('owner')
    other = v3.client('other_owner')
    invited = ('worker', 'vet')
    animal_id = str(v3.animals['owner'].id)
    expected_diio = v3.animals['owner'].diio
    inventory = owner.get(f'{BASE}/inventario').json()
    assert inventory['total'] == 1 and inventory['items'][0][0] == expected_diio
    assert inventory['start'] is None and inventory['end'] is None
    assert other.get(f'{BASE}/inventario').json()['items'][0][0] == v3.animals['other_owner'].diio
    assert other.get(f'{BASE}/inventario', params={'animal_id': animal_id, 'format': 'csv'}).status_code == 403
    assert v3.client('viewer').get(f'{BASE}/sanidad').status_code == 403
    assert v3.client('owner', login=False).get(f'{BASE}/sanidad', params={'format': 'csv'}).status_code == 401
    for role in invited:
        assert len(read_csv(v3.client(role).get(f'{BASE}/inventario', params={'format': 'csv'}))) == 2
    assert owner.get(f'{BASE}/agenda', params={'start': '2026-01-01', 'end': '2025-01-01'}).status_code == 422
    for kind in ('sanidad', 'agenda', 'mediciones', 'observaciones', 'asignaciones', 'alertas', 'actividad'):
        response = owner.get(f'{BASE}/{kind}')
        assert response.status_code == 200, response.text
        report = response.json()
        assert report['total'] == 0 and report['items'] == []
        assert read_csv(owner.get(f'{BASE}/{kind}', params={'format': 'csv'})) == [report['columns']]


def test_daily_health_csv_includes_all_products_and_only_effective_events(v3, monkeypatch):
    vet = v3.client('vet')
    worker = v3.client('worker')
    farm = v3.farms['owner']
    zone = ZoneInfo(farm.timezone)
    day = utcnow().astimezone(zone).date() - timedelta(days=2)
    midnight = datetime.combine(day, time.min, zone)
    params = {'start': day.isoformat(), 'animal_id': str(v3.animals['owner'].id)}
    for at in (midnight - timedelta(seconds=1), midnight + timedelta(days=1)):
        outside = vet.post(CHANGES, json=body(v3, 'health_record', {
            'event_type': 'observation', 'description': 'Fuera del día elegido', 'occurred_at': at.isoformat(),
        }))
        assert outside.status_code == 201, outside.text
    vaccination = {
        'event_type': 'vaccination', 'description': 'Registro original',
        'occurred_at': midnight.isoformat(),
        'treatments': [VACCINE_TREATMENT, {**VACCINE_TREATMENT, 'product_name': 'Producto B, prueba', 'batch_number': 'LOTE-B'}],
    }
    original = vet.post(CHANGES, json=body(v3, 'health_record', vaccination))
    assert original.status_code == 201, original.text
    correction = vet.post(CHANGES, json=body(v3, 'health_record', {
        **vaccination, 'operation': 'correct', 'target_event_id': original.json()['entity_id'],
        'description': '=texto de prueba',
    }))
    assert correction.status_code == 201, correction.text
    pending = worker.post(CHANGES, json=body(v3, 'health_record', {**vaccination, 'description': 'Propuesta pendiente'}))
    assert pending.status_code == 201 and pending.json()['status'] == 'pending'
    response = worker.get(f'{BASE}/sanidad', params=params)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report['start'] == report['end'] == day.isoformat()
    assert report['timezone'] == farm.timezone and report['total'] == 2
    exported = read_csv(worker.get(f'{BASE}/sanidad', params={**params, 'format': 'csv'}))
    records = [dict(zip(exported[0], row, strict=True)) for row in exported[1:]]
    assert exported[0] == report['columns']
    assert {row['Evento ID'] for row in records} == {correction.json()['entity_id']}
    assert {row['Lote'] for row in records} == {'LOTE-QA', 'LOTE-B'}
    assert {row['Descripción'] for row in records} == {"'=texto de prueba"}
    assert {row['Fecha del evento'] for row in records} == {midnight.isoformat()}
    assert {row['Autor'] for row in records} == {v3.users['vet'].full_name}
    monkeypatch.setattr('geocattle.v3_animal_reports.CSV_LIMIT', 1)
    assert worker.get(f'{BASE}/sanidad', params={**params, 'format': 'csv'}).status_code == 422


def test_reports_export_records_from_their_original_sources(v3):
    owner = v3.client('owner')
    animal = v3.animals['owner']
    hardware_id = f'qa-{uuid4().hex}'
    saved_device = owner.post('/api/v1/devices', json={
        'name': 'Collar QA', 'hardware_id': hardware_id, 'transport': 'academic',
    })
    assert saved_device.status_code == 201, saved_device.text
    device = saved_device.json()['id']
    assigned = owner.post('/api/v1/assignments', json={'animal_id': str(animal.id), 'device_id': device})
    assert assigned.status_code == 201, assigned.text
    for action, payload in (
        ('animal_profile', {'weight_kg': 100, 'height_cm': 95}),
        ('animal_report', {'description': 'Observación QA'}),
        ('health_schedule', {'kind': 'checkup', 'description': 'Control QA', 'due_at': utcnow().isoformat()}),
    ):
        result = owner.post(CHANGES, json=body(v3, action, payload))
        assert result.status_code == 201, result.text
    source = 'sim' if v3.farms['owner'].environment == 'simulation' else 'academic'
    captured = owner.post('/api/v1/ingest/telemetry', headers={'X-Ingest-Key': settings().ingest_key}, json={
        'hardware_id': hardware_id, 'session_id': 'qa', 'seq': 1, 'observed_at': utcnow().isoformat(),
        'gnss_valid': False, 'source': source, 'quality': {'movement_state': 'moving'},
    })
    assert captured.status_code == 201, captured.text
    v3.db.add(Event(farm_id=v3.farms['owner'].id, animal_id=animal.id, device_id=device,
                    type='escape', severity='critical'))
    v3.db.commit()

    expected = {
        'inventario': ('Collar vigente', hardware_id),
        'agenda': ('Descripción', 'Control QA'),
        'mediciones': ('Peso (kg)', '100'),
        'observaciones': ('Descripción', 'Observación QA'),
        'asignaciones': ('Identificador del collar', hardware_id),
        'alertas': ('Tipo', 'escape'),
        'actividad': ('Muestras en movimiento', '1'),
    }
    for kind, (column, value) in expected.items():
        table = read_csv(owner.get(f'{BASE}/{kind}', params={'format': 'csv'}))
        assert len(table) == 2, (kind, table)
        row = dict(zip(table[0], table[1], strict=True))
        assert row['DIIO'] == animal.diio and row[column] == value


def test_owner_indicators_use_farm_time_and_show_coverage(v3, monkeypatch):
    owner = v3.client('owner')
    farm = v3.farms['owner']
    animal = v3.animals['owner']
    farm.timezone = 'America/Santiago'
    now = utcnow().astimezone(ZoneInfo(farm.timezone))
    day = now.date() - timedelta(days=2)
    midnight = datetime.combine(day, time.min, now.tzinfo)
    collar = Device(farm_id=farm.id, hardware_id=f'qa-{uuid4().hex}', name='QA', transport='academic')
    spare = Device(farm_id=farm.id, hardware_id=f'qa-{uuid4().hex}', name='En inventario', transport='academic')
    v3.db.add_all([collar, spare])
    v3.db.flush()
    assignment = Assignment(farm_id=farm.id, animal_id=animal.id, device_id=collar.id, valid_from=midnight - timedelta(hours=1))
    v3.db.add(assignment)
    v3.db.flush()
    fence = v3.db.execute(text("""
        INSERT INTO sectors(id,farm_id,name,active) VALUES(gen_random_uuid(),:farm,'Sector QA',true) RETURNING id
    """), {'farm': farm.id}).scalar_one()
    geofence = v3.db.execute(text("""
        INSERT INTO geofences(id,farm_id,sector_id,name,version,geometry,active,created_at)
        VALUES(gen_random_uuid(),:farm,:sector,'Potrero QA',1,ST_GeomFromText(
            'POLYGON((-72 -38,-71 -38,-71 -37,-72 -37,-72 -38))',4326),true,:start) RETURNING id
    """), {'farm': farm.id, 'sector': fence, 'start': assignment.valid_from}).scalar_one()
    keys = {'farm': farm.id, 'animal': animal.id, 'device': collar.id, 'assignment': assignment.id, 'fence': geofence}
    v3.db.execute(text("""
        INSERT INTO pasture_assignments(id,farm_id,animal_id,geofence_id,valid_from)
        VALUES(gen_random_uuid(),:farm,:animal,:fence,:start)
    """), {**keys, 'start': assignment.valid_from})
    v3.db.execute(text("INSERT INTO farm_features(farm_id,feature_code) VALUES(:farm,'monitoring')"), keys)
    source, excluded_source = ('sim', 'academic') if farm.environment == 'simulation' else ('academic', 'sim')
    v3.db.execute(text("""
        INSERT INTO telemetry(id,farm_id,animal_id,device_id,assignment_id,session_id,seq,observed_at,received_at,
                              gnss_valid,longitude,latitude,point,source,quality)
        SELECT gen_random_uuid(),:farm,:animal,:device,:assignment,'qa-indicators',n,
               :midnight+n*interval '1 minute',:received,true,-72,-38,ST_SetSRID(ST_MakePoint(-72,-38),4326),
               CASE WHEN n=12 THEN :excluded_source ELSE :source END,
               jsonb_build_object('movement_state',CASE WHEN n<=6 OR n=12 THEN 'moving' WHEN n<=10 THEN 'rest' ELSE 'unknown' END)
        FROM generate_series(1,12) AS n
    """), {**keys, 'midnight': midnight, 'received': now, 'source': source, 'excluded_source': excluded_source})
    for event_type, at in [('escape', midnight), ('low_battery', midnight), ('escape', midnight - timedelta(seconds=1))]:
        closed = at < midnight
        v3.db.add(Event(farm_id=farm.id, animal_id=animal.id, device_id=collar.id, geofence_id=geofence,
                        type=event_type, severity='critical', opened_at=at, detail={'geofence_version': 1},
                        condition='resolved' if closed else 'active', resolved_at=midnight if closed else None))
    v3.db.commit()
    monkeypatch.setattr('geocattle.v3_animal_reports.utcnow', lambda: now)
    params = {'start': day.isoformat(), 'end': (day + timedelta(days=1)).isoformat()}

    def report(kind, filters=None):
        response = owner.get(f'{BASE}/{kind}', params=filters)
        assert response.status_code == 200, response.text
        result = response.json()
        exported = read_csv(owner.get(f'{BASE}/{kind}', params={**(filters or {}), 'format': 'csv'}))
        assert exported == [result['columns'], *result['items']]
        return result['items']

    totals = {row[0]: row[1] for row in report('totales')}
    assert totals == {'Bovinos activos': '1', 'Collares inventariados': '2', 'Collares con asignación vigente': '1',
                      'Módulos de software habilitados': '1', 'Monitoreo IoT': '1'}
    for grain in ('day', 'week', 'month'):
        series = report('serie-alertas', {**params, 'grain': grain, 'alert_type': 'escape'})
        assert series[0][0] == params['start'] and series[-1][1] == params['end']
        assert sum(int(row[3]) for row in series) == 1
        assert sum(int(row[4]) for row in series) == 1
    assert report('serie-alertas', params)[-1][3:] == ['0', '0', '1']
    assert report('ranking-movimiento', params) == [['1', animal.diio, animal.name, '60.00', '6', '10', '1', '2', 'Suficiente']]
    assert report('ranking-salidas', params) == [['1', animal.diio, animal.name, '1', 'Potrero QA (v1)', '11', '1', '2', 'Suficiente']]
    insufficient = {**params, 'end': now.date().isoformat()}
    for kind in ('ranking-movimiento', 'ranking-salidas'):
        row, = report(kind, insufficient)
        assert row[0] == '' and row[-1] == 'Insuficiente'
    for role in ('worker', 'vet', 'viewer'):
        assert v3.client(role).get(f'{BASE}/totales').status_code == 403
        assert v3.client(role).get(f'{BASE}/ranking-salidas', params={'format': 'csv'}).status_code == 403
    other = v3.client('other_owner').get(f'{BASE}/ranking-movimiento', params=params).json()['items']
    assert other[0][1] == v3.animals['other_owner'].diio and other[0][-1] == 'Insuficiente'
