"""Regression coverage for identities, sector isolation and frozen locations."""
import os
from datetime import timedelta
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from geocattle.models import Assignment, Device, Event, Geofence, GeofenceSector, Sector, Telemetry, RuleSettings, utcnow
from geocattle.domain import check_timeouts, ingest
from geocattle.schemas import TelemetryIn, GeofenceIn
from test_v3_legacy_assignments import legacy_v3, register_animal, register_device
from test_v3_api import v3, PASSWORD
from geocattle.v3_security import totp

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Requires migrated PostgreSQL QA database')
POLYGON={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}

def fence_body(sectors, **changes):
    return {'name':'QA independent','sector_ids':sectors,'geometry':POLYGON,'expected_version':0,'confirm_impact':True,**changes}

def sector(client,name):
    r=client.post('/api/v1/sectors',json={'name':name}); assert r.status_code==201,r.text
    return r.json()['id']

@pytest.mark.parametrize('role',['owner','admin'])
def test_multiple_fences_versions_and_sectors_by_role(v3,role):
    client=v3.client(role,login=role!='admin')
    if role=='admin':
        login=client.post('/api/v1/auth/login',json={'username':v3.users['admin'].username,'password':PASSWORD}).json()
        verified=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':login['challenge_token'],'code':totp(login['secret'])})
        assert verified.status_code==200,verified.text
        client.headers['X-CSRF-Token']=verified.json()['csrf_token']
        assert client.post('/api/v1/auth/context',json={'farm_id':str(v3.farms['owner'].id)}).status_code==200
    a,b=sector(client,'Sector A'),sector(client,'Sector B')
    first=client.post('/api/v1/geofences',json=fence_body([a,b]));assert first.status_code==201,first.text
    first=first.json()
    second=client.post('/api/v1/geofences',json=fence_body([a],name='Otra zona'));assert second.status_code==201,second.text
    assert first['geofence_key']!=second.json()['geofence_key']
    update=client.post('/api/v1/geofences',json=fence_body([a,b],geofence_key=first['geofence_key'],expected_version=1,name='Zona editada'))
    assert update.status_code==201,update.text
    assert update.json()['version']==2 and update.json()['geofence_key']==first['geofence_key']
    rows=client.get('/api/v1/geofences').json()['items']
    assert {x['id'] for x in rows if x['active']}=={update.json()['id'],second.json()['id']}
    assert next(x for x in rows if x['id']==first['id'])['sector_ids']==first['sector_ids']
    assert update.json()['geometry']==POLYGON
    stale=client.post('/api/v1/geofences',json=fence_body([a,b],geofence_key=first['geofence_key'],expected_version=1))
    assert stale.status_code==409
    ambiguous=client.post('/api/v1/geofences',json=fence_body([a],expected_version=2))
    assert ambiguous.status_code==409
    assert set(update.json()['sector_ids'])=={a,b}


def test_sector_and_identity_cannot_cross_farms(v3):
    owner,other=v3.client('owner'),v3.client('other_owner')
    a,b=sector(owner,'Own sector'),sector(other,'Foreign sector')
    foreign=other.post('/api/v1/geofences',json=fence_body([b])).json()
    assert owner.post('/api/v1/geofences',json=fence_body([a,b])).status_code==403
    assert owner.post('/api/v1/geofences',json=fence_body([a],geofence_key=foreign['geofence_key'],expected_version=1)).status_code==403
    assert owner.get('/api/v1/geofences').json()['items']==[]
    worker=v3.client('worker')
    assert worker.post('/api/v1/geofences',json=fence_body([a])).status_code==403


def test_geometry_and_inactive_sector_rejected(legacy_v3):
    db,client,_,_=legacy_v3;a=sector(client,'Sector QA')
    crossed={'type':'Polygon','coordinates':[[[0,0],[1,1],[0,1],[1,0],[0,0]]]}
    assert client.post('/api/v1/geofences',json=fence_body([a],geometry=crossed)).status_code==422
    db.get(Sector,UUID(a)).active=False;db.commit()
    assert client.post('/api/v1/geofences',json=fence_body([a])).status_code==409


def prepare_readings(data):
    db,client,farm,_=data
    animal=register_animal(client);device=register_device(client)
    response=client.post('/api/v1/assignments',json={'animal_id':str(animal),'device_id':str(device)})
    assert response.status_code==201,response.text
    assignment=db.get(Assignment,UUID(response.json()['id']))
    now=utcnow()+timedelta(seconds=2)
    return db,client,farm,animal,device,assignment,now

def reading(db,device,at,seq,valid=True,temperature=None):
    device=db.get(Device,device)
    source='sim' if os.environ.get('APP_ENV')=='simulation' else 'academic'
    payload=TelemetryIn(hardware_id=device.hardware_id,session_id='qa-frozen',seq=seq,observed_at=at,gnss_valid=valid,latitude=.5 if valid else None,longitude=.5 if valid else None,source=source,surface_temperature_c=temperature)
    result=ingest(db,payload,received_at=at);db.flush();return db.get(Telemetry,UUID(result['id']))


def test_timeout_position_frozen_after_invalid_fix_and_reconnection(legacy_v3):
    db,client,farm,animal,device,assignment,now=prepare_readings(legacy_v3)
    good=reading(db,device,now,1);reading(db,device,now+timedelta(seconds=1),2,False)
    check_timeouts(db,now+timedelta(seconds=1000));db.commit()
    event=db.scalar(select(Event).where(Event.device_id==device,Event.type=='communication_timeout'))
    assert event.last_position_id==good.id
    original=next(x for x in client.get('/api/v1/events').json()['items'] if x['id']==str(event.id))
    assert original['last_known_position']['telemetry']['id']==str(good.id)
    attention=client.post(f'/api/v1/events/{event.id}/actions',json={'action':'acknowledge','note':'QA revisión'})
    assert attention.status_code==200 and attention.json()['condition']=='active'
    reading(db,device,now+timedelta(seconds=1001),3);db.commit()
    updated=next(x for x in client.get('/api/v1/events').json()['items'] if x['id']==str(event.id))
    assert updated['condition']=='resolved'
    assert updated['last_known_position']==original['last_known_position']


def test_timeout_no_fix_and_old_association_are_not_used(legacy_v3):
    db,client,farm,animal,device,assignment,now=prepare_readings(legacy_v3)
    reading(db,device,now,1,False);check_timeouts(db,now+timedelta(seconds=1000))
    event=db.scalar(select(Event).where(Event.device_id==device,Event.type=='communication_timeout'))
    assert event.last_position_id is None
    # A valid packet received after detection cannot become historical evidence.
    late=reading(db,device,now+timedelta(seconds=1001),2);db.commit()
    row=next(x for x in client.get('/api/v1/events').json()['items'] if x['id']==str(event.id))
    assert row['last_known_position'] is None


def test_temperature_missing_duplicate_late_and_threshold(legacy_v3):
    db,client,farm,animal,device,assignment,now=prepare_readings(legacy_v3)
    rules=db.get(RuleSettings,farm.id);rules.temperature_enabled=True;rules.temperature_high_c=39.5;db.flush()
    high=reading(db,device,now,1,temperature=39.5)
    event=db.scalar(select(Event).where(Event.device_id==device,Event.type=='high_surface_temperature'))
    assert event and event.condition=='active' and event.telemetry_id==high.id
    reading(db,device,now+timedelta(seconds=1),2,temperature=None);assert event.condition=='active'
    reading(db,device,now-timedelta(seconds=1),3,temperature=20);assert event.condition=='active'
    reading(db,device,now+timedelta(seconds=2),2,temperature=20);assert event.condition=='active' # duplicate
    reading(db,device,now+timedelta(seconds=3),4,temperature=39.4);assert event.condition=='resolved'


def test_previous_collar_assignment_cannot_supply_new_animal_location(legacy_v3):
    from geocattle.models import AnimalHolding, Animal
    db,client,farm,animal,device,assignment,now=prepare_readings(legacy_v3)
    reading(db,device,now,1)
    second=register_animal(client)
    at=now+timedelta(seconds=2)
    assignment.valid_to=at;db.flush()
    holding=db.scalar(select(AnimalHolding).where(AnimalHolding.animal_id==second))
    db.add(Assignment(id=uuid4(),farm_id=farm.id,device_id=device,animal_id=second,animal_holding_id=holding.id,valid_from=at));db.flush()
    check_timeouts(db,at+timedelta(seconds=1000))
    event=db.scalar(select(Event).where(Event.device_id==device,Event.type=='communication_timeout'))
    assert event.animal_id==second and event.last_position_id is None


def test_event_position_cannot_be_replaced_in_database(legacy_v3):
    from sqlalchemy.exc import IntegrityError
    db,client,farm,animal,device,assignment,now=prepare_readings(legacy_v3)
    good=reading(db,device,now,1);check_timeouts(db,now+timedelta(seconds=1000));db.flush()
    event=db.scalar(select(Event).where(Event.device_id==device,Event.type=='communication_timeout'))
    assert event.last_position_id==good.id
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            event.last_position_id=None;db.flush()
    db.refresh(event);assert event.last_position_id==good.id


def test_revision_transfers_only_its_explicit_pasture_assignments(legacy_v3):
    from geocattle.models import PastureAssignment, Animal
    db,client,farm,_=legacy_v3
    sid=sector(client,'Shared sector')
    first=client.post('/api/v1/geofences',json=fence_body([sid],name='First')).json()
    second=client.post('/api/v1/geofences',json=fence_body([sid],name='Second')).json()
    a,b=register_animal(client),register_animal(client)
    for animal,fence in ((a,first),(b,second)):
        r=client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':fence['id']});assert r.status_code==201,r.text
    updated=client.post('/api/v1/geofences',json=fence_body([sid],geofence_key=first['geofence_key'],expected_version=1))
    assert updated.status_code==201,updated.text
    active=db.scalars(select(PastureAssignment).where(PastureAssignment.farm_id==farm.id,PastureAssignment.valid_to.is_(None))).all()
    assert {x.animal_id:x.geofence_id for x in active}=={a:UUID(updated.json()['id']),b:UUID(second['id'])}
    history=db.scalars(select(PastureAssignment).where(PastureAssignment.animal_id==a).order_by(PastureAssignment.valid_from)).all()
    assert len(history)==2 and history[0].geofence_id==UUID(first['id'])
    assert history[0].valid_to==history[1].valid_from
