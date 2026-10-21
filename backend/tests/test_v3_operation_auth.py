"""Each team write needs its own session-, tenant- and payload-bound MFA token."""
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from starlette.requests import Request

from geocattle.main import app
from geocattle.models import LoginSession, utcnow
from geocattle.security import token_hash
from geocattle.v3_operation_auth import operation_digest, require_operation, router
from geocattle.v3_security import totp
from test_v3_api import PASSWORD, enable_owner_mfa, v3


pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS V3 de prueba')


# Root connects the router in main.py; standalone execution is also supported.
if not any(getattr(route, 'path', '') == '/api/v1/auth/operation' for route in app.routes):
    app.include_router(router)

PATH = '/api/v1/v3/invitations'
PAYLOAD = {'email': 'colaborador@qa.test', 'role_code': 'worker'}


def authorization(v3, client, secret, payload=None, method='POST', path=PATH):
    v3.clock['value'] += 30
    response = client.post('/api/v1/auth/operation', json={
        'password': PASSWORD, 'code': totp(secret), 'method': method,
        'path': path, 'payload': PAYLOAD if payload is None else payload,
    })
    assert response.status_code == 200, response.text
    return response.json()['operation_token']


def operation_request(v3, client, token, method='POST', path=PATH, farm=None):
    request = Request({'type': 'http', 'method': method, 'path': path,
        'headers': [(b'x-operation-token', token.encode())], 'query_string': b'',
        'scheme': 'http', 'server': ('testserver', 80)})
    session = v3.db.get(LoginSession, token_hash(client.cookies.get('geocattle_session')))
    request.state.session = session
    user = SimpleNamespace(id=v3.users['owner'].id, role='owner',
        farm_id=farm or v3.farms['owner'].id)
    return request, user


def consumed_at(v3, token):
    return v3.db.execute(text('SELECT consumed_at FROM auth_challenges WHERE token_hash=:t'),
        {'t': token_hash(token)}).scalar_one()


def assert_denied(v3, client, token, payload=None, **kwargs):
    request, user = operation_request(v3, client, token, **kwargs)
    with pytest.raises(HTTPException) as error:
        require_operation(request, v3.db, user, PAYLOAD if payload is None else payload)
    assert error.value.status_code == 403
    assert consumed_at(v3, token) is None


def test_operation_valid_consumption_rejects_reuse(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    token = authorization(v3, client, secret)
    request, user = operation_request(v3, client, token)
    require_operation(request, v3.db, user, dict(reversed(list(PAYLOAD.items()))))
    assert consumed_at(v3, token) is not None
    with pytest.raises(HTTPException) as error:
        require_operation(request, v3.db, user, PAYLOAD)
    assert error.value.status_code == 403


def test_protected_invitation_http_requires_exact_one_use_authorization(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    assert client.post(PATH, json=PAYLOAD).status_code == 403
    token = authorization(v3, client, secret)
    altered = client.post(PATH, json={**PAYLOAD, 'role_code': 'veterinarian'},
        headers={'X-Operation-Token': token})
    assert altered.status_code == 403, altered.text
    assert consumed_at(v3, token) is None
    accepted = client.post(PATH, json=PAYLOAD, headers={'X-Operation-Token': token})
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()['email'] == PAYLOAD['email']
    assert consumed_at(v3, token) is not None
    reused = client.post(PATH, json=PAYLOAD, headers={'X-Operation-Token': token})
    assert reused.status_code == 403, reused.text
    assert v3.db.execute(text('SELECT count(*) FROM invitations WHERE farm_id=:f AND email=:e'),
        {'f': v3.farms['owner'].id, 'e': PAYLOAD['email']}).scalar_one() == 1


def test_operation_payload_method_path_and_predio_are_bound(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    token = authorization(v3, client, secret)
    assert_denied(v3, client, token, payload={**PAYLOAD, 'role_code': 'veterinarian'})
    assert_denied(v3, client, token, path='/api/v1/v3/trust')
    assert_denied(v3, client, token, farm=v3.farms['other_owner'].id)
    request, user = operation_request(v3, client, token)
    require_operation(request, v3.db, user, PAYLOAD)
    assert consumed_at(v3, token) is not None


def test_operation_token_cannot_move_to_another_session(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    token = authorization(v3, client, secret)
    other_session = v3.client('owner')
    assert_denied(v3, other_session, token)
    request, user = operation_request(v3, client, token)
    require_operation(request, v3.db, user, PAYLOAD)


def test_operation_expired_unverified_and_missing_token_denied(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    token = authorization(v3, client, secret)
    v3.db.execute(text('UPDATE auth_challenges SET expires_at=:t WHERE token_hash=:h'),
        {'t': utcnow() - timedelta(seconds=1), 'h': token_hash(token)})
    assert_denied(v3, client, token)
    v3.db.execute(text('UPDATE auth_challenges SET expires_at=:t,verified_at=NULL WHERE token_hash=:h'),
        {'t': utcnow() + timedelta(minutes=5), 'h': token_hash(token)})
    assert_denied(v3, client, token)
    request, user = operation_request(v3, client, '')
    with pytest.raises(HTTPException) as error:
        require_operation(request, v3.db, user, PAYLOAD)
    assert error.value.status_code == 403


def test_operation_consumption_rolls_back_with_the_write(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    token = authorization(v3, client, secret)
    request, user = operation_request(v3, client, token)
    with pytest.raises(RuntimeError):
        with v3.db.begin_nested():
            require_operation(request, v3.db, user, PAYLOAD)
            assert consumed_at(v3, token) is not None
            raise RuntimeError('La escritura protegida falló')
    assert consumed_at(v3, token) is None
    require_operation(request, v3.db, user, PAYLOAD)
    assert consumed_at(v3, token) is not None


def test_operation_requires_csrf_allowed_role_and_supported_target(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    request = {'password': PASSWORD, 'code': totp(secret), 'method': 'POST', 'path': PATH, 'payload': PAYLOAD}
    assert client.post('/api/v1/auth/operation', json=request, headers={'X-CSRF-Token': ''}).status_code == 403
    worker = v3.client('worker')
    assert worker.post('/api/v1/auth/operation', json=request).status_code == 403
    request['path'] = '/api/v1/v3/admin/owners'
    assert client.post('/api/v1/auth/operation', json=request).status_code == 422


def test_operation_mfa_failures_share_identity_budget(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    v3.clock['value'] += 30
    request = {'password': PASSWORD + '-incorrecta', 'code': totp(secret),
        'method': 'POST', 'path': PATH, 'payload': PAYLOAD}
    for _ in range(5):
        failed = client.post('/api/v1/auth/operation', json=request)
        assert failed.status_code == 401, failed.text
    request['password'] = PASSWORD
    assert client.post('/api/v1/auth/operation', json=request).status_code == 429


def test_operation_digest_is_canonical_and_includes_method():
    assert operation_digest('POST', PATH, {'a': 1, 'b': 2}, 'farm') == operation_digest('POST', PATH, {'b': 2, 'a': 1}, 'farm')
    assert operation_digest('POST', PATH, PAYLOAD, 'farm') != operation_digest('PATCH', PATH, PAYLOAD, 'farm')
