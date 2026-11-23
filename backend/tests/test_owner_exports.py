import csv
from datetime import date, datetime, timezone
from io import BytesIO, StringIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from geocattle import v3_owner_exports as reports
from geocattle.db import get_db
from geocattle.kpi_metrics import Evidence, calculate_metrics
from geocattle.security import current_user


BASE = '/api/v1/v3/owner-exports'
NOW = datetime(2026, 11, 23, 1, tzinfo=timezone.utc)


def by_code(evidence):
    return {item.code: item for item in calculate_metrics(evidence, '17 a 23')}


def test_kpi_calculations_do_not_certify_auxiliary_measurements():
    items = by_code(Evidence(packets=96, unique_packets=95, expected_packets=100, extra_gateway_receptions=2,
                             fresh_positions=18, position_samples=20, event_samples=12, processing_p50=0.5,
                             processing_p95=2, requests=100, errors=1, request_p95_ms=1000,
                             battery_devices=2, battery_delta_mv=-24, exits=3, animal_hours=240))
    assert len(items) == 12
    assert (items['K01'].value, items['K01'].numerator, items['K01'].status) == (95, 95, 'Sí')
    assert (items['K02'].value, items['K02'].status) == (90, 'No')
    assert (items['K03'].value, items['K03'].secondary_value, items['K03'].status) == (2, 0.5, 'Sí')
    assert (items['K05'].value, items['K05'].secondary_value, items['K05'].status) == (98.9583, 1, 'No')
    assert by_code(Evidence(packets=1, unique_packets=1))['K05'].status == 'Sin datos'
    assert 'gateways: 2' in items['K05'].observation
    assert (items['K06'].value, items['K06'].secondary_value, items['K06'].status) == (1, 1, 'No')
    assert (items['K08'].value, items['K08'].status) == (-24, 'Sin datos')
    assert (items['K09'].value, items['K09'].status) == (1.25, 'Sin datos')
    for code in ('K04', 'K07', 'K10', 'K11', 'K12'):
        assert items[code].value is None and items[code].status == 'Sin datos'
        assert 'Requiere ensayo / no medido por el sistema' in items[code].observation


def test_null_zero_and_compliance_before_rounding():
    assert all(item.value is None and item.status == 'Sin datos' for item in by_code(Evidence()).values())
    items = by_code(Evidence(requests=100, request_p95_ms=1000.01, position_samples=1, animal_hours=10))
    assert (items['K06'].value, items['K06'].status, items['K06'].secondary_value) == (1, 'No', 0)
    assert (items['K09'].value, items['K09'].numerator) == (0, 0)
    assert (items['K02'].value, items['K02'].status) == (0, 'No')


@pytest.fixture
def api_client(monkeypatch):
    farm = SimpleNamespace(id=uuid4(), account_id=uuid4(), name='Predio QA', timezone='America/Santiago', environment='simulation')
    actor = SimpleNamespace(farm_id=farm.id, role='owner')
    app = FastAPI()
    app.include_router(reports.router)
    app.dependency_overrides[current_user] = lambda: actor

    def get_farm(model, ident):
        assert ident == farm.id
        return farm

    app.dependency_overrides[get_db] = lambda: SimpleNamespace(get=get_farm)

    def evidence(db, params):
        assert params['farm'] == farm.id and params['account'] == farm.account_id and params['simulation']
        return Evidence(unique_packets=1, packets=1, expected_packets=1)

    def query_rows(db, sql, **params):
        assert params['farm'] == farm.id and params['simulation']
        if sql == reports.COLLARS:
            return [{'id': uuid4(), 'hardware_id': '=collar', 'name': 'Collar 1', 'diio': '00123',
                     'status': 'Instalado', 'period_readings': 1}]
        assert sql == reports.GATEWAYS
        return [{'id': uuid4(), 'name': 'Gateway 1', 'latitude': -38.75, 'status': 'Archivado'}]

    monkeypatch.setattr(reports, 'utcnow', lambda: NOW)
    monkeypatch.setattr(reports, 'evidence_for', evidence)
    monkeypatch.setattr(reports, 'rows', query_rows)
    monkeypatch.setattr(reports, 'one', lambda db, sql, **params:
                        dict(collars=1, gateways=1, withdrawn_collars=0, withdrawn_gateways=1))
    with TestClient(app) as client:
        yield client, actor


def test_role_scope_and_required_session(api_client):
    client, actor = api_client
    for role in ('worker', 'veterinarian', 'viewer'):
        actor.role = role
        assert client.get(f'{BASE}/metricas').status_code == 403
        assert client.get(f'{BASE}/dispositivos?format=xlsx').status_code == 403
    actor.role = 'admin'
    assert client.get(f'{BASE}/metricas').status_code == 200
    assert client.get(f'{BASE}/metricas?farm_id={uuid4()}').json()['farm_id'] == str(actor.farm_id)
    actor.farm_id = None
    assert client.get(f'{BASE}/metricas').status_code == 409
    client.app.dependency_overrides.pop(current_user)
    assert client.get(f'{BASE}/metricas').status_code == 401


def test_period_defaults_presets_and_limits(api_client):
    client, _ = api_client
    response = client.get(f'{BASE}/metricas?days=7')
    data = response.json()
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert (data['start'], data['end'], data['origin']) == ('2026-11-16', '2026-11-22', 'Simulado')
    assert client.get(f'{BASE}/metricas').json()['start'] == '2026-11-22'
    assert client.get(f'{BASE}/metricas?days=30').json()['start'] == '2026-10-24'
    assert client.get(f'{BASE}/metricas?start=2026-01-01&end=2027-01-01').status_code == 200
    for query in ('days=14', 'days=7&start=2026-11-01', 'start=2026-11-22&end=2026-11-01',
                  'start=2026-01-01&end=2027-01-02', 'end=9999-12-31'):
        assert client.get(f'{BASE}/metricas?{query}').status_code == 422
    start, end, start_at, stop_at = reports.date_window(date(2026, 11, 1), date(2026, 11, 1), NOW, 'America/Santiago')
    assert start == end == date(2026, 11, 1)
    assert start_at.hour == stop_at.hour == 3 and stop_at.day == 2


def test_inventory_and_download_formats(api_client):
    client, _ = api_client
    response = client.get(f'{BASE}/dispositivos?days=7')
    data = response.json()
    assert data['summary']['withdrawn_gateways'] == 1 and data['collars'][0]['diio'] == '00123'
    assert data['gateways'][0]['status'] == 'Archivado'
    response = client.get(f'{BASE}/dispositivos?days=7&format=csv')
    assert response.status_code == 200 and response.content.startswith(b'\xef\xbb\xbf')
    assert 'geocattle-dispositivos-predio-qa-2026-11-16-2026-11-22.csv' in response.headers['content-disposition']
    collar, gateway = csv.DictReader(StringIO(response.content.decode('utf-8-sig')), delimiter=';')
    assert (collar['Tipo'], collar['Origen'], collar['ID de hardware'], collar['DIIO vigente']) == ('Collar', 'Simulado', "'=collar", '00123')
    assert (gateway['Tipo'], gateway['Latitud'], gateway['DIIO vigente']) == ('Gateway', '-38,75', '')
    response = client.get(f'{BASE}/metricas?days=7&format=csv')
    exported = list(csv.DictReader(StringIO(response.content.decode('utf-8-sig')), delimiter=';'))
    assert len(exported) == 12 and exported[0]['Cumple'] == 'Sí' and exported[0]['Origen'] == 'Simulado'
    assert client.get(f'{BASE}/general?format=csv').status_code == 422
    for kind, names in (('metricas', ['Métricas']), ('dispositivos', ['Collares', 'Gateways']),
                        ('general', ['Métricas', 'Collares', 'Gateways'])):
        response = client.get(f'{BASE}/{kind}?format=xlsx')
        assert response.status_code == 200
        book = load_workbook(BytesIO(response.content))
        assert book.sheetnames == [*names, 'Metadatos']
        assert all(book[name].freeze_panes == 'A2' for name in book.sheetnames)
        if 'Collares' in names:
            assert book['Collares']['A2'].data_type == 's' and book['Collares']['A2'].value == '=collar'
            assert book['Collares']['M2'].value == '00123'
