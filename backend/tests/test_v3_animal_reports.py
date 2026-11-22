"""Preview and export contracts for reports scoped to the active farm."""
import csv
import io
import os
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from sqlalchemy import text

from geocattle.models import Assignment, Device, Event, Telemetry, utcnow
from geocattle.settings import settings
from test_v3_api import VACCINE_TREATMENT, body, v3


pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS de QA')
BASE = '/api/v1/v3/animal-reports'
CHANGES = '/api/v1/v3/changes'


def read_csv(response, delimiter=','):
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'text/csv; charset=utf-8'
    assert response.headers['content-disposition'].startswith('attachment; filename="geocattle-')
    assert response.content.startswith(b'\xef\xbb\xbf')
    return list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'), newline=''), delimiter=delimiter))


def read_xlsx(response, title):
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert response.headers['content-disposition'].endswith('.xlsx"')
    with io.BytesIO(response.content) as content:
        book = load_workbook(content)
    assert book.sheetnames == [title, 'Metadatos']
    sheet = book[title]
    assert sheet.freeze_panes == 'A2'
    assert sheet.auto_filter.ref == sheet.dimensions
    assert all(cell.font.bold for cell in sheet[1])
    assert sheet.column_dimensions['A'].width > 12
    metadata = dict(book['Metadatos'].values)
    assert metadata['Campo'] == 'Valor'
    assert isinstance(metadata['Generado'], datetime)
    return sheet, metadata


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
    assert other.get(f'{BASE}/inventario', params={'animal_id': animal_id, 'format': 'xlsx'}).status_code == 403
    assert v3.client('viewer').get(f'{BASE}/inventario', params={'format': 'xlsx'}).status_code == 403
    assert v3.client('owner', login=False).get(f'{BASE}/inventario', params={'format': 'xlsx'}).status_code == 401
    sheet, metadata = read_xlsx(v3.client('vet').get(f'{BASE}/inventario', params={'format': 'xlsx'}), 'Inventario actual')
    assert list(list(sheet.values)[0]) == inventory['columns']
    assert sheet['A2'].value == expected_diio and sheet['D2'].value == 'Sí'
    assert metadata['Predio'] == v3.farms['owner'].name and metadata['Período'] == 'Corte actual'
    assert owner.get(f'{BASE}/agenda', params={'start': '2026-01-01', 'end': '2025-01-01'}).status_code == 422
    for kind, title in (('sanidad', 'Ficha sanitaria'), ('agenda', 'Agenda sanitaria'), ('mediciones', 'Mediciones'),
                        ('observaciones', 'Observaciones del rebaño'), ('asignaciones', 'Asignaciones de collares'),
                        ('alertas', 'Alertas por bovino'), ('actividad', 'Actividad diaria')):
        response = owner.get(f'{BASE}/{kind}')
        assert response.status_code == 200, response.text
        report = response.json()
        assert report['total'] == 0 and report['items'] == []
        assert read_csv(owner.get(f'{BASE}/{kind}', params={'format': 'csv'})) == [report['columns']]
        sheet, _ = read_xlsx(owner.get(f'{BASE}/{kind}', params={'format': 'xlsx'}), title)
        assert list(sheet.values) == [tuple(report['columns'])]


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
        'treatments': [VACCINE_TREATMENT, {**VACCINE_TREATMENT, 'product_name': 'Producto B; "prueba"',
                                           'batch_number': 'LOTE-B', 'dose_value': 1.25}],
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
    localized = read_csv(worker.get(f'{BASE}/sanidad', params={**params, 'format': 'csv', 'delimiter': 'semicolon'}), ';')
    assert localized[0] == report['columns']
    assert any(row[10] == 'Producto B; "prueba"' and row[13] == '1,25' for row in localized[1:])
    assert all(row[7] == "'=texto de prueba" for row in localized[1:])
    sheet, metadata = read_xlsx(worker.get(f'{BASE}/sanidad', params={**params, 'format': 'xlsx'}), 'Ficha sanitaria')
    assert sheet.max_row == 3
    assert sheet['D2'].is_date and sheet['D2'].value == midnight.replace(tzinfo=None)
    assert {sheet['N2'].value, sheet['N3'].value} == {1, 1.25}
    assert sheet['H2'].data_type == 's' and sheet['H2'].value == '=texto de prueba'
    assert {sheet['E2'].value, sheet['F2'].value} <= {'Vacunación', 'Registro', 'Corrección'}
    assert {row['Tipo'] for row in records} == {'Vacunación'}
    assert metadata['Bovino (ID)'] == params['animal_id']
    assert metadata['Zona horaria'] == farm.timezone
    assert metadata['Desde'].date() == metadata['Hasta'].date() == day
    for format in ('csv', 'xlsx'):
        monkeypatch.setattr('geocattle.v3_animal_reports.EXPORT_LIMIT', 2)
        assert worker.get(f'{BASE}/sanidad', params={**params, 'format': format}).status_code == 200
        monkeypatch.setattr('geocattle.v3_animal_reports.EXPORT_LIMIT', 1)
        assert worker.get(f'{BASE}/sanidad', params={**params, 'format': format}).status_code == 422


def test_telemetry_exports_share_the_scoped_day_and_collar_filters(v3, monkeypatch):
    viewer = v3.client('viewer')
    other = v3.client('other_owner')
    farm = v3.farms['owner']
    farm.timezone = 'America/Santiago'
    zone = ZoneInfo(farm.timezone)
    day = date(2026, 1, 11)
    start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    hardware_id = f'qa-{uuid4().hex}'
    source = 'sim' if farm.environment == 'simulation' else 'academic'
    collars = [Device(farm_id=owner.id, hardware_id=code, name='QA', transport='academic') for owner, code in
               ((farm, hardware_id), (farm, f'{hardware_id}-otro'), (v3.farms['other_owner'], f'{hardware_id}-ajeno'))]
    v3.db.add_all(collars)
    v3.db.flush()
    for seq, (collar, instant) in enumerate(((collars[0], start - timedelta(seconds=1)), (collars[0], start),
                                             (collars[0], start + timedelta(seconds=1)), (collars[0], start + timedelta(days=1)),
                                             (collars[1], start), (collars[2], start))):
        v3.db.add(Telemetry(farm_id=collar.farm_id, device_id=collar.id, session_id='qa-xlsx', seq=seq,
                            observed_at=instant, received_at=instant, gnss_valid=False, source=source,
                            activity_index=0.125, battery_mv=4000))
    v3.db.execute(text("SET TIME ZONE 'UTC'"))
    v3.db.commit()
    params = {'day': day.isoformat(), 'hardware_id': hardware_id}
    preview = viewer.get('/api/v1/hardware/telemetry', params=params).json()
    assert preview['total'] == 2
    endpoint = '/api/v1/reports/telemetry'
    xlsx = viewer.get(f'{endpoint}.xlsx', params=params)
    sheet, metadata = read_xlsx(xlsx, 'Telemetría')
    assert xlsx.headers['x-export-limit'] == '50000'
    assert xlsx.headers['content-disposition'] == f'attachment; filename="geocattle-telemetria-{day}.xlsx"'
    assert sheet.max_row == preview['total'] + 1
    assert [cell.value for cell in sheet[1]][:4] == ['DIIO', 'Bovino', 'Collar', 'Observado']
    assert sheet['C2'].value == hardware_id
    assert sheet['D2'].value == datetime.combine(day, time.min) and sheet['D2'].is_date
    assert sheet['H2'].value == 'No' and sheet['F2'].value is None
    assert sheet['J2'].value == 0.125 and sheet['J2'].data_type == 'n' and sheet['J2'].number_format == '0.000'
    assert sheet['K2'].value == 4000 and sheet['K2'].data_type == 'n'
    assert sheet['L2'].value in {'Simulado', 'Collar del prototipo'}
    assert metadata['Zona horaria'] == farm.timezone and metadata['Collar'] == hardware_id
    assert metadata['Hasta (exclusivo)'] == datetime.combine(day + timedelta(days=1), time.min)
    standard = read_csv(viewer.get(f'{endpoint}.csv', params=params))
    assert standard[0][:3] == ['animal_id', 'device_id', 'observed_at']
    assert datetime.fromisoformat(standard[1][2]) == start
    assert standard[1][6:10] == ['False', '', '0.125', '4000']
    localized = read_csv(viewer.get(f'{endpoint}.csv', params={**params, 'delimiter': 'semicolon'}), ';')
    assert localized[1][6:10] == ['No', '', '0,125', '4000']
    empty, metadata = read_xlsx(other.get(f'{endpoint}.xlsx', params=params), 'Telemetría')
    assert empty.max_row == 1 and metadata['Predio'] == v3.farms['other_owner'].name
    for format in ('csv', 'xlsx'):
        assert other.get(f'{endpoint}.{format}', params={'animal_id': v3.animals['owner'].id}).status_code == 403
        assert v3.client('owner', login=False).get(f'{endpoint}.{format}').status_code == 401
        assert viewer.get(f'{endpoint}.{format}', params={**params, 'start': start.isoformat()}).status_code == 422
    monkeypatch.setattr('geocattle.main.EXPORT_LIMIT', 1)
    capped = viewer.get(f'{endpoint}.xlsx', params=params)
    limited, metadata = read_xlsx(capped, 'Telemetría')
    assert capped.headers['x-export-limit'] == '1' and metadata['Máximo de filas'] == 1
    assert limited.max_row == 2 and limited['D2'].value == sheet['D2'].value
    assert read_csv(viewer.get(f'{endpoint}.csv', params=params)) == standard[:2]


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
        'alertas': ('Tipo', 'Fuera de geocerca'),
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
    titles = {'totales': 'Totales del predio', 'serie-alertas': 'Alertas por período',
              'ranking-movimiento': 'Ranking de movimiento', 'ranking-salidas': 'Ranking de salidas de geocerca'}

    def report(kind, filters=None):
        response = owner.get(f'{BASE}/{kind}', params=filters)
        assert response.status_code == 200, response.text
        result = response.json()
        exported = read_csv(owner.get(f'{BASE}/{kind}', params={**(filters or {}), 'format': 'csv'}))
        assert exported == [result['columns'], *result['items']]
        sheet, metadata = read_xlsx(owner.get(f'{BASE}/{kind}', params={**(filters or {}), 'format': 'xlsx'}), titles[kind])
        assert list(list(sheet.values)[0]) == result['columns'] and sheet.max_row == result['total'] + 1
        if kind == 'totales':
            assert sheet['B2'].data_type == 'n' and metadata['Período'] == 'Corte actual'
        if kind == 'serie-alertas':
            assert sheet['A2'].is_date and sheet['D2'].data_type == 'n'
            assert metadata['Agrupación'] in ('Día', 'Semana', 'Mes') and metadata['Tipo de alerta']
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
        assert v3.client(role).get(f'{BASE}/ranking-salidas', params={'format': 'xlsx'}).status_code == 403
    other = v3.client('other_owner').get(f'{BASE}/ranking-movimiento', params=params).json()['items']
    assert other[0][1] == v3.animals['other_owner'].diio and other[0][-1] == 'Insuficiente'
