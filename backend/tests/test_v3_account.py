"""Credential and recovery integration; all fixtures roll back their data."""
import os
from datetime import timedelta

import pytest
from sqlalchemy import text

from geocattle.main import app
from geocattle.models import utcnow
from geocattle.security import token_hash, verify_password
from geocattle.v3_account import router
from geocattle.v3_security import totp
from test_v3_api import PASSWORD, enable_owner_mfa, v3


pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS V3 de prueba')
if not any(getattr(route, 'path', '') == '/api/v1/auth/password/change' for route in app.routes):
    app.include_router(router)

NEW_PASSWORD = 'new-test-only-password-2026'


def admin_session(v3):
    client = v3.client('admin', login=False)
    challenge = client.post('/api/v1/auth/login', json={'username': v3.users['admin'].username, 'password': PASSWORD})
    assert challenge.status_code == 200, challenge.text
    secret = challenge.json()['secret']
    logged = client.post('/api/v1/auth/mfa/verify', json={'challenge_token': challenge.json()['challenge_token'], 'code': totp(secret)})
    assert logged.status_code == 200, logged.text
    client.headers['X-CSRF-Token'] = logged.json()['csrf_token']
    return client, secret


def generate_codes(v3, client, secret):
    v3.clock['value'] += 30
    response = client.post('/api/v1/auth/mfa/recovery-codes', json={'password': PASSWORD, 'code': totp(secret)})
    assert response.status_code == 200, response.text
    return response.json()['recovery_codes']


def issue_reset(v3, client, secret, key='owner'):
    v3.clock['value'] += 30
    response = client.post('/api/v1/auth/password/reset-issue', json={
        'user_id': str(v3.users[key].id), 'password': PASSWORD, 'code': totp(secret)})
    assert response.status_code == 200, response.text
    assert response.json()['delivery'] == 'manual'
    return response.json()['reset_token']


def test_password_change_reauthenticates_and_revokes_all_sessions(v3):
    client = v3.client('worker')
    second = v3.client('worker')
    wrong = client.post('/api/v1/auth/password/change', json={'current_password': PASSWORD + '-wrong', 'new_password': NEW_PASSWORD})
    assert wrong.status_code == 401
    assert second.get('/api/v1/auth/me').status_code == 200
    changed = client.post('/api/v1/auth/password/change', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD})
    assert changed.status_code == 200, changed.text
    assert changed.json()['reauthentication_required'] is True
    assert 'geocattle_session' not in client.cookies
    assert second.get('/api/v1/auth/me').status_code == 401
    assert client.post('/api/v1/auth/login', json={'username': v3.users['worker'].username, 'password': PASSWORD}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'username': v3.users['worker'].username, 'password': NEW_PASSWORD}).status_code == 200
    assert v3.db.execute(text('SELECT count(*) FROM login_sessions WHERE user_id=:u AND revoked_at IS NOT NULL'),
        {'u': v3.users['worker'].id}).scalar_one() == 2


def test_password_change_requires_totp_when_enabled_and_preserves_factor(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    payload = {'current_password': PASSWORD, 'new_password': NEW_PASSWORD}
    assert client.post('/api/v1/auth/password/change', json=payload).status_code == 401
    v3.clock['value'] += 30
    changed = client.post('/api/v1/auth/password/change', json={**payload, 'code': totp(secret)})
    assert changed.status_code == 200, changed.text
    assert v3.db.execute(text('SELECT count(*) FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL'),
        {'u': v3.users['owner'].id}).scalar_one() == 1


def test_closure_is_only_a_reauthenticated_request_and_preserves_records(v3):
    client = v3.client('owner')
    assert client.post('/api/v1/auth/account/close-request', json={'password': PASSWORD + '-wrong', 'reason': 'Cierre solicitado'}).status_code == 401
    request = client.post('/api/v1/auth/account/close-request', json={'password': PASSWORD, 'reason': 'Solicito revisión del cierre de mi cuenta'})
    assert request.status_code == 201, request.text
    assert request.json()['status'] == 'pending_review'
    assert 'token' not in request.json()
    repeated = client.post('/api/v1/auth/account/close-request', json={'password': PASSWORD, 'reason': 'Se mantiene la solicitud'})
    assert repeated.status_code == 201
    assert repeated.json()['request_id'] == request.json()['request_id']
    assert client.get('/api/v1/auth/me').status_code == 200
    assert v3.db.execute(text('SELECT active FROM users WHERE id=:u'), {'u': v3.users['owner'].id}).scalar_one() is True
    assert v3.db.execute(text('SELECT count(*) FROM animals WHERE id=:a'), {'a': v3.animals['owner'].id}).scalar_one() == 1
    assert v3.db.execute(text("SELECT count(*) FROM account_tokens WHERE user_id=:u AND purpose='close_account'"),
        {'u': v3.users['owner'].id}).scalar_one() == 1


def test_recovery_codes_require_mfa_are_hashed_and_regeneration_invalidates_old(v3):
    client = v3.client('owner')
    assert client.post('/api/v1/auth/mfa/recovery-codes', json={'password': PASSWORD, 'code': '000000'}).status_code == 409
    secret = enable_owner_mfa(v3, client)
    codes = generate_codes(v3, client, secret)
    assert len(codes) == len(set(codes)) == 8
    stored = v3.db.execute(text('SELECT code_hash FROM mfa_recovery_codes WHERE user_id=:u'), {'u': v3.users['owner'].id}).scalars().all()
    assert len(stored) == 8 and all(code not in stored for code in codes)
    fresh = generate_codes(v3, client, secret)
    assert not set(codes) & set(fresh)
    assert v3.db.execute(text('SELECT count(*) FROM mfa_recovery_codes WHERE user_id=:u AND used_at IS NULL'),
        {'u': v3.users['owner'].id}).scalar_one() == 8
    visitor = v3.client('owner', login=False)
    response = visitor.post('/api/v1/auth/mfa/recovery-login', json={'username': v3.users['owner'].username,
        'password': PASSWORD, 'recovery_code': codes[0]})
    assert response.status_code == 401


def test_recovery_login_is_one_use_and_wrong_password_does_not_burn_code(v3):
    client = v3.client('owner')
    secret = enable_owner_mfa(v3, client)
    codes = generate_codes(v3, client, secret)
    visitor = v3.client('owner', login=False)
    payload = {'username': v3.users['owner'].username, 'password': PASSWORD + '-wrong', 'recovery_code': codes[0]}
    assert visitor.post('/api/v1/auth/mfa/recovery-login', json=payload).status_code == 401
    payload['password'] = PASSWORD
    logged = visitor.post('/api/v1/auth/mfa/recovery-login', json=payload)
    assert logged.status_code == 200, logged.text
    assert logged.json()['user']['mfa_enabled'] is True
    visitor.headers['X-CSRF-Token'] = logged.json()['csrf_token']
    assert visitor.get('/api/v1/auth/me').status_code == 200
    assert visitor.post('/api/v1/auth/mfa/recovery-login', json=payload).status_code == 401
    assert v3.db.execute(text('SELECT count(*) FROM mfa_recovery_codes WHERE user_id=:u AND used_at IS NOT NULL'),
        {'u': v3.users['owner'].id}).scalar_one() == 1


def test_admin_recovery_login_preserves_mfa_for_future_logins(v3):
    admin, secret = admin_session(v3)
    codes = generate_codes(v3, admin, secret)
    visitor = v3.client('admin', login=False)
    recovered = visitor.post('/api/v1/auth/mfa/recovery-login', json={'username': v3.users['admin'].username,
        'password': PASSWORD, 'recovery_code': codes[0]})
    assert recovered.status_code == 200, recovered.text
    assert visitor.get('/api/v1/v3/admin/kpis').status_code == 200
    next_login = visitor.post('/api/v1/auth/login', json={'username': v3.users['admin'].username, 'password': PASSWORD})
    assert next_login.status_code == 200
    assert next_login.json()['mfa_required'] is True and next_login.json()['setup_required'] is False
    assert v3.db.execute(text('SELECT count(*) FROM mfa_factors WHERE user_id=:u AND revoked_at IS NULL'),
        {'u': v3.users['admin'].id}).scalar_one() == 1


def test_recovery_login_failed_attempts_are_persistently_bounded(v3):
    owner = v3.client('owner')
    secret = enable_owner_mfa(v3, owner)
    generate_codes(v3, owner, secret)
    visitor = v3.client('owner', login=False)
    payload = {'username': v3.users['owner'].username, 'password': PASSWORD,
        'recovery_code': '00000-00000-00000-00000'}
    for _ in range(5):
        failed = visitor.post('/api/v1/auth/mfa/recovery-login', json=payload)
        assert failed.status_code == 401, failed.text
    assert visitor.post('/api/v1/auth/mfa/recovery-login', json=payload).status_code == 429
    assert v3.db.execute(text('SELECT count(*) FROM mfa_recovery_codes WHERE user_id=:u AND used_at IS NULL'),
        {'u': v3.users['owner'].id}).scalar_one() == 8


def test_assisted_password_reset_is_admin_only_one_use_and_preserves_mfa(v3):
    owner = v3.client('owner')
    enable_owner_mfa(v3, owner)
    denied = owner.post('/api/v1/auth/password/reset-issue', json={'user_id': str(v3.users['worker'].id), 'password': PASSWORD, 'code': '000000'})
    assert denied.status_code == 403
    admin, secret = admin_session(v3)
    token = issue_reset(v3, admin, secret)
    stored = v3.db.execute(text('SELECT token_hash,expires_at FROM account_tokens WHERE token_hash=:t'),
        {'t': token_hash(token)}).mappings().one()
    assert stored['token_hash'] != token
    assert utcnow() < stored['expires_at'] <= utcnow() + timedelta(minutes=15)
    assert owner.get('/api/v1/auth/me').status_code == 200
    visitor = v3.client('owner', login=False)
    reset = visitor.post('/api/v1/auth/password/reset', json={'token': token, 'new_password': NEW_PASSWORD})
    assert reset.status_code == 200, reset.text
    assert reset.json()['reauthentication_required'] is True
    assert 'geocattle_session' not in visitor.cookies
    assert owner.get('/api/v1/auth/me').status_code == 401
    assert visitor.post('/api/v1/auth/password/reset', json={'token': token, 'new_password': NEW_PASSWORD + '-again'}).status_code == 401
    assert v3.db.execute(text('SELECT count(*) FROM mfa_factors WHERE user_id=:u AND verified_at IS NOT NULL AND revoked_at IS NULL'),
        {'u': v3.users['owner'].id}).scalar_one() == 1
    assert verify_password(v3.db.execute(text('SELECT password_hash FROM users WHERE id=:u'), {'u': v3.users['owner'].id}).scalar_one(), NEW_PASSWORD)


def test_reset_links_expire_and_new_issue_invalidates_earlier_link(v3):
    admin, secret = admin_session(v3)
    old = issue_reset(v3, admin, secret)
    latest = issue_reset(v3, admin, secret)
    visitor = v3.client('owner', login=False)
    assert visitor.post('/api/v1/auth/password/reset', json={'token': old, 'new_password': NEW_PASSWORD}).status_code == 401
    v3.db.execute(text('UPDATE account_tokens SET expires_at=:e WHERE token_hash=:t'),
        {'e': utcnow() - timedelta(seconds=1), 't': token_hash(latest)})
    v3.db.commit()
    assert visitor.post('/api/v1/auth/password/reset', json={'token': latest, 'new_password': NEW_PASSWORD}).status_code == 401
    assert verify_password(v3.db.execute(text('SELECT password_hash FROM users WHERE id=:u'), {'u': v3.users['owner'].id}).scalar_one(), PASSWORD)


def test_admin_password_reset_still_requires_mfa_at_next_login(v3):
    admin, secret = admin_session(v3)
    token = issue_reset(v3, admin, secret, key='admin')
    visitor = v3.client('admin', login=False)
    reset = visitor.post('/api/v1/auth/password/reset', json={'token': token, 'new_password': NEW_PASSWORD})
    assert reset.status_code == 200, reset.text
    assert admin.get('/api/v1/v3/admin/kpis').status_code == 401
    assert visitor.get('/api/v1/v3/admin/kpis').status_code == 401
    challenge = visitor.post('/api/v1/auth/login', json={'username': v3.users['admin'].username, 'password': NEW_PASSWORD})
    assert challenge.status_code == 200
    assert challenge.json()['mfa_required'] is True and challenge.json()['setup_required'] is False
    assert 'geocattle_session' not in visitor.cookies


def test_password_change_invalidates_outstanding_assisted_reset(v3):
    admin, secret = admin_session(v3)
    token = issue_reset(v3, admin, secret)
    owner = v3.client('owner')
    changed = owner.post('/api/v1/auth/password/change', json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD})
    assert changed.status_code == 200, changed.text
    assert owner.post('/api/v1/auth/password/reset', json={'token': token, 'new_password': PASSWORD}).status_code == 401


def test_account_actions_enforce_csrf_origin_and_password_strength(v3):
    owner = v3.client('owner')
    payload = {'current_password': PASSWORD, 'new_password': NEW_PASSWORD}
    assert owner.post('/api/v1/auth/password/change', json=payload, headers={'X-CSRF-Token': ''}).status_code == 403
    assert owner.post('/api/v1/auth/password/change', json={**payload, 'new_password': 'short'}).status_code == 422
    assert owner.post('/api/v1/auth/password/reset', json={'token': 'a' * 40, 'new_password': NEW_PASSWORD},
        headers={'Origin': 'https://untrusted.invalid'}).status_code == 403
    assert owner.post('/api/v1/auth/password/reset', json={'token': 'a' * 40, 'new_password': NEW_PASSWORD}).status_code == 401
