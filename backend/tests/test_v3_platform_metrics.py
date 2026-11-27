"""KPI endpoint remains usable on operating systems without Unix load averages."""
import os
from uuid import uuid4

import pytest

from geocattle import v3_api
from geocattle.demo_farm import DEMO_FARM_ID
from geocattle.models import Farm, OwnerAccount
from test_v3_api import development_v3, v3
from test_v3_admin_filters import admin_client

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS V3 de prueba')


@pytest.mark.parametrize('unavailable', ['missing', 'oserror', 'not_implemented'])
def test_admin_kpis_report_unknown_load_without_failing_on_windows(v3, monkeypatch, unavailable):
    if unavailable == 'missing':
        monkeypatch.delattr(v3_api.os, 'getloadavg', raising=False)
    else:
        def unavailable_load():
            if unavailable == 'not_implemented':
                raise NotImplementedError('Load average is not available')
            raise OSError('Load average is not available')
        monkeypatch.setattr(v3_api.os, 'getloadavg', unavailable_load, raising=False)
    client = admin_client(v3)
    response = client.get('/api/v1/v3/admin/kpis')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['instance_resources']['load_1m'] is None
    assert data['instance_resources']['database_bytes'] > 0
    assert data['instance_resources']['disk_free_bytes'] >= 0
    assert data['farms'] >= 2 and data['users'] >= 6


def test_admin_kpis_preserve_available_load_measurement(v3, monkeypatch):
    monkeypatch.setattr(v3_api.os, 'getloadavg', lambda: (1.25, 0.75, 0.5), raising=False)
    client = admin_client(v3)
    response = client.get('/api/v1/v3/admin/kpis')
    assert response.status_code == 200, response.text
    assert response.json()['instance_resources']['load_1m'] == 1.25


def test_demonstration_context_preserves_farm_authorization_and_kpi_scope(development_v3):
    fixture = development_v3
    owner_account = fixture.db.get(OwnerAccount, fixture.farms['owner'].account_id)
    owner_account.max_farms = 1
    fixture.db.commit()

    admin = admin_client(fixture)
    api = '/api/v1/v3/admin/kpis'
    physical_total = admin.get(api).json()['farms']
    unrelated_id = uuid4()
    fixture.db.add_all([
        Farm(id=DEMO_FARM_ID, account_id=owner_account.id, environment='simulation', name='Demo QA'),
        Farm(id=unrelated_id, environment='simulation', name='Simulación independiente'),
    ])
    fixture.db.commit()

    owner = fixture.client('owner')
    ids = {f['id'] for f in owner.get('/api/v1/v3/farms').json()['items']}
    assert str(DEMO_FARM_ID) in ids and str(unrelated_id) not in ids
    context = '/api/v1/auth/context'
    assert owner.post(context, json={'farm_id': str(DEMO_FARM_ID)}).status_code == 200
    assert owner.get('/api/v1/dashboard').json()['farm']['environment'] == 'simulation'
    assert owner.get('/api/v1/hardware/receiver').json()['available'] is False
    other_owner = fixture.client('other_owner')
    assert other_owner.post(context, json={'farm_id': str(DEMO_FARM_ID)}).status_code == 403
    assert owner.post(context, json={'farm_id': str(unrelated_id)}).status_code == 403

    assert admin.get(api).json()['farms'] == physical_total + 1  # Solo la simulación no reservada.
    assert admin.get(api, params={'account_id': str(owner_account.id)}).json()['farms'] == 1
    assert admin.get(api, params={'farm_id': str(DEMO_FARM_ID)}).json()['farms'] == 1
