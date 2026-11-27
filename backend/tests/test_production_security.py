"""Production identity and HTTP security contracts."""

import os
from datetime import timedelta
from http.cookies import SimpleCookie
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from geocattle.main import app
from geocattle.mirror_policy import CREATE_OWNER
from geocattle.models import utcnow
from geocattle.security import current_user, service_auth, token_hash
from geocattle.settings import settings
from geocattle.v3_security import one
from test_mirror_mode import MIRROR, PASSWORD as MIRROR_PASSWORD, mirror
from test_v3_api import PASSWORD, v3


def auth_dependencies(dependant):
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from auth_dependencies(dependency)


def api_routes(router):
    for route in router.routes:
        if isinstance(route, APIRoute):
            yield route
        elif getattr(route, 'original_router', None):
            yield from api_routes(route.original_router)


def test_routes_outside_session_dependency_have_explicit_security_review():
    routes = tuple(api_routes(app))
    outside = {
        (method, route.path)
        for route in routes
        if not {current_user, service_auth}.intersection(auth_dependencies(route.dependant))
        for method in route.methods
    }
    assert outside == {
        ('GET', '/api/v1/health'),
        ('POST', '/api/v1/auth/login'),
        ('POST', '/api/v1/auth/mfa/verify'),
        ('POST', '/api/v1/auth/mfa/recovery-login'),
        ('POST', '/api/v1/auth/password/reset'),
        ('POST', '/api/v1/v3/enrol/preview'),
        ('POST', '/api/v1/v3/enrol'),
        ('GET', '/api/v1/mirror/inbox'),
        ('GET', '/api/v1/v3/device-candidates/capture-farms'),
        ('POST', '/api/v1/v3/device-candidates'),
        ('POST', '/api/v1/v3/gateway-candidates'),
    }


@pytest.mark.parametrize('environment', ['development', 'production'])
def test_docs_and_cors_at_startup(environment, tmp_path):
    origin = 'https://geocattle.example.invalid'
    env = {
        **os.environ,
        'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
        'APP_ENV': environment,
        'SIMULATION_ENABLED': 'false',
        'COOKIE_SECURE': 'true',
        'SESSION_SECRET': 'session-secret-for-isolated-qa-only',
        'INGEST_KEY': 'capture-secret-for-isolated-qa-only',
        'DATABASE_URL': 'postgresql+psycopg://qa@127.0.0.1:1/geocattle_qa_stub',
        'DEMO_PASSWORD': '',
        'ALLOWED_ORIGINS': origin,
        'ALLOWED_HOSTS': 'geocattle.example.invalid',
        'MIRROR_MODE': 'off',
        'LOCAL_ADMIN_PASSWORD_ONLY': 'false',
        'INVITATION_EMAIL_ENABLED': 'false',
    }
    source = """
from fastapi.testclient import TestClient
from pydantic import ValidationError
from geocattle import main
from geocattle.settings import Settings, settings

main.persist_request_metrics = lambda *args: None
origin = settings().allowed_origins
with TestClient(main.app, base_url=origin) as client:
    expected = 404 if settings().app_env == 'production' else 200
    for path in ('/api/docs', '/api/openapi.json'):
        response = client.get(path)
        assert response.status_code == expected, (path, response.status_code)
    assert client.get('/api/docs', headers={'Host': 'external.invalid'}).status_code == 400
    path = '/api/v1/auth/context'
    preflight = {'Access-Control-Request-Method': 'POST',
                 'Access-Control-Request-Headers': 'X-CSRF-Token'}
    accepted = client.options(path, headers={**preflight, 'Origin': origin})
    assert accepted.headers['Access-Control-Allow-Origin'] == origin
    assert accepted.headers['Access-Control-Allow-Credentials'] == 'true'
    denied = client.options(path, headers={**preflight, 'Origin': 'https://external.invalid'})
    assert denied.status_code == 400
    assert 'Access-Control-Allow-Origin' not in denied.headers

if settings().app_env == 'production':
    try:
        Settings(allowed_origins=origin + ', *')
    except ValidationError as error:
        assert 'ALLOWED_ORIGINS' in str(error)
    else:
        raise AssertionError('Production must reject wildcard origins')
"""
    result = subprocess.run([sys.executable, '-c', source], env=env, cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS de QA')
@pytest.mark.parametrize('end', ['logout', 'absolute_expiry', 'idle_expiry'])
def test_secure_session_cookie_and_session_end(v3, monkeypatch, end):
    monkeypatch.setattr(settings(), 'cookie_secure', True)
    username = v3.users['owner'].username
    with TestClient(app, base_url='https://testserver') as client:
        login = client.post('/api/v1/auth/login', json={'username': username, 'password': PASSWORD})
        assert login.status_code == 200
        cookie = SimpleCookie(login.headers['Set-Cookie'])['geocattle_session']
        assert cookie['httponly'] and cookie['secure'] and cookie['samesite'].lower() == 'lax'
        assert cookie['path'] == '/' and not cookie['domain']
        assert client.get('/api/v1/auth/me').status_code == 200
        if end == 'logout':
            assert client.post('/api/v1/auth/logout').status_code == 403
            response = client.post('/api/v1/auth/logout', headers={'X-CSRF-Token': login.json()['csrf_token']})
            assert response.status_code == 204
            assert SimpleCookie(response.headers['Set-Cookie'])['geocattle_session']['max-age'] == '0'
        else:
            expiry = (
                text('UPDATE login_sessions SET expires_at=:at WHERE token_hash=:token')
                if end == 'absolute_expiry' else
                text('UPDATE login_sessions SET last_seen_at=:at WHERE token_hash=:token')
            )
            v3.db.execute(expiry, {'at': utcnow() - timedelta(minutes=31), 'token': token_hash(cookie.value)})
            v3.db.commit()
            v3.db.expire_all()
        client.cookies.clear()
        client.cookies.set('geocattle_session', cookie.value)
        assert client.get('/api/v1/auth/me').status_code == 401


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS de QA')
def test_mirror_inbox_requires_its_key_and_owner_order_does_not_audit_password(mirror):
    with TestClient(app) as vet, TestClient(app) as admin:
        payload = {'email': f'{uuid4()}@qa.invalid', 'password': MIRROR_PASSWORD, 'full_name': 'QA'}
        mirror.login(vet, 'vet')
        assert vet.post(CREATE_OWNER, json=payload).status_code == 403
        mirror.login(admin, 'admin')
        queued = admin.post(CREATE_OWNER, json=payload)
        assert queued.status_code == 202
        ident = queued.json()['outbox_id']
        for headers in ({}, {'X-Mirror-Key': 'qa-incorrect-key'}):
            assert admin.get(MIRROR + '/inbox', headers=headers).status_code == 401
        with mirror.db.begin() as db:
            order = one(db, 'SELECT body,attempts FROM mirror_outbox WHERE id=:i', i=ident)
            assert MIRROR_PASSWORD not in str(order['body'])
            assert order['attempts'] == 0
            audit = one(db, 'SELECT after FROM mirror_audit_log WHERE object_id=:i', i=ident)
            assert audit['after'] == {'kind': 'admin_order', 'method': 'POST', 'path': CREATE_OWNER}
