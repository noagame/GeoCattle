"""RF-36: multiple registered antennas preserve one immutable sensor reading."""
import json
import os
from datetime import timedelta
from uuid import UUID,uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select,text

from geocattle.domain import ingest
from geocattle.ingestor import decode
from geocattle.models import Farm,Telemetry
from geocattle.schemas import ReceptionIn,TelemetryIn
from test_integration import data,packet

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Requiere PostgreSQL/PostGIS V3 de prueba')


def gateway(db,farm,eui=None):
    ident=uuid4();eui=eui or uuid4().hex[:16]
    db.execute(text("INSERT INTO gateways(id,farm_id,gateway_eui,name,status) VALUES(:i,:f,:e,'QA antena','installed')"),{'i':ident,'f':farm.id,'e':eui})
    return ident,eui


def reception(eui,**values):
    return ReceptionIn(gateway_eui=eui,rssi_dbm=-88,snr_db=6.25,**values)


def stored(db,ident):
    return db.execute(text('SELECT * FROM telemetry_receptions WHERE telemetry_id=:i ORDER BY gateway_id'),{'i':UUID(ident)}).mappings().all()


def seen(db,ident):
    return db.execute(text('SELECT last_seen_at FROM gateways WHERE id=:i'),{'i':ident}).scalar_one()


def test_new_uplink_persists_two_antennas_and_uses_server_gateway_clock(data):
    db,_,farm,_,_,device,_,_,now=data
    first,eui1=gateway(db,farm);second,eui2=gateway(db,farm)
    payload=packet(device,now,201)
    antenna_clock=now+timedelta(days=1)
    payload.receptions=[reception(eui1.upper(),received_at=antenna_clock),reception(eui2)]
    result=ingest(db,payload,now)
    rows=stored(db,result['id'])
    assert len(rows)==2 and {r['gateway_id'] for r in rows}=={first,second}
    assert all(r['farm_id']==farm.id and r['rssi_dbm']==-88 and r['snr_db']==6.25 for r in rows)
    assert next(r for r in rows if r['gateway_id']==first)['received_at']==antenna_clock
    assert seen(db,first)==seen(db,second)==now
    assert device.last_received_at==now


def test_duplicate_can_add_antenna_without_rejuvenating_device_or_existing_pair(data):
    db,_,farm,_,_,device,_,_,now=data
    first,eui1=gateway(db,farm);second,eui2=gateway(db,farm)
    payload=packet(device,now,202);payload.receptions=[reception(eui1)]
    original=ingest(db,payload,now)
    previous_id=device.last_telemetry_id
    later=now+timedelta(hours=1)
    payload.receptions=[reception(eui1),reception(eui2),reception(eui2)]
    duplicate=ingest(db,payload,later)
    assert duplicate['duplicate'] is True and duplicate['id']==original['id']
    assert len(stored(db,original['id']))==2
    assert db.scalar(select(Telemetry.id).where(Telemetry.device_id==device.id))==UUID(original['id'])
    assert device.last_received_at==now and device.last_telemetry_id==previous_id
    assert seen(db,first)==now and seen(db,second)==later
    ingest(db,payload,later+timedelta(hours=1))
    assert seen(db,second)==later


def test_unknown_and_foreign_gateway_metadata_do_not_reject_or_leak(data):
    db,_,farm,_,_,device,_,_,now=data
    foreign=Farm(id=uuid4(),name='QA otro predio',environment=farm.environment)
    db.add(foreign);db.flush()
    own,eui=gateway(db,farm);other,foreign_eui=gateway(db,foreign)
    payload=packet(device,now,203)
    payload.receptions=[reception(eui),reception(foreign_eui),reception(uuid4().hex[:16])]
    result=ingest(db,payload,now)
    assert set(result)=={'id','duplicate','animal_id','state_updated'}
    assert [r['gateway_id'] for r in stored(db,result['id'])]==[own]
    assert seen(db,other) is None


def test_late_reading_preserves_device_freshness_and_gateway_clock_is_monotonic(data):
    db,_,farm,_,_,device,_,_,now=data
    ident,eui=gateway(db,farm)
    current=packet(device,now,204);current.receptions=[reception(eui)]
    ingest(db,current,now)
    late=packet(device,now-timedelta(hours=2),205);late.receptions=[reception(eui)]
    arrival=now+timedelta(hours=1)
    result=ingest(db,late,arrival)
    assert result['state_updated'] is False and device.last_received_at==now
    assert seen(db,ident)==arrival and len(stored(db,result['id']))==1
    queued=packet(device,now-timedelta(hours=3),206);queued.receptions=[reception(eui)]
    ingest(db,queued,now-timedelta(minutes=1))
    assert seen(db,ident)==arrival and device.last_received_at==now


def test_reception_schema_rejects_malformed_numbers_euis_naive_time_and_excess(data):
    valid={'gateway_eui':'ABCDEF0123456789','rssi_dbm':-80,'snr_db':1.5}
    assert ReceptionIn(**valid).gateway_eui=='abcdef0123456789'
    invalid=[{'gateway_eui':'abcd'},{'rssi_dbm':float('nan')},{'rssi_dbm':float('inf')},
             {'rssi_dbm':-201},{'rssi_dbm':21},{'rssi_dbm':True},{'rssi_dbm':'-80'},
             {'snr_db':-101},{'snr_db':101},{'snr_db':float('-inf')},{'received_at':'2026-10-21T12:00:00'}]
    for change in invalid:
        with pytest.raises(ValidationError):ReceptionIn(**(valid|change))
    with pytest.raises(ValidationError):
        TelemetryIn(hardware_id='QA',session_id='QA',seq=1,observed_at='2026-10-21T12:00:00Z',gnss_valid=False,source='sim',receptions=[valid]*11)


def test_chirpstack_transforms_valid_rx_info_and_preserves_malformed_metadata(data):
    db,_,_,_,_,device,_,_,now=data
    device.dev_eui=uuid4().hex[:16];db.flush()
    rx_info=[{'gatewayId':'ABCDEF0123456789','rssi':-77,'snr':8.5,'time':now.isoformat()},
             {'gatewayId':'0000000000000001','rssi':-90,'snr':3},
             {'gatewayId':'bad','rssi':-80,'snr':3},
             {'gatewayId':'0000000000000002','rssi':-80,'snr':'invalid'},
             {'gatewayId':'0000000000000003','rssi':-80,'snr':3,'time':'2026-10-21T12:00:00'},
             'invalid entry']
    decoded=packet(device,now,207).model_dump(mode='json',exclude={'hardware_id','receptions'})
    decoded['receptions']=[{'untrusted':'ignored in favor of authenticated envelope'}]
    envelope={'object':decoded,'deviceInfo':{'devEui':device.dev_eui},'rxInfo':rx_info}
    payload=decode(db,'application/qa/device/qa/event/up',json.dumps(envelope).encode())
    assert payload.hardware_id==device.hardware_id and payload.source=='lorawan'
    assert len(payload.receptions)==2
    assert payload.receptions[0].gateway_eui=='abcdef0123456789'
    assert payload.receptions[0].received_at==now
    assert payload.receptions[1].received_at is None
    assert payload.quality['rx_info']==rx_info and payload.quality['transport']=='chirpstack'
    assert payload.surface_temperature_c is None and payload.activity_index is None
    envelope['rxInfo']={'invalid':'container'}
    malformed=decode(db,'application/qa/device/qa/event/up',json.dumps(envelope).encode())
    assert malformed.receptions==[] and malformed.quality['rx_info']==envelope['rxInfo']
