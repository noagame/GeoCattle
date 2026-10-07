"""PostGIS integration: run with TEST_DATABASE_URL pointing to a migrated test DB.
Each test uses an external rollback transaction; no persisted production writes.
"""
import os
from datetime import timedelta
from uuid import uuid4, UUID
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,func,select,text
from sqlalchemy.orm import Session
from geocattle.models import *
from geocattle.schemas import TelemetryIn
from geocattle.security import hash_password
from geocattle.domain import ingest,check_timeouts
from geocattle.db import get_db
from geocattle.main import app
from geocattle.settings import settings

pytestmark=pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),reason="Requiere PostgreSQL/PostGIS de prueba migrado (TEST_DATABASE_URL)")

@pytest.fixture
def data():
    engine=create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.connect() as conn:
        outer=conn.begin()
        db=Session(conn,join_transaction_mode="create_savepoint",expire_on_commit=False)
        now=utcnow();farm=Farm(id=uuid4(),name="QA integration",environment=settings().app_env)
        db.add(farm);db.flush()
        owner=User(id=uuid4(),farm_id=farm.id,username=f"qa-{uuid4()}@test.local",password_hash=hash_password("test-only-strong-password"),role="owner",active=True)
        db.add(owner);db.add(RuleSettings(farm_id=farm.id));db.flush()
        sector=Sector(id=uuid4(),farm_id=farm.id,name="QA");db.add(sector);db.flush()
        animal=Animal(id=uuid4(),farm_id=farm.id,diio=f"QA-{uuid4()}",name="QA animal",orientation="meat",enabled=True,sector_id=sector.id)
        device=Device(id=uuid4(),farm_id=farm.id,hardware_id=f"qa-{uuid4()}",name="QA module",transport="academic",interval_seconds=300,enabled=True,installed_at=now-timedelta(days=1))
        db.add_all([animal,device]);db.flush()
        fence=Geofence(id=uuid4(),farm_id=farm.id,sector_id=sector.id,name="QA fence",version=1,geometry=func.ST_GeomFromText("POLYGON((0 0,1 0,1 1,0 1,0 0))",4326),active=True,created_at=now-timedelta(days=1))
        db.add(fence);db.flush()
        assignment=Assignment(id=uuid4(),farm_id=farm.id,animal_id=animal.id,device_id=device.id,valid_from=now-timedelta(days=1))
        db.add_all([assignment,PastureAssignment(id=uuid4(),farm_id=farm.id,animal_id=animal.id,geofence_id=fence.id,valid_from=now-timedelta(days=1))]);db.flush()
        db.commit()
        def override():
            try:yield db;db.commit()
            except BaseException:db.rollback();raise
        app.dependency_overrides[get_db]=override
        client=TestClient(app)
        yield db,client,farm,owner,animal,device,fence,assignment,now
        app.dependency_overrides.clear();db.close();outer.rollback()
    engine.dispose()

def packet(device,at,seq,lon=.5,valid=True,session="qa"):
    return TelemetryIn(hardware_id=device.hardware_id,session_id=session,seq=seq,observed_at=at,longitude=lon if valid else None,latitude=.5 if valid else None,gnss_valid=valid,battery_mv=3700,source="sim" if os.environ.get("APP_ENV")=="simulation" else "academic")

def test_border_escape_invalid_consecutive_and_attention(data):
    db,client,farm,user,animal,device,fence,assignment,now=data
    ingest(db,packet(device,now,0,lon=0),now)
    assert db.get(AnimalState,animal.id).geofence_status=="inside"
    ingest(db,packet(device,now+timedelta(seconds=1),1,lon=2),now+timedelta(seconds=1))
    assert not db.scalar(select(Event).where(Event.device_id==device.id,Event.type=="escape"))
    ingest(db,packet(device,now+timedelta(seconds=2),2,valid=False),now+timedelta(seconds=2))
    ingest(db,packet(device,now+timedelta(seconds=3),3,lon=2),now+timedelta(seconds=3))
    assert db.get(AnimalState,animal.id).outside_count==1
    ingest(db,packet(device,now+timedelta(seconds=4),4,lon=2),now+timedelta(seconds=4))
    e=db.scalar(select(Event).where(Event.device_id==device.id,Event.type=="escape"));assert e.condition=="active"
    login=client.post("/api/v1/auth/login",json={"username":user.username,"password":"test-only-strong-password"});assert login.status_code==200
    response=client.post(f"/api/v1/events/{e.id}/actions",headers={"X-CSRF-Token":login.json()["csrf_token"]},json={"action":"conclude","note":"Inspección registrada"})
    assert response.status_code==200 and response.json()["condition"]=="active" and response.json()["attention"]=="concluded"
    assert response.json()["telemetry"]["seq"]==4
    ingest(db,packet(device,now+timedelta(seconds=5),5,valid=False),now+timedelta(seconds=5))
    assert e.condition=="active"
    ingest(db,packet(device,now+timedelta(seconds=6),6,lon=.5),now+timedelta(seconds=6))
    assert e.condition=="resolved" and e.attention=="concluded"

def test_duplicate_and_late_do_not_rejuvenate(data):
    db,_,_,_,animal,device,_,assignment,now=data
    p=packet(device,now,1);result=ingest(db,p,now)
    before=device.last_received_at
    assert ingest(db,p,now+timedelta(hours=1))["duplicate"]
    assert device.last_received_at==before
    late=ingest(db,packet(device,now-timedelta(hours=1),2),now+timedelta(hours=1))
    assert not late["state_updated"] and str(db.get(AnimalState,animal.id).telemetry_id)==result["id"]
    assert device.last_received_at==before
    assert db.scalar(select(func.count()).select_from(Telemetry).where(Telemetry.device_id==device.id))==2

def test_historical_association(data):
    db,_,farm,_,animal,device,_,assignment,now=data
    replacement=Animal(id=uuid4(),farm_id=farm.id,diio=f"QA-{uuid4()}",name="Replacement",orientation="meat",enabled=True);db.add(replacement);db.flush()
    assignment.valid_to=now-timedelta(hours=1);db.flush()
    new=Assignment(id=uuid4(),farm_id=farm.id,animal_id=replacement.id,device_id=device.id,valid_from=assignment.valid_to);db.add(new);db.flush()
    result=ingest(db,packet(device,now-timedelta(hours=2),1),now)
    assert result["animal_id"]==str(animal.id) and not result["state_updated"]
    result=ingest(db,packet(device,now,2),now)
    assert result["animal_id"]==str(replacement.id)

def test_independent_timeout_and_disabled_maintenance(data):
    db,_,_,_,animal,device,_,_,now=data
    ingest(db,packet(device,now,1),now)
    check_timeouts(db,now+timedelta(seconds=930))
    assert not db.scalar(select(Event).where(Event.device_id==device.id,Event.type=="communication_timeout"))
    check_timeouts(db,now+timedelta(seconds=931))
    assert db.scalar(select(Event).where(Event.device_id==device.id,Event.type=="communication_timeout")).condition=="active"
    device.enabled=False
    existing=db.scalar(select(func.count()).select_from(Event).where(Event.device_id==device.id))
    check_timeouts(db,now+timedelta(hours=12))
    assert db.scalar(select(func.count()).select_from(Event).where(Event.device_id==device.id))==existing

def test_authorization_csrf_version_and_config_evidence(data):
    db,client,farm,user,animal,device,fence,assignment,now=data
    assert client.get("/api/v1/dashboard").status_code==401
    login=client.post("/api/v1/auth/login",json={"username":user.username,"password":"test-only-strong-password"});csrf=login.json()["csrf_token"]
    assert client.post("/api/v1/sectors",json={"name":"unsafe"}).status_code==403
    foreign=Farm(id=uuid4(),name="Foreign",environment=settings().app_env);db.add(foreign);db.flush()
    alien=Animal(id=uuid4(),farm_id=foreign.id,diio=f"QA-{uuid4()}",name="Alien",orientation="meat",enabled=True);db.add(alien);db.flush()
    assert client.get(f"/api/v1/animals/{alien.id}").status_code==403
    user.role="viewer";db.flush()
    assert client.post("/api/v1/sectors",json={"name":"forbidden"},headers={"X-CSRF-Token":csrf}).status_code==403
    user.role="owner";db.flush()
    config=client.post(f"/api/v1/devices/{device.id}/config",json={"interval_seconds":600,"expected_version":0},headers={"X-CSRF-Token":csrf})
    assert config.status_code==201 and config.json()["status"]=="requested" and device.interval_seconds==300
    assert client.post(f"/api/v1/devices/{device.id}/config",json={"interval_seconds":900,"expected_version":0},headers={"X-CSRF-Token":csrf}).status_code==409
    at=utcnow();p=packet(device,at,1);p.config_version=1;ingest(db,p,at)
    assert device.interval_seconds==600 and device.config_version==1
    assert db.scalar(select(DeviceConfig).where(DeviceConfig.device_id==device.id)).status=="applied"

def test_config_sent_only_after_real_sender_acceptance(data):
    db,_,farm,_,animal,device,_,_,now=data
    from geocattle.downlink import dispatch_configs
    from types import SimpleNamespace
    device.transport="lorawan";device.dev_eui="aabbccddeeff0011"
    config=DeviceConfig(id=uuid4(),device_id=device.id,version=1,interval_seconds=600,status="requested")
    db.add(config);db.flush()
    cfg=SimpleNamespace(config_downlink_enabled=True)
    def broken(*args):raise RuntimeError("broker unavailable")
    dispatch_configs(db,sender=broken,cfg=cfg)
    assert config.status=="requested" and config.sent_at is None
    dispatch_configs(db,sender=lambda *args:{"topic":"test","mqtt_mid":1,"meaning":"test PUBACK"},cfg=cfg)
    assert config.status=="sent" and config.sent_at is not None
    assert device.interval_seconds==300 and device.config_version==0

def test_no_external_call_without_configured_channel(data,monkeypatch):
    db,_,_,_,_,device,_,_,now=data
    ingest(db,packet(device,now,1,lon=2),now)
    ingest(db,packet(device,now+timedelta(seconds=1),2,lon=2),now+timedelta(seconds=1))
    from geocattle.worker import process_outbox
    def forbidden(*args,**kwargs):raise AssertionError("No provider call permitted")
    monkeypatch.setattr("geocattle.worker.httpx.post",forbidden)
    event=db.scalar(select(Event).where(Event.device_id==device.id,Event.type=="escape"))
    process_outbox(db,event_id=event.id);db.flush()
    n=db.scalar(select(Notification).join(Event).where(Event.device_id==device.id))
    assert n.status=="disabled"
    attempts=db.scalars(select(NotificationAttempt).where(NotificationAttempt.notification_id==n.id)).all()
    assert len(attempts)==1 and attempts[0].status=="disabled"
    assert db.scalar(select(Event).where(Event.device_id==device.id,Event.type=="escape")).condition=="active"

def test_temporal_overlap_and_append_only_database_enforcement(data):
    db,_,farm,_,animal,device,_,assignment,now=data
    from sqlalchemy.exc import IntegrityError,DBAPIError
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(Assignment(id=uuid4(),farm_id=farm.id,animal_id=animal.id,device_id=device.id,valid_from=now))
            db.flush()
    result=ingest(db,packet(device,now,1),now)
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(text("UPDATE telemetry SET seq=99 WHERE id=:id"),{"id":result["id"]})
    assert db.scalar(select(Telemetry.seq).where(Telemetry.id==result["id"]))==1


def test_config_retry_after_failed_confirmation_uses_applied_version(data):
    db,client,_,user,_,device,_,_,_=data
    login=client.post("/api/v1/auth/login",json={"username":user.username,"password":"test-only-strong-password"})
    csrf={"X-CSRF-Token":login.json()["csrf_token"]}
    result=client.post(f"/api/v1/devices/{device.id}/config",headers=csrf,json={"interval_seconds":600,"expected_version":0})
    assert result.status_code==201 and result.json()["version"]==1
    previous=db.scalar(select(DeviceConfig).where(DeviceConfig.device_id==device.id))
    previous.status="failed";previous.error="Sin confirmación";db.commit()
    result=client.post(f"/api/v1/devices/{device.id}/config",headers=csrf,json={"interval_seconds":900,"expected_version":0})
    assert result.status_code==201 and result.json()["version"]==2
    assert device.config_version==0 and device.interval_seconds==300
