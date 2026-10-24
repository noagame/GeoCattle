"""KPI endpoint remains usable on operating systems without Unix load averages."""
import os

import pytest

from geocattle import v3_api
from test_v3_api import v3
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
