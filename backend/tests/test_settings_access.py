"""Farm rule configuration: permissions, versioning and preventive field-validation guard.

Uses only the existing V3 external-rollback fixture and TEST_DATABASE_URL.
"""
import os

import pytest
from sqlalchemy import text

from geocattle.models import RuleSettings
from geocattle.settings import settings
from test_v3_api import v3
from test_v3_admin_filters import admin_client

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS V3 de prueba')


@pytest.fixture(autouse=True)
def unvalidated_preventive_sensors(monkeypatch):
    monkeypatch.setattr(settings(), 'preventive_rules_validated', False)


def rule_payload(version=1, **overrides):
    return {
        'expected_version': version, 'battery_low_mv': 3450,
        'temperature_high_c': 41.1, 'activity_low_threshold': 0.025,
        'activity_window_minutes': 15, 'proximity_meters': 25,
        'temperature_enabled': False, 'activity_enabled': False, 'proximity_enabled': True,
        **overrides,
    }


def selected_admin(v3):
    client = admin_client(v3)
    response = client.post('/api/v1/auth/context', json={'farm_id': str(v3.farms['owner'].id)})
    assert response.status_code == 200, response.text
    return client


def audit_updates(v3, farm=None):
    return v3.db.execute(text("SELECT before,after FROM audit_log WHERE farm_id=:farm AND object_type='rule_settings' AND action='update' ORDER BY at"),
        {'farm': farm or v3.farms['owner'].id}).mappings().all()


@pytest.mark.parametrize('profile,can_edit', [('owner', True), ('admin', True), ('worker', False), ('vet', False), ('viewer', False)])
def test_settings_capabilities_and_write_permissions_match_actor(v3, profile, can_edit):
    client = selected_admin(v3) if profile == 'admin' else v3.client(profile)
    before = client.get('/api/v1/settings')
    assert before.status_code == 200, before.text
    capabilities = before.json()['capabilities']
    assert capabilities == {
        'can_edit': can_edit, 'environment': settings().app_env,
        'preventive_rules_validated': False,
        'preventive_rules_allowed': settings().app_env == 'simulation',
    }
    changed = client.put('/api/v1/settings', json=rule_payload(before.json()['version']))
    assert changed.status_code == (200 if can_edit else 403), changed.text
    after = client.get('/api/v1/settings')
    assert after.status_code == 200, after.text
    if can_edit:
        assert changed.json()['capabilities'] == capabilities
        assert after.json()['version'] == before.json()['version'] + 1
        assert after.json()['battery_low_mv'] == 3450
    else:
        assert after.json() == before.json()
        assert audit_updates(v3) == []


def test_owner_can_save_disabled_sensor_thresholds_without_field_validation(v3):
    client = v3.client('owner')
    before = client.get('/api/v1/settings').json()
    assert before['capabilities']['preventive_rules_allowed'] is False
    response = client.put('/api/v1/settings', json=rule_payload(before['version']))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['temperature_high_c'] == 41.1 and data['activity_low_threshold'] == 0.025
    assert data['temperature_enabled'] is False and data['activity_enabled'] is False
    assert data['activity_window_minutes'] == 15 and data['proximity_meters'] == 25
    assert data['capabilities']['preventive_rules_allowed'] is False
    recorded = audit_updates(v3)
    assert len(recorded) == 1
    assert 'capabilities' not in recorded[0]['before'] and 'capabilities' not in recorded[0]['after']
    assert recorded[0]['before']['version'] == before['version']
    assert recorded[0]['after']['version'] == before['version'] + 1


@pytest.mark.parametrize('flag', ['temperature_enabled', 'activity_enabled'])
def test_real_environment_cannot_enable_unvalidated_preventive_sensor(v3, flag):
    client = v3.client('owner')
    before = client.get('/api/v1/settings').json()
    assert before['capabilities']['environment'] != 'simulation'
    response = client.put('/api/v1/settings', json=rule_payload(before['version'], **{flag: True}))
    assert response.status_code == 422, response.text
    assert 'PREVENTIVE_RULES_VALIDATED' in response.json()['detail']
    assert client.get('/api/v1/settings').json() == before
    assert audit_updates(v3) == []


def test_validated_flag_exposes_capability_and_allows_preventive_rules(v3, monkeypatch):
    monkeypatch.setattr(settings(), 'preventive_rules_validated', True)
    client = v3.client('owner')
    before = client.get('/api/v1/settings').json()
    assert before['capabilities']['preventive_rules_validated'] is True
    assert before['capabilities']['preventive_rules_allowed'] is True
    response = client.put('/api/v1/settings', json=rule_payload(before['version'], temperature_enabled=True, activity_enabled=True))
    assert response.status_code == 200, response.text
    assert response.json()['temperature_enabled'] is True and response.json()['activity_enabled'] is True
    assert response.json()['capabilities']['preventive_rules_allowed'] is True


def test_settings_stale_version_does_not_overwrite_current_rules(v3):
    client = v3.client('owner')
    before = client.get('/api/v1/settings').json()
    first = client.put('/api/v1/settings', json=rule_payload(before['version']))
    assert first.status_code == 200, first.text
    rejected = client.put('/api/v1/settings', json=rule_payload(before['version'], battery_low_mv=3800))
    assert rejected.status_code == 409, rejected.text
    assert client.get('/api/v1/settings').json() == first.json()
    assert len(audit_updates(v3)) == 1


def test_settings_are_bound_to_authorized_farm_and_reject_caller_capabilities(v3):
    owner = v3.client('owner')
    other = v3.client('other_owner')
    own_before = owner.get('/api/v1/settings').json()
    foreign_before = other.get('/api/v1/settings').json()
    foreign_write = other.put('/api/v1/settings', json=rule_payload(foreign_before['version'], battery_low_mv=3890))
    assert foreign_write.status_code == 200, foreign_write.text
    denied = owner.post('/api/v1/auth/context', json={'farm_id': str(v3.farms['other_owner'].id)})
    assert denied.status_code == 403, denied.text
    assert owner.get('/api/v1/settings').json() == own_before
    for extra in ({'farm_id': str(v3.farms['other_owner'].id)}, {'capabilities': {'preventive_rules_allowed': True}}):
        rejected = owner.put('/api/v1/settings', json={**rule_payload(own_before['version']), **extra})
        assert rejected.status_code == 422, rejected.text
    own_write = owner.put('/api/v1/settings', json=rule_payload(own_before['version'], battery_low_mv=3400))
    assert own_write.status_code == 200, own_write.text
    assert owner.get('/api/v1/settings').json()['battery_low_mv'] == 3400
    assert other.get('/api/v1/settings').json() == foreign_write.json()


def test_admin_must_select_farm_before_reading_or_changing_rules(v3):
    client = admin_client(v3)
    assert client.get('/api/v1/auth/me').json()['user']['farm_id'] is None
    read = client.get('/api/v1/settings')
    assert read.status_code == 409, read.text
    write = client.put('/api/v1/settings', json=rule_payload())
    assert write.status_code == 409, write.text
    assert audit_updates(v3) == []


def test_missing_rule_row_is_actionable_service_error_not_attribute_error(v3):
    client = v3.client('owner')
    row = v3.db.get(RuleSettings, v3.farms['owner'].id)
    v3.db.delete(row)
    v3.db.commit()
    read = client.get('/api/v1/settings')
    assert read.status_code == 503 and read.json()['detail'] == 'Reglas no inicializadas'
    write = client.put('/api/v1/settings', json=rule_payload())
    assert write.status_code == 503 and write.json()['detail'] == 'Reglas no inicializadas'


def test_settings_require_authenticated_session(v3):
    client = v3.client('worker', login=False)
    assert client.get('/api/v1/settings').status_code == 401
    assert client.put('/api/v1/settings', json=rule_payload()).status_code == 401
