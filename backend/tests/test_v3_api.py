"""Integración V3: roles, aislamiento, MFA y cambios atómicos sobre PostgreSQL.
Los datos y las métricas de cada prueba se revierten en una transacción externa.
"""
import os
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from geocattle.db import get_db
from geocattle.main import app
from geocattle.models import Animal, AnimalHolding, Farm, FarmMembership, OwnerAccount, RuleSettings, User, utcnow
from geocattle.security import hash_password, token_hash
from geocattle.settings import settings
from geocattle.v3_security import totp

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Requiere PostgreSQL/PostGIS V3 de prueba')
PASSWORD='test-only-v3-strong-password'
PASSWORD_HASH=hash_password(PASSWORD)


@pytest.fixture
def v3(monkeypatch):
    engine=create_engine(os.environ['TEST_DATABASE_URL'])
    with engine.connect() as conn:
        outer=conn.begin()
        db=Session(conn,join_transaction_mode='create_savepoint',expire_on_commit=False)
        now=utcnow()
        users={}
        for name,role in [('admin','admin'),('owner','owner'),('other_owner','owner'),('worker','worker'),('vet','veterinarian'),('viewer','viewer')]:
            uid=uuid4()
            users[name]=User(id=uid,username=f'{name}-{uid}@qa.test',email=f'{name}-{uid}@qa.test',full_name='QA '+name,password_hash=PASSWORD_HASH,role=role,active=True)
        db.add_all(users.values());db.flush()
        farms={}
        for key in ('owner','other_owner'):
            account=OwnerAccount(id=uuid4(),owner_user_id=users[key].id,display_name='QA '+key,max_farms=3)
            db.add(account);db.flush()
            farm=Farm(id=uuid4(),account_id=account.id,name='QA predio '+key,environment=settings().app_env)
            db.add(farm);db.flush();db.add(RuleSettings(farm_id=farm.id))
            users[key].farm_id=farm.id
            farms[key]=farm
        members={}
        for key in ('worker','vet','viewer'):
            user=users[key];user.farm_id=farms['owner'].id
            membership=FarmMembership(id=uuid4(),farm_id=farms['owner'].id,user_id=user.id,role_code=user.role,granted_by=users['owner'].id,valid_from=now-timedelta(days=1))
            db.add(membership);members[key]=membership
        animals={}
        for key in ('owner','other_owner'):
            animal=Animal(id=uuid4(),farm_id=farms[key].id,diio=f'QA-{uuid4()}',name='QA bovino '+key,orientation='milk',production_type='milk')
            db.add(animal);db.flush()
            db.add(AnimalHolding(id=uuid4(),farm_id=farms[key].id,animal_id=animal.id,valid_from=now-timedelta(days=10),reason='QA fixture'))
            animals[key]=animal
        db.commit()
        def override():
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
        @contextmanager
        def metrics_transaction():
            with db.begin_nested():
                yield db
        monkeypatch.setattr('geocattle.db.SessionLocal',SimpleNamespace(begin=metrics_transaction))
        app.dependency_overrides[get_db]=override
        clock={'value':1800000010}
        monkeypatch.setattr('geocattle.v3_security.time.time',lambda:clock['value'])
        with ExitStack() as stack:
            def client_for(key,login=True):
                client=stack.enter_context(TestClient(app))
                if login:
                    response=client.post('/api/v1/auth/login',json={'username':users[key].username,'password':PASSWORD})
                    assert response.status_code==200,response.text
                    if key!='admin':client.headers['X-CSRF-Token']=response.json()['csrf_token']
                return client
            yield SimpleNamespace(db=db,users=users,farms=farms,members=members,animals=animals,client=client_for,clock=clock)
        app.dependency_overrides.clear();db.close();outer.rollback()
    engine.dispose()


def body(v3,action,payload,version=None):
    return {'action':action,'animal_id':str(v3.animals['owner'].id),
      'expected_version':version if version is not None else v3.animals['owner'].version,
      'payload':payload,'idempotency_key':str(uuid4())}


def enable_owner_mfa(v3,client):
    setup=client.post('/api/v1/auth/mfa/setup',json={'password':PASSWORD})
    assert setup.status_code==200,setup.text
    response=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':setup.json()['challenge_token'],'code':totp(setup.json()['secret'])})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf_token']
    return setup.json()['secret']


def operation_write(v3,client,secret,method,path,payload=None):
    v3.clock['value']+=30
    authorized=client.post('/api/v1/auth/operation',json={'password':PASSWORD,'code':totp(secret),'method':method,'path':path,'payload':payload or {}})
    assert authorized.status_code==200,authorized.text
    return client.request(method,path,json=payload,headers={'X-Operation-Token':authorized.json()['operation_token']})


def test_admin_requires_real_totp_enrollment_login_and_one_use_challenge(v3):
    client=v3.client('admin',login=False)
    challenge=client.post('/api/v1/auth/login',json={'username':v3.users['admin'].username,'password':PASSWORD})
    assert challenge.status_code==200,challenge.text
    assert challenge.json()['mfa_required'] and challenge.json()['setup_required']
    assert 'geocattle_session' not in client.cookies
    assert client.get('/api/v1/v3/admin/kpis').status_code==401
    secret=challenge.json()['secret']
    token=challenge.json()['challenge_token']
    verified=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':token,'code':totp(secret)})
    assert verified.status_code==200,verified.text
    assert verified.json()['user']['role']=='admin'
    assert verified.json()['user']['mfa_enabled'] is True
    client.headers['X-CSRF-Token']=verified.json()['csrf_token']
    kpis=client.get('/api/v1/v3/admin/kpis')
    assert kpis.status_code==200,kpis.text
    assert kpis.json()['instance_resources']['database_bytes']>0
    assert kpis.json()['usage_24h']['request_bytes']>=0
    assert client.post('/api/v1/auth/mfa/verify',json={'challenge_token':token,'code':totp(secret)}).status_code==401
    factor=v3.db.execute(text('SELECT protected_data FROM mfa_factors WHERE user_id=:u'),{'u':v3.users['admin'].id}).scalar_one()
    assert secret.encode() not in bytes(factor)
    assert v3.db.execute(text('SELECT token_hash FROM auth_challenges WHERE token_hash=:t'),{'t':token_hash(token)}).scalar_one()==token_hash(token)
    assert client.post('/api/v1/auth/logout').status_code==204
    assert client.get('/api/v1/v3/admin/kpis').status_code==401
    v3.clock['value']+=30
    login=client.post('/api/v1/auth/login',json={'username':v3.users['admin'].username,'password':PASSWORD})
    assert login.status_code==200 and login.json()['setup_required'] is False
    assert 'secret' not in login.json()
    response=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':login.json()['challenge_token'],'code':totp(secret)})
    assert response.status_code==200,response.text
    assert client.get('/api/v1/v3/admin/kpis').status_code==200


def test_owner_is_denied_other_owner_farm_animal_and_context(v3):
    client=v3.client('owner')
    foreign_animal=v3.animals['other_owner'].id
    assert client.get(f'/api/v1/animals/{foreign_animal}').status_code==403
    assert client.get(f'/api/v1/v3/animals/{foreign_animal}/record').status_code==403
    assert client.post('/api/v1/auth/context',json={'farm_id':str(v3.farms['other_owner'].id)}).status_code==403
    assert client.patch(f"/api/v1/v3/farms/{v3.farms['other_owner'].id}",json={'name':'Intento ajeno'}).status_code==403
    owned=client.get('/api/v1/v3/farms')
    assert owned.status_code==200
    assert {item['id'] for item in owned.json()['items']}=={str(v3.farms['owner'].id)}


def test_worker_pending_health_does_not_mutate_until_owner_approval(v3):
    worker=v3.client('worker');owner=v3.client('owner')
    payload={'event_type':'vaccination','description':'Vacuna aplicada y reportada por trabajador'}
    submitted=worker.post('/api/v1/v3/changes',json=body(v3,'health_record',payload))
    assert submitted.status_code==201,submitted.text
    assert submitted.json()['status']=='pending'
    req=submitted.json()['id']
    before=owner.get(f"/api/v1/v3/animals/{v3.animals['owner'].id}/record")
    assert before.status_code==200 and before.json()['health_events']==[]
    assert before.json()['pending_health_warning'] is True
    assert len(before.json()['pending'])==1
    approved=owner.post(f'/api/v1/v3/changes/{req}/decision',json={'decision':'approved'})
    assert approved.status_code==200,approved.text
    assert approved.json()['status']=='applied'
    after=owner.get(f"/api/v1/v3/animals/{v3.animals['owner'].id}/record")
    assert after.status_code==200
    assert len(after.json()['health_events'])==1 and after.json()['health_events'][0]['effective'] is True
    assert after.json()['pending_health_warning'] is False
    assert v3.animals['owner'].version==2
    repeat=owner.post(f'/api/v1/v3/changes/{req}/decision',json={'decision':'approved'})
    assert repeat.status_code==200,repeat.text
    assert v3.db.execute(text('SELECT count(*) FROM health_events WHERE request_id=CAST(:r AS uuid)'),{'r':req}).scalar_one()==1


def test_veterinarian_direct_health_and_correction_preserve_history(v3):
    vet=v3.client('vet')
    first=vet.post('/api/v1/v3/changes',json=body(v3,'health_record',{'event_type':'pathology','description':'Evaluación clínica','diagnosis':'Hallazgo de prueba'}))
    assert first.status_code==201,first.text
    assert first.json()['status']=='applied' and first.json()['decision']=='direct'
    original=first.json()['entity_id']
    corrected=vet.post('/api/v1/v3/changes',json=body(v3,'health_record',{'event_type':'pathology','operation':'correct','target_event_id':original,'description':'Corrección clínica','diagnosis':'Hallazgo corregido'}))
    assert corrected.status_code==201,corrected.text
    record=vet.get(f"/api/v1/v3/animals/{v3.animals['owner'].id}/record")
    assert record.status_code==200,record.text
    assert len(record.json()['health_events'])==2
    assert sum(item['effective'] for item in record.json()['health_events'])==1
    decisions=v3.db.execute(text("SELECT decision,decided_by FROM change_decisions d JOIN change_requests r ON r.id=d.request_id WHERE r.requested_by=:u"),{'u':v3.users['vet'].id}).all()
    assert len(decisions)==2 and all(d.decision=='direct' and d.decided_by==v3.users['vet'].id for d in decisions)


def test_worker_trust_is_action_specific_and_revocable(v3):
    worker=v3.client('worker');owner=v3.client('owner')
    pending=worker.post('/api/v1/v3/changes',json=body(v3,'animal_report',{'description':'Reporte sujeto a revisión'}))
    assert pending.status_code==201 and pending.json()['status']=='pending'
    assert v3.db.execute(text('SELECT count(*) FROM animal_reports')).scalar_one()==0
    grant_body={'membership_id':str(v3.members['worker'].id),'action':'animal_report'}
    assert owner.post('/api/v1/v3/trust',json=grant_body).status_code==403
    secret=enable_owner_mfa(v3,owner)
    grant=operation_write(v3,owner,secret,'POST','/api/v1/v3/trust',grant_body)
    assert grant.status_code==201,grant.text
    direct=worker.post('/api/v1/v3/changes',json=body(v3,'animal_report',{'description':'Reporte con confianza vigente'}))
    assert direct.status_code==201,direct.text
    assert direct.json()['status']=='applied' and direct.json()['decision']=='direct'
    decision=v3.db.execute(text('SELECT trust_grant_id FROM change_decisions WHERE request_id=CAST(:r AS uuid)'),{'r':direct.json()['id']}).scalar_one()
    assert str(decision)==grant.json()['id']
    different=worker.post('/api/v1/v3/changes',json=body(v3,'animal_status',{'status':'missing'}))
    assert different.status_code==201 and different.json()['status']=='pending'
    assert v3.animals['owner'].status=='active'
    # El rollback externo fija now() para todas las peticiones de QA;
    # antedatar la concesión evita un intervalo de longitud cero artificial.
    v3.db.execute(text("UPDATE trust_grants SET valid_from=valid_from-interval '1 second' WHERE id=CAST(:i AS uuid)"),{'i':grant.json()['id']})
    assert operation_write(v3,owner,secret,'DELETE',f"/api/v1/v3/trust/{grant.json()['id']}").status_code==204
    revoked=worker.post('/api/v1/v3/changes',json=body(v3,'animal_report',{'description':'Reporte después de revocación'}))
    assert revoked.status_code==201 and revoked.json()['status']=='pending'


def test_legacy_viewer_can_read_but_cannot_write_or_review(v3):
    viewer=v3.client('viewer')
    assert viewer.get('/api/v1/animals').status_code==200
    assert viewer.get(f"/api/v1/v3/animals/{v3.animals['owner'].id}/record").status_code==200
    assert viewer.post('/api/v1/v3/changes',json=body(v3,'animal_status',{'status':'missing'})).status_code==403
    assert viewer.patch(f"/api/v1/animals/{v3.animals['owner'].id}",json={'name':'Sin permiso'}).status_code==403
    assert viewer.post('/api/v1/sectors',json={'name':'No autorizado'}).status_code==403
    assert viewer.get('/api/v1/v3/admin/users').status_code==403
    assert viewer.get('/api/v1/v3/audit').status_code==403


def test_owner_approval_detects_changed_animal_version_and_keeps_pending(v3):
    worker=v3.client('worker');vet=v3.client('vet');owner=v3.client('owner')
    proposal=worker.post('/api/v1/v3/changes',json=body(v3,'animal_status',{'status':'missing'},version=1))
    assert proposal.status_code==201,proposal.text
    direct=vet.post('/api/v1/v3/changes',json=body(v3,'animal_profile',{'color':'Marrón'},version=1))
    assert direct.status_code==201,direct.text
    assert v3.animals['owner'].version==2
    conflict=owner.post(f"/api/v1/v3/changes/{proposal.json()['id']}/decision",json={'decision':'approved'})
    assert conflict.status_code==409,conflict.text
    assert v3.animals['owner'].status=='active' and v3.animals['owner'].color=='Marrón'
    assert v3.db.execute(text('SELECT count(*) FROM change_decisions WHERE request_id=CAST(:r AS uuid)'),{'r':proposal.json()['id']}).scalar_one()==0
    pending=owner.get('/api/v1/v3/changes')
    assert pending.status_code==200
    assert next(item for item in pending.json()['items'] if item['id']==proposal.json()['id'])['status']=='pending'
    rejected=owner.post(f"/api/v1/v3/changes/{proposal.json()['id']}/decision",json={'decision':'rejected','reason':'Se reformulará con los datos actuales'})
    assert rejected.status_code==200,rejected.text


def test_legacy_reconciliation_never_resurrects_a_revoked_membership(v3):
    from geocattle.seed_v3 import reconcile_legacy
    member=v3.members['worker']
    member.valid_to=utcnow()-timedelta(hours=1)
    v3.db.flush()
    reconcile_legacy(v3.db)
    count=v3.db.execute(text('SELECT count(*) FROM farm_memberships WHERE user_id=:u AND farm_id=:f'),{'u':v3.users['worker'].id,'f':v3.farms['owner'].id}).scalar_one()
    active=v3.db.execute(text("SELECT count(*) FROM farm_memberships WHERE user_id=:u AND farm_id=:f AND now() <@ tstzrange(valid_from,valid_to,'[)')"),{'u':v3.users['worker'].id,'f':v3.farms['owner'].id}).scalar_one()
    assert count==1 and active==0


def test_worker_health_trust_never_authorizes_editing_veterinary_diagnosis(v3):
    vet=v3.client('vet');worker=v3.client('worker');owner=v3.client('owner')
    original=vet.post('/api/v1/v3/changes',json=body(v3,'health_record',{'event_type':'diagnosis','description':'Diagnóstico registrado por veterinario','diagnosis':'Hallazgo clínico'}))
    assert original.status_code==201,original.text
    event=original.json()['entity_id']
    secret=enable_owner_mfa(v3,owner)
    trust=operation_write(v3,owner,secret,'POST','/api/v1/v3/trust',{'membership_id':str(v3.members['worker'].id),'action':'health_record'})
    assert trust.status_code==201,trust.text
    for operation in ('correct','void'):
        forged=worker.post('/api/v1/v3/changes',json=body(v3,'health_record',{'event_type':'vaccination','operation':operation,'target_event_id':event,'description':'Intento de sustituir diagnóstico con un tipo permitido'}))
        assert forged.status_code==403,forged.text
    record=vet.get(f"/api/v1/v3/animals/{v3.animals['owner'].id}/record")
    assert record.status_code==200,record.text
    assert len(record.json()['health_events'])==1
    assert record.json()['health_events'][0]['id']==event
    assert record.json()['health_events'][0]['effective'] is True


def test_mfa_failure_budget_survives_new_challenges_for_same_identity(v3):
    client=v3.client('admin',login=False)
    credentials={'username':v3.users['admin'].username,'password':PASSWORD}
    challenge_a=client.post('/api/v1/auth/login',json=credentials)
    challenge_b=client.post('/api/v1/auth/login',json=credentials)
    assert challenge_a.status_code==200 and challenge_b.status_code==200
    counter=v3.clock['value']//30
    valid={totp(challenge_b.json()['secret'],counter+delta) for delta in (-1,0,1)}
    invalid=next(str(number).zfill(6) for number in range(1000000) if str(number).zfill(6) not in valid)
    # Rotar el token no reinicia el presupuesto global de la misma identidad.
    for token in [challenge_a.json()['challenge_token']]*3+[challenge_b.json()['challenge_token']]*2:
        failed=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':token,'code':invalid})
        assert failed.status_code==401,failed.text
    attempts=v3.db.execute(text("SELECT sum(attempts) FROM auth_challenges WHERE user_id=:u AND verified_at IS NULL"),{'u':v3.users['admin'].id}).scalar_one()
    assert attempts==5
    blocked=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':challenge_b.json()['challenge_token'],'code':totp(challenge_b.json()['secret'])})
    assert blocked.status_code==429,blocked.text
    challenge_c=client.post('/api/v1/auth/login',json=credentials)
    assert challenge_c.status_code==429,challenge_c.text
    assert 'geocattle_session' not in client.cookies
    assert client.get('/api/v1/v3/admin/kpis').status_code==401


def test_owner_without_farm_gets_actionable_dashboard_conflict(v3):
    uid=uuid4()
    identity=User(id=uid,username=f'owner-empty-{uid}@qa.test',email=f'owner-empty-{uid}@qa.test',full_name='Dueño sin predio',password_hash=PASSWORD_HASH,role='owner',active=True)
    v3.db.add(identity);v3.db.flush()
    v3.db.add(OwnerAccount(id=uuid4(),owner_user_id=uid,display_name='Cuenta nueva',max_farms=1));v3.db.commit()
    v3.users['empty_owner']=identity
    owner=v3.client('empty_owner')
    response=owner.get('/api/v1/dashboard')
    assert response.status_code==409,response.text
    farms=owner.get('/api/v1/v3/farms')
    assert farms.status_code==200 and farms.json()['items']==[]
    assert owner.get('/api/v1/auth/me').json()['user']['farm_id'] is None


def test_owner_can_list_and_reactivate_owned_inactive_farm_only(v3):
    owner=v3.client('owner');foreign=v3.client('other_owner')
    ident=str(v3.farms['owner'].id)
    disabled=owner.patch(f'/api/v1/v3/farms/{ident}',json={'active':False})
    assert disabled.status_code==200 and disabled.json()['active'] is False,disabled.text
    listing=owner.get('/api/v1/v3/farms')
    assert listing.status_code==200,listing.text
    assert [(item['id'],item['active']) for item in listing.json()['items']]==[(ident,False)]
    assert owner.get('/api/v1/dashboard').status_code==409
    denied=foreign.patch(f'/api/v1/v3/farms/{ident}',json={'active':True})
    assert denied.status_code==403,denied.text
    restored=owner.patch(f'/api/v1/v3/farms/{ident}',json={'active':True})
    assert restored.status_code==200 and restored.json()['active'] is True,restored.text
    assert owner.get('/api/v1/dashboard').status_code==200
    me=owner.get('/api/v1/auth/me')
    assert me.status_code==200 and me.json()['user']['farm_id']==ident


def test_owner_can_manage_inactive_farm_without_using_it_as_context(v3):
    client=v3.client('owner');farm=v3.farms['owner']
    disabled=client.patch(f'/api/v1/v3/farms/{farm.id}',json={'active':False})
    assert disabled.status_code==200,disabled.text
    listed=client.get('/api/v1/v3/farms')
    assert listed.status_code==200
    assert any(item['id']==str(farm.id) and not item['active'] for item in listed.json()['items'])
    assert client.get('/api/v1/dashboard').status_code==409
    enabled=client.patch(f'/api/v1/v3/farms/{farm.id}',json={'active':True})
    assert enabled.status_code==200,enabled.text
    assert client.get('/api/v1/dashboard').status_code==200
