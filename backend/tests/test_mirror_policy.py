from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from geocattle.mirror_policy import CHANGES, DRAFTS, SUPPORT_REQUESTS, kind_enabled, write_kind, write_target
from geocattle.mirror_replay import Replay, replay_for, replay_transport
from geocattle.settings import Settings, settings


KEY = 'qa-fictitious-mirror-key-at-least-32'


def test_mirror_settings_and_production_isolation():
    base = {'_env_file': None, 'app_env': 'development', 'simulation_enabled': False, 'admin_login_mfa': False}
    assert Settings(**base, mirror_mode='off', mirror_sync_key='').mirror_mode == 'off'
    replica = Settings(**base, mirror_mode='replica', mirror_sync_key=KEY, mirror_source_environment='production')
    assert replica.visible_farm_environment == 'production'
    assert not replica.admin_login_requires_mfa
    assert KEY not in repr(replica)
    with pytest.raises(ValidationError, match='MIRROR_SYNC_KEY'):
        Settings(**base, mirror_mode='replica', mirror_sync_key='short')
    for url in ('http://localhost:8080/', 'http://127.0.0.1:8080/', 'https://mirror.example.invalid/'):
        field = Settings(**base, mirror_mode='field', mirror_sync_key=KEY, mirror_server_url=url)
        assert field.mirror_server_url == url.rstrip('/')
    for url in ('', 'http://mirror.example.invalid', 'https://user:pass@mirror.example.invalid', 'https://localhost:bad'):
        with pytest.raises(ValidationError, match='MIRROR_SERVER_URL'):
            Settings(**base, mirror_mode='field', mirror_sync_key=KEY, mirror_server_url=url)
    production = {**base, 'app_env': 'production', 'cookie_secure': True,
                  'session_secret': KEY, 'ingest_key': KEY, 'local_admin_password_only': False}
    with pytest.raises(ValidationError, match='MIRROR_SERVER_URL'):
        Settings(**production, mirror_mode='field', mirror_sync_key=KEY, mirror_server_url='http://localhost')
    assert Settings(**production, mirror_mode='replica', mirror_sync_key=KEY).admin_login_requires_mfa


def test_write_allowlist_restricts_method_path_role_and_action():
    draft = f'{DRAFTS}/{uuid4()}'
    admin = {'platform_admin': True, 'veterinarian': False}
    vet = {'platform_admin': False, 'veterinarian': True}
    owner = {'platform_admin': False, 'veterinarian': False}
    assert write_kind('POST', CHANGES, {'action': 'animal_report'}, **admin) == 'admin_order'
    assert write_kind('POST', CHANGES, {'action': 'health_record'}, **vet) == 'remote_change'
    assert write_kind('POST', CHANGES, {'action': 'health_record'}, **owner) is None
    assert write_kind('POST', CHANGES, {'action': 'animal_report'}, **vet) is None
    assert write_kind('POST', CHANGES, {'action': 'battery_replacement'}, **admin) is None
    assert write_kind('POST', CHANGES, {'action': ['health_record']}, **vet) is None
    assert write_kind('PUT', draft, {}, **vet) == 'draft_revision'
    assert write_kind('POST', draft + '/submit', {}, **vet) == 'draft_revision'
    assert write_kind('DELETE', draft, {}, **admin) is None
    assert write_kind('POST', '/api/v1/v3/admin/owners', {}, **admin) == 'admin_order'
    assert write_kind('POST', '/api/v1/v3/admin/owners', {}, **vet) is None
    assert write_target('PATCH', f'/api/v1/v3/admin/owners/{uuid4()}') == 'admin_order'
    assert write_target('POST', f'/api/v1/auth/support-requests/{uuid4()}/decision') == 'admin_order'
    assert write_target('POST', '/api/v1/auth/context') == 'local'
    for path in (draft + '/submit/', f'{DRAFTS}/invalid/submit', '/api/v1/ingest/receiver-batch',
                 '/api/v1/auth/mfa/setup', '/api/v1/v3/admin/device-registration'):
        assert write_target('POST', path) is None


def test_replay_scope_cannot_be_populated_through_headers_or_json():
    app = FastAPI()
    actor_id = uuid4()
    replay = Replay(None, uuid4(), actor_id, uuid4(), 'admin_order')

    @app.post('/identity')
    def identity(request: Request):
        ctx = replay_for(request)
        return {'actor': str(ctx.actor_id) if ctx else None}

    with TestClient(app) as network:
        fake = network.post('/identity', headers={'X-Mirror-Key': KEY, 'X-Actor-ID': str(actor_id)},
                            json={'actor_id': str(actor_id), 'kind': 'admin_order'})
        assert fake.json() == {'actor': None}
        with TestClient(replay_transport(app, replay)) as internal:
            assert internal.post('/identity').json() == {'actor': str(actor_id)}
        assert network.post('/identity').json() == {'actor': None}


@pytest.mark.parametrize(('platform_admin', 'veterinarian'), [(False, False), (False, True), (True, False)])
def test_support_creation_is_a_personal_submission(platform_admin, veterinarian):
    permissions = {'platform_admin': platform_admin, 'veterinarian': veterinarian}
    assert write_kind('POST', SUPPORT_REQUESTS, {'kind': 'access_issue'}, **permissions) == 'support_request'
    assert write_target('PATCH', SUPPORT_REQUESTS) is None
    assert write_target('POST', f'{SUPPORT_REQUESTS}/{uuid4()}/read') is None
    assert write_target('POST', '/api/v1/auth/account/close-request') is None


def test_support_uses_the_remote_changes_switch_and_marks_creation_as_applied(monkeypatch):
    from geocattle.mirror_sync import result_status

    monkeypatch.setattr(settings(), 'mirror_remote_admin', False)
    monkeypatch.setattr(settings(), 'mirror_remote_changes', True)
    assert kind_enabled('support_request')
    monkeypatch.setattr(settings(), 'mirror_remote_changes', False)
    assert not kind_enabled('support_request')
    assert result_status(201, {'status': 'pending'}, 'support_request') == 'applied'
    assert result_status(422, {'detail': []}, 'support_request') == 'rejected'
    assert result_status(201, {'status': 'pending'}, 'remote_change') == 'pending_owner'


def test_replica_worker_skips_database_tasks(monkeypatch):
    from geocattle import worker

    monkeypatch.setattr(settings(), 'mirror_mode', 'replica')
    monkeypatch.setattr(worker, 'SessionLocal', None)
    assert worker.run_once() is None


def test_owner_conversion_is_an_admin_order_only():
    path = f'/api/v1/v3/admin/users/{uuid4()}/owner'
    assert write_kind('POST', path, {'max_farms': 1}, platform_admin=True, veterinarian=False) == 'admin_order'
    assert write_kind('POST', path, {'max_farms': 1}, platform_admin=False, veterinarian=True) is None
    assert write_target('PATCH', path) is None
