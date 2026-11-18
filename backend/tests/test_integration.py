"""PostGIS integration: run with TEST_DATABASE_URL pointing to a migrated test DB.
Each test uses an external rollback transaction; no persisted production writes.
"""
import os
from datetime import timedelta
from uuid import uuid4, UUID as PythonUUID
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event as sql_event,func,select,text
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

def test_one_collar_moves_between_two_active_geofences(data):
    db,client,farm,user,animal,device,first,assignment,now=data
    second=Geofence(id=uuid4(),farm_id=farm.id,sector_id=first.sector_id,name="Segundo potrero QA",version=1,
        geometry=func.ST_GeomFromText("POLYGON((2 0,3 0,3 1,2 1,2 0))",4326),active=True,created_at=now-timedelta(days=1))
    holding=AnimalHolding(farm_id=farm.id,animal_id=animal.id,valid_from=now-timedelta(days=1),reason="QA de pastoreo")
    db.add_all([second,holding]);db.flush()
    previous=db.scalar(select(PastureAssignment).where(PastureAssignment.animal_id==animal.id))
    beginning=now-timedelta(seconds=20)
    for seq in (1,2):
        observed=beginning+timedelta(seconds=seq)
        ingest(db,packet(device,observed,seq,lon=2.5),observed)
    old_event=db.scalar(select(Event).where(Event.device_id==device.id,Event.type=="escape"))
    assert old_event and old_event.geofence_id==first.id and old_event.condition=="active"
    old_evidence=old_event.telemetry_id
    low_battery=Event(farm_id=farm.id,animal_id=animal.id,device_id=device.id,type="low_battery",severity="warning",detail={})
    db.add(low_battery);db.flush()

    login=client.post("/api/v1/auth/login",json={"username":user.username,"password":"test-only-strong-password"})
    assert login.status_code==200,login.text
    client.headers["X-CSRF-Token"]=login.json()["csrf_token"]
    body={"animal_id":str(animal.id),"geofence_id":str(second.id),"expected_pasture_id":str(previous.id),"expected_device_id":str(device.id)}
    transfer=client.post("/api/v1/pasture-assignments",json=body)
    assert transfer.status_code==201,transfer.text
    new_id=PythonUUID(transfer.json()["id"])
    at=db.get(PastureAssignment,new_id).valid_from
    assert previous.valid_to==at and assignment.valid_to is None
    assert old_event.condition=="resolved" and old_event.telemetry_id==old_evidence
    assert old_event.detail["resolution_reason"]=="pasture_changed" and old_event.attention=="pending"
    assert low_battery.condition=="active"
    state=db.get(AnimalState,animal.id)
    assert state.geofence_status=="unknown" and state.outside_count==0

    retry=client.post("/api/v1/pasture-assignments",json=body)
    assert retry.status_code==201 and retry.json()["id"]==str(new_id)
    stale=client.post("/api/v1/pasture-assignments",json={**body,"geofence_id":str(first.id)})
    assert stale.status_code==409,stale.text
    changed_collar=client.post("/api/v1/pasture-assignments",json={**body,"expected_device_id":str(uuid4())})
    assert changed_collar.status_code==409,changed_collar.text

    late=at-timedelta(milliseconds=1)
    ingest(db,packet(device,late,3,lon=2.5),at+timedelta(seconds=1))
    assert state.geofence_status=="unknown" and state.outside_count==0
    for seq,seconds in ((4,2),(5,3),(6,4)):
        observed=at+timedelta(seconds=seconds)
        ingest(db,packet(device,observed,seq,lon=2.5 if seq==4 else .5),observed)
        assert state.geofence_status=={4:"inside",5:"pending",6:"outside"}[seq]
    events=db.scalars(select(Event).where(Event.device_id==device.id,Event.type=="escape",Event.condition=="active")).all()
    assert len(events)==1 and events[0].geofence_id==second.id and events[0].id!=old_event.id
    assert db.get(Telemetry,old_evidence).assignment_id==assignment.id

    detail=client.get(f"/api/v1/animals/{animal.id}").json()
    assert detail["pasture_assignment"]["geofence_id"]==str(second.id)
    history=client.get(f"/api/v1/animals/{animal.id}/assignments").json()["items"]
    assert sum(row["active"] for row in history if row["kind"]=="pasture")==1
    assert len([row for row in history if row["kind"]=="pasture"])==2


def test_two_animals_per_geofence_keep_independent_escape_alerts(data):
    db,client,farm,user,first_animal,first_device,first_fence,first_assignment,now=data
    since=now-timedelta(days=1)
    second_fence=Geofence(farm_id=farm.id,sector_id=first_fence.sector_id,name="Segundo potrero QA",version=1,
        geometry=func.ST_GeomFromText("POLYGON((2 0,3 0,3 1,2 1,2 0))",4326),active=True,created_at=since)
    db.add_all([second_fence,AnimalHolding(farm_id=farm.id,animal_id=first_animal.id,valid_from=since,reason="QA")]);db.flush()
    monitored=[(first_animal,first_device,first_fence,2.5)]
    for fence,longitude in ((first_fence,.5),(second_fence,.5),(second_fence,2.5)):
        animal=Animal(farm_id=farm.id,diio=f"QA-{uuid4()}",name="Bovino QA",orientation="meat",enabled=True,sector_id=fence.sector_id)
        device=Device(farm_id=farm.id,hardware_id=f"qa-{uuid4()}",name="Collar QA",transport="academic",interval_seconds=300,enabled=True,installed_at=since)
        db.add_all([animal,device]);db.flush()
        db.add_all([Assignment(farm_id=farm.id,animal_id=animal.id,device_id=device.id,valid_from=since),
                    PastureAssignment(farm_id=farm.id,animal_id=animal.id,geofence_id=fence.id,valid_from=since)])
        monitored.append((animal,device,fence,longitude))
    db.flush()

    login=client.post("/api/v1/auth/login",json={"username":user.username,"password":"test-only-strong-password"})
    assert login.status_code==200,login.text
    client.headers["X-CSRF-Token"]=login.json()["csrf_token"]

    def alert_list():
        response=client.get("/api/v1/events?condition=active")
        assert response.status_code==200,response.text
        return {event["animal_id"]:event for event in response.json()["items"] if event["type"]=="escape"}

    for seq in (1,2):
        observed=now-timedelta(seconds=20-seq)
        for animal,device,_,longitude in monitored:
            result=ingest(db,packet(device,observed,seq,lon=longitude),observed)
            assert not result["duplicate"] and result["animal_id"]==str(animal.id)
        if seq==1:
            assert not alert_list()
            assert [db.get(AnimalState,a.id).outside_count for a,_,_,_ in monitored]==[1,0,1,0]

    alerts=alert_list()
    other_animal,other_device,_,_=monitored[2]
    assert set(alerts)=={str(first_animal.id),str(other_animal.id)}
    for animal,device,fence,_ in (monitored[0],monitored[2]):
        event=alerts[str(animal.id)]
        assert (event["device_id"],event["geofence_id"],event["telemetry"]["seq"])==(str(device.id),str(fence.id),2)
    first_alert_id=alerts[str(first_animal.id)]["id"]
    other_alert_id=alerts[str(other_animal.id)]["id"]

    current=db.scalar(select(PastureAssignment).where(PastureAssignment.animal_id==first_animal.id))
    transfer=client.post("/api/v1/pasture-assignments",json={"animal_id":str(first_animal.id),
        "geofence_id":str(second_fence.id),"expected_pasture_id":str(current.id),"expected_device_id":str(first_device.id)})
    assert transfer.status_code==201,transfer.text
    assert db.get(Assignment,first_assignment.id).valid_to is None
    assert db.get(Event,PythonUUID(first_alert_id)).condition=="resolved"
    assert {a:e["id"] for a,e in alert_list().items()}=={str(other_animal.id):other_alert_id}
    assert [db.get(AnimalState,a.id).geofence_status for a,_,_,_ in monitored]==["unknown","inside","outside","inside"]

    observed=utcnow()+timedelta(seconds=1)
    ingest(db,packet(first_device,observed,3,lon=2.5),observed)
    assert db.get(AnimalState,first_animal.id).geofence_status=="inside"
    assert str(other_animal.id) in alert_list()
    ingest(db,packet(other_device,observed,3,lon=2.5),observed)
    assert not alert_list()


def test_sensor_rule_configuration_drives_alert_lifecycle(data,monkeypatch):
    db,client,farm,user,animal,device,_,_,now=data
    monkeypatch.setattr(settings(),"preventive_rules_validated",True)
    device.interval_seconds=30;db.flush()
    login=client.post("/api/v1/auth/login",json={"username":user.username,"password":"test-only-strong-password"})
    assert login.status_code==200,login.text
    client.headers["X-CSRF-Token"]=login.json()["csrf_token"]
    current=client.get("/api/v1/settings").json()
    settings_body={"expected_version":current["version"],"battery_low_mv":3300,"temperature_high_c":40,
        "activity_low_threshold":.05,"activity_window_minutes":2,"proximity_meters":25,
        "temperature_enabled":True,"activity_enabled":True,"proximity_enabled":False}
    saved=client.put("/api/v1/settings",json=settings_body)
    assert saved.status_code==200,saved.text
    version=saved.json()["version"]

    def reading(seq, seconds, temperature, activity):
        observed=now+timedelta(seconds=seconds)
        payload=packet(device,observed,seq).model_copy(update={"surface_temperature_c":temperature,"activity_index":activity})
        return PythonUUID(ingest(db,payload,observed)["id"])

    def active(kind):
        return db.scalar(select(Event).where(Event.device_id==device.id,Event.type==kind,Event.condition=="active"))

    high_id=reading(1,0,40,.01)
    first_temperature=active("high_surface_temperature")
    assert first_temperature and first_temperature.telemetry_id==high_id
    assert first_temperature.detail["rule_version"]==version
    assert active("low_activity") is None
    reading(2,105,None,.01)
    assert first_temperature.condition=="active" and active("low_activity") is None  # gap above tolerance
    reading(3,135,39,None)
    assert first_temperature.condition=="resolved"
    for seq,seconds in ((4,165),(5,195),(6,225),(7,255)):
        reading(seq,seconds,None,.01)
        assert active("low_activity") is None  # missing reading still in window

    evidence=reading(8,285,40,.01)
    low=active("low_activity")
    assert low and low.telemetry_id==evidence
    assert low.detail["threshold_activity"]==.05 and low.detail["window_minutes"]==2
    second_temperature=active("high_surface_temperature")
    assert second_temperature and second_temperature.id!=first_temperature.id
    reading(9,315,None,.30)
    assert low.condition=="resolved" and second_temperature.condition=="active"

    disabled=client.put("/api/v1/settings",json={**settings_body,"expected_version":version,"temperature_enabled":False,"temperature_high_c":41})
    assert disabled.status_code==200,disabled.text
    assert second_temperature.condition=="resolved" and second_temperature.detail["resolution_reason"]=="rule_disabled"
    assert second_temperature.telemetry_id==evidence and second_temperature.attention=="pending"
    assert disabled.json()["temperature_high_c"]==41 and disabled.json()["activity_enabled"] is True
    reading(10,345,45,.30)
    assert active("high_surface_temperature") is None


def test_dashboard_loads_animals_and_events_without_per_row_queries(data):
    db,client,farm,user,_,_,_,_,now=data
    login=client.post("/api/v1/auth/login",json={"username":user.username,"password":"test-only-strong-password"})
    assert login.status_code==200,login.text

    def dashboard():
        connection=db.connection()
        selects=[]

        def count(conn,cursor,sql,parameters,context,executemany):
            if sql.lstrip().upper().startswith("SELECT"):
                selects.append(sql)

        sql_event.listen(connection,"before_cursor_execute",count)
        try:
            response=client.get("/api/v1/dashboard")
            assert response.status_code==200,response.text
            return response.json(),len(selects)
        finally:
            sql_event.remove(connection,"before_cursor_execute",count)

    initial,initial_queries=dashboard()
    assert initial["summary"]["total"]==1
    assert initial_queries>0
    for number in range(8):
        animal=Animal(farm_id=farm.id,diio=f"QA-{uuid4()}",name=f"Animal {number}",orientation="meat",enabled=True)
        device=Device(farm_id=farm.id,hardware_id=f"qa-{uuid4()}",name=f"Collar {number}",transport="academic",
                      interval_seconds=300,enabled=True,installed_at=now)
        db.add_all([animal,device]);db.flush()
        db.add(Assignment(farm_id=farm.id,animal_id=animal.id,device_id=device.id,valid_from=now))
        db.add(Event(farm_id=farm.id,animal_id=animal.id,device_id=device.id,type="escape",severity="critical",detail={}))
    db.commit()
    result,queries=dashboard()
    assert result["summary"]["total"]==9 and result["summary"]["critical"]==8
    assert result["summary"]["active_events"]==8 and len(result["events"])==8
    assert all(row["animal_name"].startswith("Animal ") and row["device_name"].startswith("Collar ") for row in result["events"])
    assert queries<=initial_queries+3


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

def test_pending_config_expires_when_collar_has_no_assignment(data):
    db, _, farm, _, _, _, _, _, now = data
    collar = Device(farm_id=farm.id, hardware_id=f'qa-unassigned-{uuid4()}',
                    name='QA sin asignación', interval_seconds=300, transport='academic', enabled=True)
    db.add(collar)
    db.flush()
    requested_at = now - timedelta(seconds=settings().config_timeout_seconds + 1)
    config = DeviceConfig(device_id=collar.id, version=1, interval_seconds=45,
                          status='requested', requested_at=requested_at)
    db.add(config)
    db.flush()

    check_timeouts(db, now)

    assert config.status == 'failed'
    assert collar.interval_seconds == 300
    event = db.scalar(select(Event).where(Event.device_id == collar.id))
    assert event.type == 'config_timeout'
    assert event.animal_id is None


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
