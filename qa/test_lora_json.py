import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adapters.lora_usb import Archive, decode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from geocattle.schemas import TelemetryIn

NOW=datetime(2026,10,23,15,0,tzinfo=timezone.utc)
SAMPLE={'v':5,'id':'REAL01','s':'0123456789ABCDEF','q':1,'u':35000,
        'g':[-33.45,-70.66,500,8,1.2],'t':18.25,'a':[0.1,-0.2,0.95],
        'm':[1,0.086],'b':[3935,73,1,0,0],'p':35000,'f':0,'e':2,'d':[6200,40,0]}
def wire(p): return json.dumps(p,separators=(',',':'),allow_nan=False)

class JsonProtocolTests(unittest.TestCase):
    def test_valid_fix_motion_battery_and_api_contract(self):
        payload,_=decode(wire(SAMPLE),NOW)
        checked=TelemetryIn.model_validate(payload)
        self.assertTrue(checked.gnss_valid)
        self.assertEqual(checked.latitude,-33.45)
        self.assertEqual(checked.quality['movement_state'],'moving')
        self.assertEqual(checked.activity_index,0.086)
        self.assertEqual(checked.quality['gps_satellites'],8)
        self.assertEqual(checked.quality['gps_diagnostics']['valid_sentences'],40)
        self.assertEqual(checked.quality['tx_reason'],'movement_start')
        self.assertFalse(checked.quality['usb_present'])

    def test_supported_periods_preserve_value_in_raw_and_receiver_frames(self):
        for period in (30000, 35000, 40000, 45000):
            packet = {**SAMPLE, 'p': period}
            envelope = {'packet': packet, 'radio': {'rssi_dbm': -40, 'snr_db': 9.5}}
            for message in (packet, envelope):
                with self.subTest(period=period, wrapped='packet' in message):
                    payload, original = decode(wire(message), NOW)
                    checked = TelemetryIn.model_validate(payload)
                    self.assertEqual(checked.quality['period_ms'], period)
                    self.assertEqual(json.loads(original)['p'], period)

    def test_no_fix_and_usb_only(self):
        p=copy.deepcopy(SAMPLE);p.update(g=[None,None,-1,0,99.99],b=[-1,-1,0,0,1],f=1,m=[0,0.004])
        result,_=decode('Contenido: '+wire(p),NOW)
        self.assertIsNone(result['latitude']);self.assertIsNone(result['battery_mv'])
        self.assertEqual(result['quality']['movement_state'],'rest')
        self.assertTrue(result['quality']['usb_present'])
        TelemetryIn.model_validate(result)

    def test_missing_sensors_unknown_motion(self):
        p=copy.deepcopy(SAMPLE);p.update(g=[None,None,-1,-1,None],t=None,a=[None]*3,m=[-1,None],b=[-1]*5,f=7)
        result,_=decode(wire(p),NOW)
        self.assertEqual(result['quality']['movement_state'],'unknown')
        self.assertIsNone(result['activity_index'])
        TelemetryIn.model_validate(result)

    def test_receiver_envelope_and_duplicate_radio_keeps_identity(self):
        p1,w1=decode(wire(SAMPLE),NOW)
        envelope={'packet':SAMPLE,'radio':{'rssi_dbm':-40,'snr_db':9.5}}
        p2,w2=decode(wire(envelope),NOW)
        self.assertEqual(w1,w2)
        self.assertEqual(p2['quality']['radio']['snr_db'],9.5)
        with tempfile.TemporaryDirectory() as folder:
            archive=Archive(folder)
            self.assertTrue(archive.enqueue(p1,w1));self.assertFalse(archive.enqueue(p2,w2))

    def test_reject_wrong_types_nonfinite_stale_fix_inconsistent_flags_and_battery(self):
        mutations=[('q',True),('q',-1),('p',29000),('p',45001),('p',True),('p',45000.0),('p','45000'),('p',None),('v',True),('id','BAD,ID'),
                   ('s','bad'),('g',[-33.,None,0,8,1.]),('g',[-33.,-70.,5000,8,1.]),
                   ('g',[-91.,-70.,0,8,1.]),('a',[float('inf'),0,1]),
                   ('m',[1,None]),('b',[-1,-1,0,1,1]),('b',[4000,101,1,0,0]),
                   ('f',1),('e',3),('o','sim')]
        for key,value in mutations:
            with self.subTest(key=key,value=value):
                p=copy.deepcopy(SAMPLE);p[key]=value
                text=json.dumps(p,separators=(',',':'))
                with self.assertRaises(ValueError):decode(text,NOW)
        with self.assertRaises(ValueError):decode(wire(SAMPLE).replace('"v":5','"v":5,"v":5'),NOW)

    def test_reject_bad_envelope_and_radio(self):
        for radio in ({'rssi_dbm':None,'snr_db':2},{'rssi_dbm':True,'snr_db':2},
                      {'rssi_dbm':-40,'snr_db':300},[],None):
            message={'packet':SAMPLE,'radio':radio}
            with self.subTest(radio=radio):
                with self.assertRaises(ValueError):decode(wire(message),NOW)

    def test_optional_diagnostics_and_maximal_values(self):
        p=copy.deepcopy(SAMPLE);p.update(q=4294967295,u=4294967295,
            g=[-89.123456,-179.123456,4999,32,99.99],t=100.0,a=[-15.999]*3,
            m=[1,32.0],b=[4350,100,1,1,1],p=40000,f=0,d=[4294967295]*3)
        self.assertLessEqual(len(wire(p).encode()),255)
        TelemetryIn.model_validate(decode(wire(p),NOW)[0])
        p.pop('d');TelemetryIn.model_validate(decode(wire(p),NOW)[0])

    def test_unknown_json_version_rejected(self):
        with self.assertRaises(ValueError):decode('{"v":6}',NOW)

if __name__=='__main__':unittest.main()
