"""Regression: los endpoints originales preservan el contexto histórico V3.
Requiere TEST_DATABASE_URL con las tres migraciones; revierte todos los datos.
"""
import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from geocattle.db import get_db
from geocattle.main import app
from geocattle.models import AnimalHolding, Assignment, Farm, PastureAssignment, RuleSettings, User
from geocattle.security import hash_password
from geocattle.settings import settings

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Requiere PostgreSQL/PostGIS temporal migrado')

@pytest.fixture
def legacy_v3(monkeypatch):
    engine=create_engine(os.environ['TEST_DATABASE_URL'])
    with engine.connect() as conn:
        outer=conn.begin()
        db=Session(conn,join_transaction_mode='create_savepoint',expire_on_commit=False)
        farm=Farm(id=uuid4(),name='QA API legado/V3',environment=settings().app_env)
        db.add(farm);db.flush()
        owner=User(id=uuid4(),farm_id=farm.id,username=f'qa-v3-{uuid4()}@test.local',role='owner',password_hash=hash_password('test-only-strong-password'),active=True)
        db.add_all([owner,RuleSettings(farm_id=farm.id)]);db.commit()
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
        # El middleware usa la misma conexión para que sus FK puedan ver las
        # filas de esta transacción de QA y tampoco persista métricas ficticias.
        monkeypatch.setattr('geocattle.db.SessionLocal',SimpleNamespace(begin=metrics_transaction))
        app.dependency_overrides[get_db]=override
        with TestClient(app) as client:
            login=client.post('/api/v1/auth/login',json={'username':owner.username,'password':'test-only-strong-password'})
            assert login.status_code==200,login.text
            client.headers['X-CSRF-Token']=login.json()['csrf_token']
            yield db,client,farm,owner
        app.dependency_overrides.clear();db.close();outer.rollback()
    engine.dispose()


def register_animal(client):
    response=client.post('/api/v1/animals',json={'diio':f'QA-{uuid4()}','name':'Bovino QA','orientation':'milk'})
    assert response.status_code==201,response.text
    return UUID(response.json()['id'])


def test_legacy_animal_and_collar_assignment_keep_holding(legacy_v3):
    db,client,farm,owner=legacy_v3
    animal=register_animal(client)
    holding=db.scalar(select(AnimalHolding).where(AnimalHolding.animal_id==animal))
    assert holding and holding.farm_id==farm.id
    device=client.post('/api/v1/devices',json={'hardware_id':f'qa-{uuid4()}','name':'Collar QA','transport':'academic'})
    assert device.status_code==201,device.text
    assigned=client.post('/api/v1/assignments',json={'animal_id':str(animal),'device_id':device.json()['id']})
    assert assigned.status_code==201,assigned.text
    row=db.get(Assignment,UUID(assigned.json()['id']))
    assert row.animal_holding_id==holding.id
    assert row.assigned_by==owner.id


def test_legacy_pasture_and_new_fence_version_keep_holding(legacy_v3):
    db,client,farm,owner=legacy_v3
    animal=register_animal(client)
    holding=db.scalar(select(AnimalHolding).where(AnimalHolding.animal_id==animal))
    sector=client.post('/api/v1/sectors',json={'name':'Sector QA'})
    assert sector.status_code==201,sector.text
    geometry={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}
    body={'sector_id':sector.json()['id'],'name':'Geocerca QA','geometry':geometry,'expected_version':0,'confirm_impact':True}
    fence=client.post('/api/v1/geofences',json=body)
    assert fence.status_code==201,fence.text
    pasture=client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':fence.json()['id']})
    assert pasture.status_code==201,pasture.text
    first=db.get(PastureAssignment,UUID(pasture.json()['id']))
    assert first.animal_holding_id==holding.id
    assert first.assigned_by==owner.id
    updated=client.post('/api/v1/geofences',json={**body,'expected_version':1,'name':'Geocerca QA V2'})
    assert updated.status_code==201,updated.text
    db.expire_all()
    rows=db.scalars(select(PastureAssignment).where(PastureAssignment.animal_id==animal).order_by(PastureAssignment.valid_from)).all()
    assert len(rows)==2
    assert all(row.animal_holding_id==holding.id for row in rows)
    assert rows[0].valid_to==rows[1].valid_from
    assert rows[1].valid_to is None

# Association regression checks use the same rollback fixture as the V3 tests.
from datetime import timedelta
from sqlalchemy import func
from geocattle.domain import ingest
from geocattle.models import Animal, AnimalState, Audit, Device, Event, Geofence, Sector, Telemetry, utcnow
from geocattle.schemas import TelemetryIn


def register_device(client):
    response=client.post('/api/v1/devices',json={'hardware_id':f'qa-{uuid4()}','name':'Collar QA','transport':'academic'})
    assert response.status_code==201,response.text
    return UUID(response.json()['id'])


def register_fence(client,name='Sector QA'):
    sector=client.post('/api/v1/sectors',json={'name':name})
    assert sector.status_code==201,sector.text
    geometry={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}
    fence=client.post('/api/v1/geofences',json={'sector_id':sector.json()['id'],'name':f'Geocerca {name}','geometry':geometry,'expected_version':0,'confirm_impact':True})
    assert fence.status_code==201,fence.text
    return UUID(sector.json()['id']),UUID(fence.json()['id'])


def receive_packet(db,device_id,seq,observed_at=None,battery_mv=3000):
    device=db.get(Device,device_id)
    at=observed_at or utcnow()
    payload=TelemetryIn(hardware_id=device.hardware_id,session_id='qa-association',seq=seq,observed_at=at,longitude=.5,latitude=.5,gnss_valid=True,battery_mv=battery_mv,source='academic')
    result=ingest(db,payload,received_at=at)
    return db.get(Telemetry,UUID(result['id']))


def test_reassignment_clears_both_animals_without_rewriting_evidence(legacy_v3):
    db,client,farm,owner=legacy_v3
    first,second=register_animal(client),register_animal(client)
    first_device,second_device=register_device(client),register_device(client)
    for animal,device in ((first,first_device),(second,second_device)):
        assigned=client.post('/api/v1/assignments',json={'animal_id':str(animal),'device_id':str(device)})
        assert assigned.status_code==201,assigned.text
    first_reading=receive_packet(db,first_device,1)
    second_reading=receive_packet(db,second_device,1)
    first_reading_id,second_reading_id=first_reading.id,second_reading.id
    old_events=db.scalars(select(Event).where(Event.farm_id==farm.id,Event.condition=='active')).all()
    assert len(old_events)==2
    db.commit()
    replacement=client.post('/api/v1/assignments',json={'animal_id':str(second),'device_id':str(first_device),'replace':True})
    assert replacement.status_code==201,replacement.text
    db.expire_all()
    for animal_id in (first,second):
        state=db.get(AnimalState,animal_id)
        assert state.telemetry_id is None and state.position_telemetry_id is None
        assert state.observed_at is None and state.geofence_status=='unknown' and state.outside_count==0
    assert db.get(Telemetry,first_reading_id).animal_id==first
    assert db.get(Telemetry,second_reading_id).animal_id==second
    for event in old_events:
        assert event.condition=='resolved'
        assert event.telemetry_id in (first_reading_id,second_reading_id)
        assert event.detail['resolution_reason']=='assignment_closed'
        assert db.scalar(select(Audit).where(Audit.object_id==str(event.id),Audit.actor_id==owner.id,Audit.action=='resolved'))
    assert client.get(f'/api/v1/animals/{first}').json()['device_id'] is None
    assert client.get(f'/api/v1/animals/{second}').json()['device_id']==str(first_device)
    assert db.scalar(select(Assignment).where(Assignment.device_id==second_device,Assignment.valid_to.is_(None))) is None
    receive_packet(db,first_device,2)
    new_event=db.scalar(select(Event).where(Event.device_id==first_device,Event.condition=='active',Event.type=='low_battery'))
    assert new_event and new_event.animal_id==second
    assert new_event.id not in {event.id for event in old_events}


def test_retroactive_reassignment_cannot_cut_persisted_telemetry(legacy_v3):
    db,client,farm,owner=legacy_v3
    first,second=register_animal(client),register_animal(client)
    device=register_device(client)
    assigned=client.post('/api/v1/assignments',json={'animal_id':str(first),'device_id':str(device)})
    assert assigned.status_code==201,assigned.text
    assignment=db.get(Assignment,UUID(assigned.json()['id']))
    at=assignment.valid_from+timedelta(seconds=1)
    reading=receive_packet(db,device,1,observed_at=at)
    reading_id,assignment_id=reading.id,assignment.id
    cut=assignment.valid_from+timedelta(milliseconds=100)
    db.commit()
    denied=client.post('/api/v1/assignments',json={'animal_id':str(second),'device_id':str(device),'replace':True,'effective_at':cut.isoformat()})
    assert denied.status_code==409,denied.text
    assert 'lecturas históricas' in denied.json()['detail']
    db.expire_all()
    assert db.get(Assignment,assignment_id).valid_to is None
    assert db.get(Telemetry,reading_id).animal_id==first


@pytest.mark.parametrize('remove_sector',[False,True])
def test_animal_sector_must_match_current_pasture(legacy_v3,remove_sector):
    db,client,farm,owner=legacy_v3
    animal=register_animal(client)
    first_sector,first_fence=register_fence(client,'Primero')
    second_sector,second_fence=register_fence(client,'Segundo')
    assigned=client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':str(first_fence)})
    assert assigned.status_code==201,assigned.text
    denied=client.patch(f'/api/v1/animals/{animal}',json={'sector_id':None if remove_sector else str(second_sector)})
    assert denied.status_code==409,denied.text
    unchanged=client.get(f'/api/v1/animals/{animal}').json()
    assert unchanged['sector_id']==str(first_sector)
    same=client.patch(f'/api/v1/animals/{animal}',json={'sector_id':str(first_sector),'name':'Nombre actualizado'})
    assert same.status_code==200,same.text
    moved=client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':str(second_fence)})
    assert moved.status_code==201,moved.text
    db.expire_all()
    history=db.scalars(select(PastureAssignment).where(PastureAssignment.animal_id==animal).order_by(PastureAssignment.valid_from)).all()
    assert len(history)==2 and history[0].valid_to==history[1].valid_from
    assert history[1].geofence_id==second_fence
    assert client.get(f'/api/v1/animals/{animal}').json()['sector_id']==str(second_sector)


def test_inactive_sector_and_disabled_animal_are_not_new_pasture_targets(legacy_v3):
    db,client,farm,owner=legacy_v3
    animal=register_animal(client)
    sector,fence=register_fence(client)
    assert db.get(Geofence,fence).created_by==owner.id
    db.get(Sector,sector).active=False
    db.commit()
    denied=client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':str(fence)})
    assert denied.status_code==409,denied.text
    geometry={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}
    denied=client.post('/api/v1/geofences',json={'sector_id':str(sector),'name':'No activa','geometry':geometry,'expected_version':1,'confirm_impact':True})
    assert denied.status_code==409,denied.text
    denied=client.post('/api/v1/animals',json={'diio':f'QA-{uuid4()}','name':'No activo','orientation':'milk','sector_id':str(sector)})
    assert denied.status_code==409,denied.text
    db.get(Sector,sector).active=True
    db.get(Animal,animal).enabled=False
    db.commit()
    denied=client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':str(fence)})
    assert denied.status_code==409,denied.text


def test_associations_reject_resources_from_another_farm(legacy_v3):
    db,client,farm,owner=legacy_v3
    animal=register_animal(client)
    foreign=Farm(id=uuid4(),name='QA predio ajeno',environment=settings().app_env)
    db.add(foreign);db.flush()
    sector=Sector(id=uuid4(),farm_id=foreign.id,name='QA sector ajeno')
    device=Device(id=uuid4(),farm_id=foreign.id,name='QA collar ajeno',hardware_id=f'qa-{uuid4()}',transport='academic')
    db.add_all([sector,device]);db.flush()
    fence=Geofence(id=uuid4(),farm_id=foreign.id,sector_id=sector.id,name='QA geocerca ajena',version=1,geometry=func.ST_GeomFromText('POLYGON((0 0,1 0,1 1,0 1,0 0))',4326),active=True,created_at=utcnow())
    db.add(fence);db.flush()
    sector_id,device_id,fence_id=sector.id,device.id,fence.id
    db.commit()
    assert client.post('/api/v1/assignments',json={'animal_id':str(animal),'device_id':str(device_id)}).status_code==403
    assert client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':str(fence_id)}).status_code==403
    assert client.patch(f'/api/v1/animals/{animal}',json={'sector_id':str(sector_id)}).status_code==403


@pytest.mark.parametrize('member_role',['worker','veterinarian'])
def test_collaborators_can_read_but_cannot_change_associations(legacy_v3,member_role):
    db,client,farm,owner=legacy_v3
    animal=register_animal(client)
    device=register_device(client)
    sector,fence=register_fence(client)
    member=User(id=uuid4(),farm_id=farm.id,username=f'qa-{uuid4()}@test.local',role=member_role,password_hash=hash_password('test-only-strong-password'),active=True)
    db.add(member);db.flush()
    db.execute(text('INSERT INTO farm_memberships(id,farm_id,user_id,role_code,granted_by) VALUES(:i,:f,:u,:r,:o)'),{'i':uuid4(),'f':farm.id,'u':member.id,'r':member_role,'o':owner.id})
    username=member.username
    db.commit()
    login=client.post('/api/v1/auth/login',json={'username':username,'password':'test-only-strong-password'})
    assert login.status_code==200,login.text
    client.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert client.get(f'/api/v1/animals/{animal}').status_code==200
    assert client.get('/api/v1/geofences').status_code==200
    assert client.get(f'/api/v1/animals/{animal}/assignments').status_code==200
    assert client.post('/api/v1/assignments',json={'animal_id':str(animal),'device_id':str(device)}).status_code==403
    assert client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':str(fence)}).status_code==403
    assert client.patch(f'/api/v1/animals/{animal}',json={'sector_id':str(sector)}).status_code==403


def test_current_and_paginated_historical_associations_are_explicit(legacy_v3):
    db,client,farm,owner=legacy_v3
    animal=register_animal(client)
    device=register_device(client)
    collar=client.post('/api/v1/assignments',json={'animal_id':str(animal),'device_id':str(device)})
    assert collar.status_code==201,collar.text
    sector,fence=register_fence(client)
    pasture=client.post('/api/v1/pasture-assignments',json={'animal_id':str(animal),'geofence_id':str(fence)})
    assert pasture.status_code==201,pasture.text
    old=client.get('/api/v1/geofences').json()['items'][0]
    updated=client.post('/api/v1/geofences',json={'sector_id':str(sector),'name':old['name'],'geometry':old['geometry'],'expected_version':1,'confirm_impact':True})
    assert updated.status_code==201,updated.text
    detail=client.get(f'/api/v1/animals/{animal}').json()
    assert detail['collar_assignment']['id']==collar.json()['id']
    assert detail['pasture_assignment']['geofence_id']==updated.json()['id']
    assert detail['pasture_assignment']['geofence_version']==2
    assert detail['pasture_assignment']['sector_id']==str(sector)
    assert detail['pasture_assignment']['valid_to'] is None
    history=client.get(f'/api/v1/animals/{animal}/assignments?limit=2').json()
    assert history['total']==3 and len(history['items'])==2
    assert all(row['kind']=='pasture' for row in history['items'])
    assert history['items'][0]['active'] and not history['items'][1]['active']
    assert history['items'][0]['assigned_by']==str(owner.id)
    older=client.get(f'/api/v1/animals/{animal}/assignments?limit=2&offset=2').json()
    assert older['total']==3 and len(older['items'])==1
    assert older['items'][0]['kind']=='collar' and older['items'][0]['device_id']==str(device)
    assert client.get(f'/api/v1/animals/{animal}/assignments?limit=201').status_code==422
    assert client.get(f'/api/v1/animals/{animal}/assignments?offset=-1').status_code==422
