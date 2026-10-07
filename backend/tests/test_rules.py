from datetime import datetime,timezone,timedelta
import pytest
from geocattle.domain import freshness,rule_position
from geocattle.schemas import TelemetryIn,GeofenceIn
from geocattle.settings import Settings
from geocattle.security import hash_password,verify_password
from geocattle.ingestor import Spool

def test_two_outside_invalid_breaks_and_does_not_resolve():
    count,status,event=rule_position(0,True,False)
    assert (count,status,event)==(1,"pending",None)
    assert rule_position(count,True,False)==(2,"outside",True)
    assert rule_position(2,False,None)==(0,"unknown",None)
    assert rule_position(0,True,False)==(1,"pending",None)
    assert rule_position(2,True,True)==(0,"inside",False)

def test_independent_freshness_exact_thresholds():
    now=datetime.now(timezone.utc)
    assert freshness(now-timedelta(seconds=630),now-timedelta(seconds=930),300,now)==("fresh","recent")
    assert freshness(now-timedelta(seconds=631),now-timedelta(seconds=931),300,now)==("stale","absent")
    assert freshness(None,now,300,now)==("unknown","recent")

def test_no_fix_null_not_zero_and_observation_requires_timezone():
    common=dict(hardware_id="abc",session_id="s",seq=0,source="academic",gnss_valid=False)
    assert TelemetryIn(**common,observed_at=datetime.now(timezone.utc)).longitude is None
    with pytest.raises(ValueError):TelemetryIn(**common,observed_at=datetime.now(timezone.utc),longitude=0,latitude=0)
    with pytest.raises(ValueError):TelemetryIn(**common,observed_at=datetime.now())

def test_strong_hash_is_salted_and_verifiable():
    a=hash_password("long-test-password");b=hash_password("long-test-password")
    assert a!=b and a.startswith("$argon2id$")
    assert verify_password(a,"long-test-password")
    assert not verify_password(a,"incorrect")

def test_simulation_cannot_run_in_production_or_sqlite():
    with pytest.raises(ValueError):Settings(app_env="production",simulation_enabled=True)
    with pytest.raises(ValueError):Settings(database_url="sqlite:///:memory:")
    with pytest.raises(ValueError):Settings(app_env="production",cookie_secure=False)

def test_durable_spool_survives_restart_and_deduplicates(tmp_path):
    path=str(tmp_path/"queue.db");spool=Spool(path)
    key=spool.put("academic",b'{"seq":1}',1,1,1)
    spool.put("academic",b'{"seq":1}',2,1,2)
    reopened=Spool(path);rows=reopened.pending()
    assert len(rows)==1 and rows[0][3:6]==(2,1,2)
    reopened.reject(key,"invalid-contract")
    assert not reopened.pending()
    reopened.put("academic",b'{"seq":1}',3,1,3)
    assert reopened.is_rejected(key) and not reopened.pending()

def test_downlink_requires_validated_codec_and_non_simulation():
    with pytest.raises(ValueError):Settings(config_downlink_enabled=True)
    with pytest.raises(ValueError):Settings(app_env="simulation",simulation_enabled=True,config_downlink_enabled=True,config_codec_validated=True,chirpstack_application_id="app")
    cfg=Settings(app_env="development",simulation_enabled=False,config_downlink_enabled=True,config_codec_validated=True,chirpstack_application_id="app")
    from types import SimpleNamespace
    from geocattle.downlink import envelope
    topic,payload=envelope(cfg,SimpleNamespace(dev_eui="aabbccddeeff0011"),SimpleNamespace(version=2,interval_seconds=600))
    assert topic=="application/app/device/aabbccddeeff0011/command/down"
    assert payload=={"devEui":"aabbccddeeff0011","confirmed":False,"fPort":10,"object":{"schema_version":1,"config_version":2,"interval_seconds":600}}
