"""Gateway inventory CRUD, isolation, concurrency and immutable receptions."""
import os
from uuid import UUID,uuid4
import pytest
from sqlalchemy import text
from geocattle.models import User
from geocattle.v3_security import totp
from test_v3_api import v3,PASSWORD

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Requires migrated isolated PostgreSQL/PostGIS')
BASE='/api/v1/v3/gateways'

def login(v3,role='owner',context=True):
    client=v3.client(role,login=role!='admin')
    if role=='admin':
        challenge=client.post('/api/v1/auth/login',json={'username':v3.users['admin'].username,'password':PASSWORD}).json()
        verified=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':challenge['challenge_token'],'code':totp(challenge['secret'])})
        assert verified.status_code==200,verified.text
        client.headers['X-CSRF-Token']=verified.json()['csrf_token']
        if context:
            response=client.post('/api/v1/auth/context',json={'farm_id':str(v3.farms['owner'].id)})
            assert response.status_code==200,response.text
    return client

def payload(**changes):return {'name':'Gateway QA','gateway_eui':uuid4().hex[:16],'latitude':-38.745,'longitude':-72.645,**changes}
def create(client,**changes):
    data=payload();data.update(changes);r=client.post(BASE,json=data);assert r.status_code==201,r.text;return r.json()
def audit_rows(v3,ident):return v3.db.execute(text("SELECT action,actor_id,farm_id,before,after FROM audit_log WHERE object_type='gateway' AND object_id=:i ORDER BY at,id"),{'i':ident}).mappings().all()

@pytest.mark.parametrize('role',['owner','admin'])
def test_create_read_move_archive_by_role(v3,role):
    client=login(v3,role)
    original=create(client,gateway_eui=uuid4().hex[:16].upper(),name='  Gateway de prueba  ')
    ident=original['id']
    assert original['name']=='Gateway de prueba' and original['gateway_eui']==original['gateway_eui'].lower()
    assert original['version']==1 and original['archived_at'] is None
    detail=client.get(f'{BASE}/{ident}');assert detail.status_code==200,detail.text
    assert detail.json()['latitude']==-38.745 and detail.json()['reception_count']==0
    moved=client.patch(f'{BASE}/{ident}',json={'name':'Nuevo nombre','status':'maintenance','latitude':0,'longitude':0,'expected_version':1})
    assert moved.status_code==200,moved.text
    moved=moved.json();assert moved['version']==2 and moved['latitude']==moved['longitude']==0
    assert moved['id']==ident and moved['gateway_eui']==original['gateway_eui']
    assert client.patch(f'{BASE}/{ident}',json={'name':'Sobrescritura','expected_version':1}).status_code==409
    assert client.get(f'{BASE}/{ident}').json()['name']=='Nuevo nombre'
    # Status retired is still operational inventory; archive is a separate action.
    retired=client.patch(f'{BASE}/{ident}',json={'status':'retired','expected_version':2}).json()
    assert any(g['id']==ident for g in client.get(BASE).json()['items'])
    assert client.request('DELETE',f'{BASE}/{ident}',json={'expected_version':retired['version'],'confirm':False}).status_code==422
    archived=client.request('DELETE',f'{BASE}/{ident}',json={'expected_version':retired['version'],'confirm':True})
    assert archived.status_code==200,archived.text
    assert archived.json()['archived_at'] and archived.json()['status']=='retired'
    assert all(g['id']!=ident for g in client.get(BASE).json()['items'])
    assert any(g['id']==ident for g in client.get(BASE+'?include_archived=true').json()['items'])
    assert client.get(f'{BASE}/{ident}').json()['archived_at']
    assert client.get(f'{BASE}/{ident}/receptions').json()=={'items':[],'total':0}
    assert client.patch(f'{BASE}/{ident}',json={'name':'No','expected_version':archived.json()['version']}).status_code==409
    assert client.request('DELETE',f'{BASE}/{ident}',json={'expected_version':retired['version'],'confirm':True}).status_code==200
    audits=audit_rows(v3,ident);assert sorted(a['action'] for a in audits)==['archive','create','update','update']
    assert all(a['actor_id']==v3.users[role].id and a['farm_id']==v3.farms['owner'].id for a in audits)
    update=next(a for a in audits if a['action']=='update' and a['after']['name']=='Nuevo nombre' and a['before']['name']!='Nuevo nombre')
    assert update['before']['latitude']==-38.745 and update['after']['latitude']==0

@pytest.mark.parametrize('role',['worker','vet','viewer'])
def test_consultation_without_write_privilege(v3,role):
    owner=login(v3);gateway=create(owner);client=v3.client(role);ident=gateway['id']
    assert client.get(BASE).status_code==200
    assert client.get(f'{BASE}/{ident}').status_code==200
    assert client.post(BASE,json=payload()).status_code==403
    assert client.patch(f'{BASE}/{ident}',json={'expected_version':1,'name':'No'}).status_code==403
    assert client.request('DELETE',f'{BASE}/{ident}',json={'expected_version':1,'confirm':True}).status_code==403


def test_no_context_and_cross_farm_access(v3):
    owner=login(v3);g=create(owner);other=v3.client('other_owner');ident=g['id']
    assert other.get(BASE).json()['items']==[]
    for path in (f'{BASE}/{ident}',f'{BASE}/{ident}/receptions'):assert other.get(path).status_code==403
    assert other.patch(f'{BASE}/{ident}',json={'expected_version':1,'latitude':1,'longitude':1}).status_code==403
    assert other.request('DELETE',f'{BASE}/{ident}',json={'expected_version':1,'confirm':True}).status_code==403
    assert owner.get(f'{BASE}/{ident}').json()['version']==1
    admin=login(v3,'admin',context=False)
    assert admin.get(BASE).status_code==409
    assert admin.post(BASE,json=payload()).status_code==409
    assert admin.patch(f'{BASE}/{ident}',json={'expected_version':1,'name':'No'}).status_code==409
    assert admin.request('DELETE',f'{BASE}/{ident}',json={'expected_version':1,'confirm':True}).status_code==409
    assert v3.client('owner',login=False).get(BASE).status_code==401

@pytest.mark.parametrize('changes',[{'latitude':None},{'longitude':None},{'latitude':91},{'longitude':181},{'latitude':True},{'latitude':'NaN'},{'latitude':'Infinity'},{'name':'  '},{'gateway_eui':'bad'}])
def test_invalid_creation_rejected(v3,changes):
    client=login(v3);body=payload();body.update(changes)
    assert client.post(BASE,json=body).status_code==422
    assert client.get(BASE).json()['total']==0


def test_required_location_duplicate_identity_and_atomic_patch(v3):
    client=login(v3);g=create(client);ident=g['id']
    body=payload();body.pop('latitude');assert client.post(BASE,json=body).status_code==422
    assert client.post(BASE,json=payload(gateway_eui=g['gateway_eui'].upper())).status_code==409
    for invalid in ({'longitude':1},{'latitude':None,'longitude':None},{'latitude':-91,'longitude':1},{'latitude':1,'longitude':181},{'name':None},{'name':' '},{'status':None},{'gateway_eui':uuid4().hex[:16]}):
        response=client.patch(f'{BASE}/{ident}',json={'expected_version':1,**invalid})
        assert response.status_code==422,response.text
        assert client.get(f'{BASE}/{ident}').json()['version']==1
    assert client.request('DELETE',f'{BASE}/{ident}',json={'expected_version':999,'confirm':True}).status_code==409
    assert len(audit_rows(v3,ident))==1


def test_legacy_without_position_can_be_consulted_and_completed(v3):
    client=login(v3);ident=uuid4();farm=v3.farms['owner'].id
    v3.db.execute(text("INSERT INTO gateways(id,farm_id,gateway_eui,name,status) VALUES(:i,:f,:e,'Legado','installed')"),dict(i=ident,f=farm,e=uuid4().hex[:16]));v3.db.commit()
    detail=client.get(f'{BASE}/{ident}').json();assert detail['latitude'] is detail['longitude'] is None
    name_only=client.patch(f'{BASE}/{ident}',json={'expected_version':1,'name':'Legado conservado'});assert name_only.status_code==200,name_only.text
    assert name_only.json()['latitude'] is None
    completed=client.patch(f'{BASE}/{ident}',json={'expected_version':2,'latitude':-38,'longitude':-72});assert completed.status_code==200,completed.text
    assert completed.json()['latitude']==-38 and completed.json()['longitude']==-72


def test_noop_update_does_not_create_audit_or_version(v3):
    client=login(v3);g=create(client)
    unchanged=client.patch(f"{BASE}/{g['id']}",json={'expected_version':1,'name':g['name'],'latitude':g['latitude'],'longitude':g['longitude']})
    assert unchanged.status_code==200 and unchanged.json()['version']==1
    assert len(audit_rows(v3,g['id']))==1


def test_move_archive_and_new_receptions_preserve_original_evidence(v3):
    from datetime import timedelta
    from geocattle.domain import ingest
    from geocattle.schemas import TelemetryIn,ReceptionIn
    from geocattle.models import utcnow
    client=login(v3);g=create(client);ident=g['id']
    device=client.post('/api/v1/devices',json={'name':'Collar QA','hardware_id':f'qa-gateway-{uuid4()}','transport':'academic'})
    assert device.status_code==201,device.text
    device=device.json();animal=v3.animals['owner']
    assigned=client.post('/api/v1/assignments',json={'animal_id':str(animal.id),'device_id':device['id']});assert assigned.status_code==201,assigned.text
    at=utcnow()
    source='sim' if os.environ.get('APP_ENV')=='simulation' else 'academic'
    sample=TelemetryIn(hardware_id=device['hardware_id'],session_id='qa-gateways',seq=1,observed_at=at,gnss_valid=True,latitude=-38.745,longitude=-72.645,source=source,receptions=[ReceptionIn(gateway_eui=g['gateway_eui'],rssi_dbm=-88,snr_db=6.25)])
    original=ingest(v3.db,sample,received_at=at);v3.db.commit()
    before=v3.db.execute(text('SELECT to_jsonb(r) FROM telemetry_receptions r WHERE gateway_id=:g'),{'g':UUID(ident)}).scalar_one()
    original_reading=v3.db.execute(text('SELECT to_jsonb(t) FROM telemetry t WHERE id=:i'),{'i':UUID(original['id'])}).scalar_one()
    moved=client.patch(f'{BASE}/{ident}',json={'expected_version':1,'latitude':-39,'longitude':-73});assert moved.status_code==200,moved.text
    archived=client.request('DELETE',f'{BASE}/{ident}',json={'expected_version':2,'confirm':True});assert archived.status_code==200,archived.text
    detail=client.get(f'{BASE}/{ident}').json();assert detail['reception_count']==1 and detail['last_seen_at']
    history=client.get(f'{BASE}/{ident}/receptions?limit=1&offset=0').json()
    assert history['total']==1 and history['items'][0]['telemetry_id']==original['id']
    assert history['items'][0]['hardware_id']==device['hardware_id'] and float(history['items'][0]['rssi_dbm'])==-88
    assert client.get(f'{BASE}/{ident}/receptions?limit=1&offset=1').json()['items']==[]
    # Archiving inventory must not discard valid radio evidence or reactivate it.
    next_sample=sample.model_copy(update={'seq':2,'observed_at':at+timedelta(seconds=1)})
    ingest(v3.db,next_sample,received_at=at+timedelta(seconds=1));v3.db.commit()
    assert client.get(f'{BASE}/{ident}').json()['reception_count']==2
    assert all(row['id']!=ident for row in client.get(BASE).json()['items'])
    assert v3.db.execute(text('SELECT to_jsonb(r) FROM telemetry_receptions r WHERE gateway_id=:g AND telemetry_id=:i'),{'g':UUID(ident),'i':UUID(original['id'])}).scalar_one()==before
    assert v3.db.execute(text('SELECT to_jsonb(t) FROM telemetry t WHERE id=:i'),{'i':UUID(original['id'])}).scalar_one()==original_reading


def test_database_rejects_rewriting_gateway_identity(v3):
    from sqlalchemy.exc import IntegrityError
    client=login(v3);g=create(client)
    with pytest.raises(IntegrityError):
        with v3.db.begin_nested():
            v3.db.execute(text('UPDATE gateways SET gateway_eui=:e WHERE id=:i'),{'i':UUID(g['id']),'e':uuid4().hex[:16]})
    assert client.get(f"{BASE}/{g['id']}").json()['gateway_eui']==g['gateway_eui']
