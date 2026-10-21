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
