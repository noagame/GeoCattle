"""Mirror API and replay on a migrated, isolated PostgreSQL/PostGIS database."""
import os
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from geocattle import db as database, migrate, mirror_sync
from geocattle.main import app
from geocattle.mirror_policy import CHANGES, CREATE_OWNER, DRAFTS, SUPPORT_REQUESTS, WRITE_DENIED
from geocattle.mirror_tables import MIRROR as MIRROR_TABLES
from geocattle.models import Animal, AnimalHolding, Farm, FarmMembership, MFAFactor, OwnerAccount, User, utcnow
from geocattle.security import hash_password
from geocattle.settings import settings
from geocattle.v3_security import cipher, execute, one, rows, totp

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Requiere PostgreSQL/PostGIS de QA')
KEY = 'qa-fictitious-mirror-integration-key'
PASSWORD = 'qa-fictitious-mirror-password'
TOTP_SECRET = 'JBSWY3DPEHPK3PXP'
MIRROR = '/api/v1/mirror'


@pytest.fixture
def mirror(monkeypatch):
    url = os.environ['TEST_DATABASE_URL']
    assert settings().database_url == url, 'DATABASE_URL y TEST_DATABASE_URL deben apuntar a la misma base aislada'
    engine = create_engine(url)
    config = settings()
    for name, value in {'app_env': 'development', 'mirror_mode': 'replica', 'mirror_sync_key': KEY,
                        'mirror_source': 'campo', 'mirror_source_environment': 'development',
                        'mirror_remote_admin': True, 'mirror_remote_changes': True,
                        'admin_login_mfa': False, 'local_admin_password_only': False,
                        'app_database_password': 'qa-fictitious-replica-role-password'}.items():
        monkeypatch.setattr(config, name, value)
    password_hash = hash_password(PASSWORD)
    with engine.connect() as conn:
        outer = conn.begin()
        factory = sessionmaker(conn, join_transaction_mode='create_savepoint', expire_on_commit=False)

        @contextmanager
        def migration_transaction():
            with conn.begin_nested():
                yield conn

        monkeypatch.setattr(migrate, 'engine', SimpleNamespace(begin=migration_transaction))
        monkeypatch.setattr(database, 'SessionLocal', factory)
        monkeypatch.setattr(mirror_sync, 'SessionLocal', factory)
        users = {}
        with factory.begin() as db:
            for name, role in (('admin', 'admin'), ('owner', 'owner'), ('vet', 'veterinarian')):
                ident = uuid4()
                username = f'{name}-{ident}@qa.invalid'
                db.add(User(id=ident, username=username, email=username, full_name=f'QA {name}',
                            role=role, password_hash=password_hash, active=True))
                users[name] = SimpleNamespace(id=ident, username=username)
            db.flush()
            account = OwnerAccount(id=uuid4(), owner_user_id=users['owner'].id, display_name='QA espejo')
            db.add(account)
            db.flush()
            farm = Farm(id=uuid4(), account_id=account.id, name='QA espejo', environment='development')
            db.add(farm)
            db.flush()
            for name in ('owner', 'vet'):
                db.get(User, users[name].id).farm_id = farm.id
            db.add(FarmMembership(id=uuid4(), farm_id=farm.id, user_id=users['vet'].id,
                                  role_code='veterinarian', granted_by=users['owner'].id,
                                  valid_from=utcnow() - timedelta(days=1)))
            animal = Animal(id=uuid4(), farm_id=farm.id, diio=f'QA-{uuid4()}', name='QA bovino espejo',
                            orientation='milk', production_type='milk')
            db.add(animal)
            db.flush()
            db.add(AnimalHolding(id=uuid4(), farm_id=farm.id, animal_id=animal.id,
                                valid_from=utcnow() - timedelta(days=1), reason='QA espejo'))

        def switch(mode):
            conn.execute(text('RESET ROLE'))
            monkeypatch.setattr(config, 'mirror_mode', mode)
            if mode in ('field', 'replica'):
                migrate.migrate()
                conn.execute(text('SET LOCAL ROLE geocattle_app'))

        def login(client, name):
            response = client.post('/api/v1/auth/login', json={'username': users[name].username, 'password': PASSWORD})
            assert response.status_code == 200, response.text
            client.headers['X-CSRF-Token'] = response.json()['csrf_token']
            return response

        switch('replica')
        try:
            yield SimpleNamespace(conn=conn, db=factory, config=config, switch=switch, login=login,
                                  users=users, farm=farm.id, animal=animal.id, version=animal.version)
        finally:
            outer.rollback()
    engine.dispose()


def queued(response):
    assert response.status_code == 202, response.text
    data = response.json()
    assert data == {'queued': True, 'outbox_id': data['outbox_id'], 'status': 'queued'}
    return data['outbox_id']


def inbox(client):
    result = client.get(MIRROR + '/inbox?limit=50', headers={'X-Mirror-Key': KEY})
    assert result.status_code == 200, result.text
    return [mirror_sync.Submission.model_validate(item) for item in result.json()['items']]


def test_replica_write_policy_and_database_grants(mirror):
    with TestClient(app) as client:
        mirror.login(client, 'owner')
        blocked = (
            ('POST', '/api/v1/ingest/receiver-batch'), ('POST', '/api/v1/v3/gateways'),
            ('PATCH', '/api/v1/v3/profile'), ('POST', '/api/v1/auth/mfa/setup'),
            ('POST', CREATE_OWNER), ('POST', CHANGES), ('POST', DRAFTS),
        )
        bodies = {CREATE_OWNER: {'email': 'test@qa.invalid', 'password': PASSWORD, 'full_name': 'QA'},
                  CHANGES: {'action': 'animal_profile', 'animal_id': str(mirror.animal),
                            'idempotency_key': str(uuid4()), 'payload': {}},
                  DRAFTS: {'id': str(uuid4()), 'animal_id': str(mirror.animal),
                           'action': 'animal_profile', 'payload': {}}}
        for method, path in blocked:
            response = client.request(method, path, json=bodies.get(path, {}))
            assert response.status_code == 403, (path, response.text)
            assert response.json() == {'detail': WRITE_DENIED}
        assert client.get(MIRROR + '/status').status_code == 403
        assert client.get(MIRROR + '/inbox').status_code == 401
        with mirror.db.begin() as db:
            before = one(db, 'SELECT last_seen_at FROM login_sessions WHERE user_id=:u', u=mirror.users['owner'].id)
        assert client.get(MIRROR + '/info').json()['mode'] == 'replica'
        with mirror.db.begin() as db:
            assert one(db, 'SELECT last_seen_at FROM login_sessions WHERE user_id=:u', u=mirror.users['owner'].id) == before
    with mirror.db.begin() as db:
        for table in sorted(MIRROR_TABLES):
            privileges = one(db, """SELECT has_table_privilege(:t,'SELECT') AS can_read,
                has_table_privilege(:t,'INSERT,UPDATE,DELETE,TRUNCATE') AS can_write""", t=table)
            assert privileges == {'can_read': True, 'can_write': False}, table
        with pytest.raises(ProgrammingError, match='permission denied'), db.begin_nested():
            execute(db, "INSERT INTO mirror_heartbeat(source,at,schema_version) VALUES('denied',now(),'014')")
    mirror.switch('off')
    with TestClient(app) as client:
        mirror.login(client, 'owner')
        assert client.get(MIRROR + '/info').json() == {'mode': 'off'}
        assert client.patch('/api/v1/v3/profile', json={'full_name': 'QA titular editado'}).status_code == 200


def test_admin_order_queue_and_replay_are_authenticated_and_idempotent(mirror):
    with TestClient(app) as client:
        payload = {'email': f'{uuid4()}@qa.invalid', 'password': PASSWORD, 'full_name': 'QA titular remoto'}
        assert client.post(CREATE_OWNER, json=payload).status_code == 401
        mirror.login(client, 'admin')
        assert client.post(CREATE_OWNER, json=payload, headers={'X-CSRF-Token': 'bad'}).status_code == 403
        outbox_id = queued(client.post(CREATE_OWNER, json=payload))
        item, = inbox(client)
        assert str(item.id) == outbox_id and item.kind == 'admin_order' and item.farm_id is None
        assert item.body['password'] != payload['password']
        assert inbox(client) == [item]
        assert client.get(MIRROR + '/submissions').json()['items'][0]['status'] == 'delivered'
        with mirror.db.begin() as db:
            assert one(db, 'SELECT attempts FROM mirror_outbox WHERE id=:i', i=item.id)['attempts'] == 2
            assert one(db, 'SELECT id FROM users WHERE email=:email', email=payload['email']) is None
            assert one(db, "SELECT action FROM mirror_audit_log WHERE object_id=:i", i=outbox_id) == {'action': 'mirror_queued'}

        mirror.switch('field')
        with TestClient(app) as unauthenticated:
            forged = unauthenticated.post(CREATE_OWNER, json=payload,
                                          headers={'X-Mirror-Key': KEY, 'X-Actor-ID': str(item.actor_id)})
            assert forged.status_code == 401
        assert mirror_sync.apply_submission(item) == 'applied'
        assert mirror_sync.apply_submission(item) == 'applied'
        with mirror.db.begin() as db:
            assert one(db, 'SELECT count(*) AS n FROM users WHERE email=:e', e=payload['email'])['n'] == 1
            assert one(db, "SELECT count(*) AS n FROM audit_log WHERE action='remote_admin' AND object_id=:i",
                       i=outbox_id)['n'] == 1
        mirror.switch('replica')
        assert inbox(client) == []
        result, = client.get(MIRROR + '/submissions').json()['items']
        assert result['outbox_id'] == outbox_id and result['status'] == 'applied'
        assert client.get(MIRROR + '/status').json()['submission_counts'] == {'applied': 1}


def test_personal_support_is_validated_private_and_replayed_once(mirror, monkeypatch):
    payload = {'kind': 'access_issue', 'description': '  QA soporte web  '}
    with TestClient(app) as owner, TestClient(app) as vet:
        assert owner.post(SUPPORT_REQUESTS, json=payload).status_code == 401
        mirror.login(owner, 'owner')
        mirror.login(vet, 'vet')
        assert owner.post(SUPPORT_REQUESTS, json=payload, headers={'X-CSRF-Token': 'bad'}).status_code == 403
        for invalid in ({'kind': 'close_account'}, {'description': ' '}, {'description': 'x' * 2001},
                        {'requester_id': str(mirror.users['vet'].id)}):
            assert owner.post(SUPPORT_REQUESTS, json={**payload, **invalid}).status_code == 422
        monkeypatch.setattr(mirror.config, 'mirror_remote_changes', False)
        assert owner.post(SUPPORT_REQUESTS, json=payload).status_code == 403
        monkeypatch.setattr(mirror.config, 'mirror_remote_changes', True)
        outbox_id = queued(owner.post(SUPPORT_REQUESTS, json=payload))
        item, = inbox(owner)
        assert (str(item.id), item.kind, item.actor_id, item.farm_id) == (
            outbox_id, 'support_request', mirror.users['owner'].id, None)
        assert item.body == {**payload, 'description': 'QA soporte web'}
        assert owner.get(SUPPORT_REQUESTS).json() == {'items': [], 'total': 0}
        assert vet.get(MIRROR + '/submissions').json() == {'items': [], 'total': 0}
        with mirror.db.begin() as db:
            assert one(db, "SELECT farm_id FROM mirror_audit_log WHERE action='mirror_queued' AND object_id=:i",
                       i=outbox_id) == {'farm_id': None}

        mirror.switch('field')
        assert mirror_sync.apply_submission(item) == 'applied'
        assert mirror_sync.apply_submission(item) == 'applied'
        with mirror.db.begin() as db:
            record, = rows(db, 'SELECT id,requester_id,status FROM support_requests WHERE requester_id=:u',
                           u=mirror.users['owner'].id)
            assert record == {'id': item.id, 'requester_id': item.actor_id, 'status': 'pending'}
            entry, = rows(db, "SELECT actor_id,farm_id FROM audit_log WHERE action='support_request_created' AND object_id=:i",
                          i=outbox_id)
            assert entry == {'actor_id': item.actor_id, 'farm_id': None}
            db.get(User, mirror.users['vet'].id).active = False
        inactive = item.model_copy(update={'id': uuid4(), 'actor_id': mirror.users['vet'].id})
        assert mirror_sync.apply_submission(inactive) == 'rejected'

        mirror.switch('replica')
        assert inbox(owner) == []
        result, = owner.get(MIRROR + '/submissions').json()['items']
        assert result['status'] == 'applied' and result['result']['request_id'] == outbox_id
        support, = owner.get(SUPPORT_REQUESTS).json()['items']
        assert support['id'] == outbox_id and support['status'] == 'pending'


def test_failed_replay_rolls_back_business_write_and_records_failure(mirror, monkeypatch):
    with TestClient(app) as client:
        mirror.login(client, 'admin')
        email = f'{uuid4()}@qa.invalid'
        queued(client.post(CREATE_OWNER, json={'email': email, 'password': PASSWORD, 'full_name': 'QA fallo'}))
        item, = inbox(client)
    mirror.switch('field')

    def unavailable_audit(*args, **kwargs):
        raise RuntimeError('QA fallo durante el registro de la orden')

    monkeypatch.setattr(mirror_sync, 'audit', unavailable_audit)
    assert mirror_sync.apply_submission(item) == 'failed'
    assert mirror_sync.apply_submission(item) == 'failed'
    with mirror.db.begin() as db:
        assert one(db, 'SELECT id FROM users WHERE email=:e', e=email) is None
        assert one(db, 'SELECT status,http_status FROM mirror_inbox_results WHERE outbox_id=:i',
                   i=item.id) == {'status': 'failed', 'http_status': 500}


def test_field_revalidates_role_and_remote_switch_before_applying(mirror, monkeypatch):
    with TestClient(app) as client:
        mirror.login(client, 'vet')
        payload = {'action': 'animal_profile', 'animal_id': str(mirror.animal), 'expected_version': mirror.version,
                   'idempotency_key': str(uuid4()), 'payload': {'breed': 'QA rechazado'}}
        queued(client.post(CHANGES, json=payload))
        item, = inbox(client)
    mirror.switch('field')
    monkeypatch.setattr(mirror.config, 'mirror_remote_changes', False)
    assert mirror_sync.apply_submission(item) == 'rejected'
    monkeypatch.setattr(mirror.config, 'mirror_remote_changes', True)
    wrong_actor = item.model_copy(update={'id': uuid4(), 'actor_id': mirror.users['owner'].id})
    assert mirror_sync.apply_submission(wrong_actor) == 'rejected'
    with mirror.db.begin() as db:
        assert one(db, 'SELECT count(*) AS n FROM change_requests WHERE farm_id=:f', f=mirror.farm)['n'] == 0


def test_remote_change_waits_for_owner_preserves_authorship_and_keeps_reads_local(mirror):
    with TestClient(app) as vet, TestClient(app) as owner:
        mirror.login(vet, 'vet')
        payload = {'action': 'animal_profile', 'animal_id': str(mirror.animal), 'expected_version': mirror.version,
                   'idempotency_key': str(uuid4()), 'payload': {'breed': 'QA remoto'}}
        outbox_id = queued(vet.post(CHANGES, json=payload))
        item, = inbox(vet)
        mirror.switch('field')
        assert mirror_sync.apply_submission(item) == 'pending_owner'
        assert mirror_sync.apply_submission(item) == 'pending_owner'
        with mirror.db.begin() as db:
            request, = rows(db, 'SELECT id,requested_by,idempotency_key FROM change_requests WHERE requested_by=:u',
                            u=mirror.users['vet'].id)
            ident = request['id']
            assert request['idempotency_key'] == UUID(outbox_id)
            assert one(db, 'SELECT request_id FROM change_decisions WHERE request_id=:i', i=ident) is None
        mirror.login(owner, 'owner')
        assert owner.post(f'{CHANGES}/{ident}/decision', json={'decision': 'approved'}).json()['status'] == 'applied'
        with mirror.db.begin() as db:
            assert one(db, 'SELECT decided_by FROM change_decisions WHERE request_id=:i', i=ident)['decided_by'] == mirror.users['owner'].id
            assert db.get(Animal, mirror.animal).breed == 'QA remoto'
        mirror.switch('replica')
        assert owner.get(MIRROR + '/submissions').json() == {'items': [], 'total': 0}
        # La decisión del dueño, replicada desde el PC, cierra el estado del envío.
        assert vet.get(MIRROR + '/submissions').json()['items'][0]['status'] == 'applied'
        path = '/api/v1/v3/notifications'
        notice = owner.get(path + '?unread=true').json()['items'][0]
        unread = owner.get('/api/v1/v3/activity-counts').json()['unread_notices']
        assert owner.post(f'{path}/{notice["id"]}/read').json() == {'read': True}
        assert next(row for row in owner.get(path).json()['items'] if row['id'] == notice['id'])['status'] == 'read'
        assert owner.get('/api/v1/v3/activity-counts').json()['unread_notices'] == unread - 1
        with mirror.db.begin() as db:
            assert one(db, 'SELECT read_at FROM notifications WHERE id=:i', i=notice['id'])['read_at'] is None


def test_replica_totp_uses_local_counter_with_production_security(mirror, monkeypatch):
    mirror.switch('field')
    factor_id = uuid4()
    field_counter = '2000000000'
    with mirror.db.begin() as db:
        db.add(MFAFactor(id=factor_id, user_id=mirror.users['admin'].id, kind='totp', credential_id=field_counter,
                         protected_data=cipher().encrypt(TOTP_SECRET.encode()), verified_at=utcnow()))
    mirror.switch('replica')
    monkeypatch.setattr(mirror.config, 'app_env', 'production')
    monkeypatch.setattr(mirror.config, 'cookie_secure', True)
    with TestClient(app, base_url='https://testserver') as client:
        login_body = {'username': mirror.users['admin'].username, 'password': PASSWORD}
        challenge = client.post('/api/v1/auth/login', json=login_body).json()
        assert challenge['mfa_required'] and not challenge['setup_required']
        assert client.get(MIRROR + '/status').status_code == 401
        support = {'kind': 'access_issue', 'description': 'QA administrador con TOTP'}
        assert client.post(SUPPORT_REQUESTS, json=support).status_code == 401
        code = totp(TOTP_SECRET)
        verify = '/api/v1/auth/mfa/verify'
        verified = client.post(verify, json={'challenge_token': challenge['challenge_token'], 'code': code})
        assert verified.status_code == 200, verified.text
        queued(client.post(SUPPORT_REQUESTS, json=support, headers={'X-CSRF-Token': verified.json()['csrf_token']}))
        assert client.get(MIRROR + '/status').status_code == 200
        assert client.get('/api/v1/v3/farms').json()['items'][0]['id'] == str(mirror.farm)
        assert client.get('/api/v1/v3/audit').status_code == 200
        second = client.post('/api/v1/auth/login', json=login_body).json()['challenge_token']
        assert client.post(verify, json={'challenge_token': second, 'code': code}).status_code == 401
        with mirror.db.begin() as db:
            assert one(db, 'SELECT factor_id FROM mirror_totp_use WHERE factor_id=:i', i=factor_id)
            assert one(db, 'SELECT credential_id FROM mfa_factors WHERE id=:i', i=factor_id)['credential_id'] == field_counter
            assert one(db, "SELECT action FROM mirror_audit_log WHERE actor_id=:u AND action='login'",
                       u=mirror.users['admin'].id)
        with TestClient(app, base_url='https://testserver') as owner:
            assert mirror.login(owner, 'owner').json()['user']['farm_id'] == str(mirror.farm)


def test_draft_conflict_preserves_sibling_and_blocks_dependent_submit_and_discard(mirror):
    ident = str(uuid4())
    path = f'{DRAFTS}/{ident}'
    with TestClient(app) as vet:
        mirror.switch('field')
        mirror.login(vet, 'vet')
        create = vet.post(DRAFTS, json={'id': ident, 'action': 'animal_profile', 'animal_id': str(mirror.animal),
                                        'payload': {'breed': 'QA base'}})
        assert create.status_code == 201, create.text
        revised = vet.put(path, json={'base_version': 1, 'payload': {'breed': 'QA terreno'}})
        assert revised.status_code == 200 and revised.json()['version'] == 2
        mirror.switch('replica')
        save = queued(vet.put(path, json={'base_version': 1, 'payload': {'breed': 'QA web'}}))
        draft, = vet.get(DRAFTS).json()['items']
        assert draft['status'] == 'pending_sync' and draft['pending_operation'] == 'save'
        assert draft['payload'] == {'breed': 'QA web'}
        submit = queued(vet.post(path + '/submit', json={'base_version': draft['version']}))
        draft, = vet.get(DRAFTS).json()['items']
        assert draft['status'] == 'pending_sync' and draft['pending_operation'] == 'submit'
        discard = queued(vet.request('DELETE', path, json={'base_version': draft['version']}))
        draft, = vet.get(DRAFTS).json()['items']
        assert draft['pending_operation'] == 'discard'
        items = inbox(vet)
        assert [str(item.id) for item in items] == [save, submit, discard]
        assert [item.body['after_outbox_id'] for item in items] == [None, save, submit]
        mirror.switch('field')
        assert mirror_sync.apply_submission(items[1]) is None
        assert [mirror_sync.apply_submission(item) for item in items] == ['conflict', 'conflict', 'conflict']
        draft_list = vet.get(DRAFTS).json()['items']
        sibling = next(draft for draft in draft_list if draft['conflict_of'] == ident)
        original = next(draft for draft in draft_list if draft['id'] == ident)
        assert sibling['payload'] == {'breed': 'QA web'}
        assert original['payload'] == {'breed': 'QA terreno'} and original['status'] == 'draft'
        stale_submit = vet.post(path + '/submit', json={'base_version': 1})
        assert stale_submit.status_code == 409 and stale_submit.json()['draft_id'] == ident
        with mirror.db.begin() as db:
            result = one(db, 'SELECT result,http_status FROM mirror_inbox_results WHERE outbox_id=:i', i=UUID(save))
            assert result['http_status'] == 409
            assert result['result']['conflict_id'] == sibling['id'] and result['result']['draft_id'] == ident
            assert one(db, 'SELECT count(*) AS n FROM change_requests WHERE idempotency_key=:i', i=UUID(ident))['n'] == 0


def test_queued_draft_create_save_and_submit_replay_in_order(mirror):
    ident = str(uuid4())
    path = f'{DRAFTS}/{ident}'
    with TestClient(app) as vet:
        mirror.login(vet, 'vet')
        queued(vet.post(DRAFTS, json={'id': ident, 'action': 'animal_profile', 'animal_id': str(mirror.animal),
                                      'payload': {'breed': 'QA inicio web'}}))
        first, = vet.get(DRAFTS).json()['items']
        assert first['id'] == ident and first['status'] == 'pending_sync' and first['version'] == 1
        queued(vet.put(path, json={'base_version': 1, 'payload': {'breed': 'QA revisión web'}}))
        queued(vet.post(path + '/submit', json={}))
        items = inbox(vet)
        assert items[2].body['base_version'] == 2
        mirror.switch('field')
        assert [mirror_sync.apply_submission(item) for item in items] == ['applied', 'applied', 'pending_owner']
        final, = vet.get(DRAFTS).json()['items']
        assert final['status'] == 'submitted' and final['version'] == 3 and final['request_id']
        with mirror.db.begin() as db:
            request = one(db, 'SELECT payload,idempotency_key FROM change_requests WHERE id=:i', i=UUID(final['request_id']))
            assert request == {'payload': {'breed': 'QA revisión web'}, 'idempotency_key': UUID(ident)}


def test_field_cycle_refreshes_heartbeat_after_failed_fetch(mirror, monkeypatch):
    import httpx

    mirror.switch('field')

    def unreachable(_config):
        raise httpx.ConnectError('QA red caída')

    monkeypatch.setattr(mirror_sync, 'fetch_inbox', unreachable)
    with mirror.db.begin() as db:
        mirror_sync.publish_heartbeat(db)
    old = utcnow() - timedelta(seconds=61)
    with mirror.db.begin() as db:
        execute(db, 'UPDATE mirror_heartbeat SET at=:at WHERE source=:s', at=old, s='campo')
    mirror_sync.run_mirror_cycle()
    mirror.switch('replica')
    with TestClient(app) as client:
        mirror.login(client, 'admin')
        status = client.get(MIRROR + '/status').json()
        assert status['field_online'] and status['heartbeat']['inbox_checked_at']
        assert status['heartbeat']['details'] == {'inbox': 'unavailable'}
        with mirror.db.begin() as db:
            assert status['heartbeat']['schema_version'] == one(db, 'SELECT max(version) AS version FROM schema_migrations')['version']
