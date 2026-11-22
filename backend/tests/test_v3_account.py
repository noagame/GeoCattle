"""Credential and recovery integration; all fixtures roll back their data."""
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from geocattle.account_maintenance import main as maintenance
from geocattle.main import app
from geocattle.models import utcnow
from geocattle.security import token_hash, verify_password
from geocattle.settings import settings
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


def password_login(v3, client):
    response = client.post('/api/v1/auth/login', json={
        'username': v3.users['admin'].username, 'password': PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def verify_challenge(client, challenge, code, **kwargs):
    return client.post('/api/v1/auth/mfa/verify', json={
        'challenge_token': challenge['challenge_token'], 'code': code}, **kwargs)


def test_replace_totp_is_bound_to_session_and_switches_only_after_confirmation(v3):
    account, old_secret = admin_session(v3)
    codes = generate_codes(v3, account, old_secret)
    visitor = v3.client('admin', login=False)
    wrong_password = account.post('/api/v1/auth/mfa/replace', json={
        'password': 'incorrecta', 'recovery_code': codes[0]})
    assert wrong_password.status_code == 401
    replacement = account.post('/api/v1/auth/mfa/replace', json={
        'password': PASSWORD, 'recovery_code': codes[0]})
    assert replacement.status_code == 200, replacement.text
    new = replacement.json()
    assert new['secret'] != old_secret and new['secret'] in new['otpauth_uri']
    assert account.post('/api/v1/auth/mfa/replace', json={
        'password': PASSWORD, 'recovery_code': codes[0]}).status_code == 401
    v3.clock['value'] += 30
    old_login = password_login(v3, visitor)
    assert old_login['setup_required'] is False and 'secret' not in old_login
    signed_in = verify_challenge(visitor, old_login, totp(old_secret))
    assert signed_in.status_code == 200, signed_in.text
    visitor.headers['X-CSRF-Token'] = signed_in.json()['csrf_token']
    assert verify_challenge(visitor, new, totp(new['secret'])).status_code == 401
    assert verify_challenge(account, new, totp(new['secret']), headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    counter = v3.clock['value'] // 30
    valid_codes = {totp(new['secret'], counter + delta) for delta in (-1, 0, 1)}
    wrong = next(f'{number:06}' for number in range(4) if f'{number:06}' not in valid_codes)
    assert verify_challenge(account, new, wrong).status_code == 401
    assert verify_challenge(account, new, '１２３４５６').status_code == 401
    stale = password_login(v3, visitor)
    complete = verify_challenge(account, new, totp(new['secret']))
    assert complete.status_code == 200, complete.text
    assert complete.json()['user']['mfa_enabled'] is True
    assert account.get('/api/v1/auth/me').status_code == 200
    assert visitor.get('/api/v1/auth/me').status_code == 401
    assert verify_challenge(account, new, totp(new['secret'])).status_code == 401
    assert verify_challenge(visitor, stale, totp(old_secret)).status_code == 401
    assert visitor.post('/api/v1/auth/mfa/recovery-login', json={
        'username': v3.users['admin'].username, 'password': PASSWORD,
        'recovery_code': codes[1]}).status_code == 401
    v3.clock['value'] += 30
    next_login = password_login(v3, visitor)
    assert verify_challenge(visitor, next_login, totp(new['secret'])).status_code == 200
    audited = v3.db.execute(text("SELECT after::text FROM audit_log WHERE action='mfa_replaced' AND actor_id=:u"),
        {'u': v3.users['admin'].id}).scalar_one()
    assert all(value not in audited for value in (old_secret, new['secret'], new['challenge_token'], codes[0]))


@pytest.mark.parametrize('required', [False, True])
def test_remove_totp_revokes_sessions_and_follows_admin_policy(v3, monkeypatch, required):
    client, secret = admin_session(v3)
    monkeypatch.setattr(settings(), 'admin_login_mfa', required)
    v3.clock['value'] += 30
    removed = client.post('/api/v1/auth/mfa/remove', json={'password': PASSWORD, 'code': totp(secret)})
    assert removed.status_code == 200, removed.text
    assert removed.json() == {'removed': True, 'enrollment_required': required}
    assert 'geocattle_session' not in client.cookies
    assert client.get('/api/v1/auth/me').status_code == 401
    # A mandatory enrollment survives a switch to password-only mode.
    monkeypatch.setattr(settings(), 'admin_login_mfa', False)
    next_login = password_login(v3, client)
    if required:
        assert next_login['setup_required'] is True and 'geocattle_session' not in client.cookies
        assert verify_challenge(client, next_login, totp(next_login['secret'])).status_code == 200
    else:
        assert next_login['user']['mfa_enabled'] is False


def test_console_reset_forces_enrollment_in_password_only_mode(v3, monkeypatch, capsys):
    account, old_secret = admin_session(v3)
    codes = generate_codes(v3, account, old_secret)
    visitor = v3.client('admin', login=False)
    previous_challenge = password_login(v3, visitor)
    monkeypatch.setattr(settings(), 'admin_login_mfa', False)
    monkeypatch.setattr('sys.argv', ['maintenance', 'mfa-reset', '--email', 'missing@example.test'])
    assert maintenance() == 0
    generic_reply = capsys.readouterr().out
    assert account.get('/api/v1/auth/me').status_code == 200
    monkeypatch.setattr('sys.argv', ['maintenance', 'mfa-reset', '--email', v3.users['admin'].email.upper()])
    assert maintenance() == 0 and capsys.readouterr().out == generic_reply
    # The fixture's SessionLocal.begin() uses a nested transaction. Release
    # the savepoint so the next failed HTTP request only rolls back its own work.
    v3.db.commit()
    assert account.get('/api/v1/auth/me').status_code == 401
    assert verify_challenge(visitor, previous_challenge, totp(old_secret)).status_code == 401
    assert visitor.post('/api/v1/auth/mfa/recovery-login', json={
        'username': v3.users['admin'].username, 'password': PASSWORD, 'recovery_code': codes[0]}).status_code == 401
    pending = password_login(v3, visitor)
    assert pending['setup_required'] is True and 'geocattle_session' not in visitor.cookies
    assert pending['secret'] != old_secret
    assert verify_challenge(visitor, pending, totp(pending['secret'])).status_code == 200
    audit = v3.db.execute(text("SELECT actor_id,actor_kind,after FROM audit_log WHERE object_id=:u AND action='mfa_reset_console'"),
        {'u': str(v3.users['admin'].id)}).one()
    assert audit.actor_id is None and audit.actor_kind == 'service' and audit.after['actor'] == 'sistema/consola'
    assert v3.db.execute(text('SELECT mfa_enrollment_required FROM users WHERE id=:u'),
        {'u': v3.users['admin'].id}).scalar_one() is False


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
    assert v3.db.execute(text("SELECT count(*) FROM support_requests WHERE requester_id=:u AND kind='close_account'"),
        {'u': v3.users['owner'].id}).scalar_one() == 1


def test_support_is_private_and_global_admin_response_reaches_requester(v3):
    worker = v3.client('worker')
    owner = v3.client('owner')
    admin, _ = admin_session(v3)
    support = '/api/v1/auth/support-requests'
    counts = '/api/v1/v3/activity-counts'
    previous = admin.get(counts).json()['pending_support']

    closure = worker.post('/api/v1/auth/account/close-request', json={'password': PASSWORD, 'reason': 'Motivo privado'})
    assert closure.status_code == 201, closure.text
    ident = closure.json()['request_id']
    access = worker.post(support, json={'kind': 'access_issue', 'description': 'Consulta de acceso'})
    assert access.status_code == 201, access.text
    assert worker.post(support, json={'kind': 'close_account', 'description': 'Sin credenciales'}).status_code == 422
    assert worker.post(support, json={'kind': 'change_email', 'description': '  '}).status_code == 422

    mine = worker.get(support).json()['items']
    assert {item['id'] for item in mine} == {ident, access.json()['request_id']}
    assert owner.get(support).json()['total'] == 0
    assert owner.get(support, params={'admin': True}).status_code == 403
    decision = {'status': 'resolved', 'response': 'Revisión de cuenta completada'}
    assert owner.post(f'{support}/{ident}/decision', json=decision).status_code == 403

    # Preserve historical evidence without returning its private text to the farm owner.
    v3.db.execute(text("""INSERT INTO audit_log(id,farm_id,actor_id,object_type,object_id,action,at,after)
        VALUES(:id,:farm,:worker,'account_request',:ref,'account_closure_requested',now(),'{"reason":"Privado histórico"}')"""),
        {'id': uuid4(), 'farm': v3.farms['owner'].id, 'worker': v3.users['worker'].id, 'ref': ident})
    assert owner.get('/api/v1/v3/audit', params={'entity': 'account_request'}).json()['total'] == 0
    assert all(item['object_type'] != 'account_request' for item in owner.get('/api/v1/audit').json()['items'])
    new_audit = v3.db.execute(text("""SELECT farm_id,after FROM audit_log
        WHERE object_id=:i AND action='account_closure_requested' AND farm_id IS NULL"""), {'i': ident}).one()
    assert new_audit.after == {'kind': 'close_account', 'status': 'pending'}

    assert admin.get(counts).json()['pending_support'] == previous + 2
    queue = admin.get(support, params={'admin': True, 'status': 'pending'}).json()['items']
    assert next(item for item in queue if item['id'] == ident)['description'] == 'Motivo privado'
    context = admin.post('/api/v1/auth/context', json={'farm_id': str(v3.farms['owner'].id)})
    assert context.status_code == 200
    assert admin.get(support, params={'admin': True}).status_code == 403
    assert admin.post(f'{support}/{ident}/decision', json=decision).status_code == 403
    assert admin.post('/api/v1/auth/context', json={'farm_id': None}).status_code == 200

    assert admin.post(f'{support}/{ident}/decision', json=decision).status_code == 200
    assert admin.post(f'{support}/{ident}/decision', json=decision).status_code == 200
    assert admin.post(f'{support}/{ident}/decision', json={**decision, 'response': 'Otra respuesta'}).status_code == 409
    assert admin.get(counts).json()['pending_support'] == previous + 1
    answered = worker.get(support, params={'status': 'resolved'}).json()
    assert answered['total'] == 1 and answered['items'][0]['response'] == decision['response']
    assert worker.get(counts).json()['unread_support'] == 1
    assert owner.post(f'{support}/{ident}/read', json={}).status_code == 404
    assert worker.post(f'{support}/{ident}/read', json={}).status_code == 200
    assert worker.get(counts).json()['unread_support'] == 0
    assert worker.get('/api/v1/auth/me').status_code == 200


def test_audit_records_known_login_and_context_states(v3):
    admin, _ = admin_session(v3)
    farm = v3.farms['owner']
    assert admin.post('/api/v1/auth/context', json={'farm_id': str(farm.id)}).status_code == 200
    assert admin.post('/api/v1/auth/context', json={'farm_id': None}).status_code == 200
    contexts = admin.get('/api/v1/v3/audit', params={'action': 'select_context'}).json()['items']
    platform = {'scope': 'platform', 'role': 'admin'}
    farm_context = {'scope': 'farm', 'farm_id': str(farm.id), 'farm_name': farm.name, 'role': 'admin'}
    assert any(item['before'] == platform and item['after'] == farm_context for item in contexts)
    assert any(item['before'] == farm_context and item['after'] == platform for item in contexts)
    login = admin.get('/api/v1/v3/audit', params={'action': 'login', 'actor_id': str(v3.users['admin'].id)}).json()['items'][0]
    assert login['before'] is None
    assert login['after'] == {'status': 'active', 'mfa_verified': True, **platform}


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
