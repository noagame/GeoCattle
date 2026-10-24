"""PostgreSQL integration checks. All fixture changes are rolled back."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

@unittest.skipUnless(os.environ.get('GEOCATTLE_TEST_DATABASE') == '1', 'Requires explicit local PostgreSQL test environment')
class HardwareTests(unittest.TestCase):
    def setUp(self):
        from geocattle.db import SessionLocal
        from geocattle.models import Farm, Device, Telemetry, User
        from sqlalchemy import select, func
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        existing = self.db.scalar(select(User).where(User.username == 'prototipo@geocattle.local'))
        self.user = SimpleNamespace(farm_id=existing.farm_id, role='owner')
        self.now = datetime.now(timezone.utc)
        token = uuid4().hex[:12]
        other = Farm(name='QA transaction only', environment='development', timezone='America/Santiago')
        self.db.add(other); self.db.flush()
        self.other_user = SimpleNamespace(farm_id=other.id, role='owner')
        self.devices = []
        for index, farm in enumerate((existing.farm_id, existing.farm_id, other.id)):
            d = Device(farm_id=farm, hardware_id=f'QA{token}{index}', name='Rolled back fixture', transport='academic', interval_seconds=30)
            self.db.add(d); self.db.flush(); self.devices.append(d)
        self.rows = []
        for seq, seconds, fix in ((1, 600, True), (2, 10, False)):
            t = Telemetry(farm_id=existing.farm_id, device_id=self.devices[0].id, session_id=token, seq=seq,
                observed_at=self.now-timedelta(seconds=seconds), received_at=self.now,
                point=func.ST_SetSRID(func.ST_MakePoint(-70.6,-33.4),4326) if fix else None,
                gnss_valid=fix, latitude=-33.4 if fix else None, longitude=-70.6 if fix else None,
                surface_temperature_c=17+seq, activity_index=.1*seq, battery_mv=3900, source='academic',
                quality={'movement_state':'rest' if seq==1 else 'moving','period_ms':35000})
            self.db.add(t);self.db.flush();self.rows.append(t)

    def test_latest_and_last_valid_position_are_independent_and_farm_scoped(self):
        from geocattle.hardware_api import overview
        data = overview(self.user, self.db)
        items = {d['hardware_id']:d for d in data['items']}
        self.assertNotIn(self.devices[2].hardware_id, items)
        active = items[self.devices[0].hardware_id]
        self.assertEqual(active['latest']['seq'], 2)
        self.assertEqual(active['latest']['activity_index'], .2)
        self.assertFalse(active['latest']['gnss_valid'])
        self.assertEqual(active['last_position']['seq'], 1)
        self.assertGreater(active['position_age_seconds'], active['freshness_seconds'])
        self.assertEqual(active['communication_status'], 'recent')
        empty = items[self.devices[1].hardware_id]
        self.assertIsNone(empty['latest']);self.assertIsNone(empty['last_position'])
        self.assertEqual(empty['communication_status'], 'unknown')

    def test_page_filter_and_activity_preserve_nulls(self):
        from geocattle.hardware_api import telemetry
        from zoneinfo import ZoneInfo
        day = self.now.astimezone(ZoneInfo('America/Santiago')).date()
        data = telemetry(day, self.devices[0].hardware_id, 1, 0, self.user, self.db)
        self.assertEqual(data['total'], 2)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['activity_index'], .2)
        self.assertIsNone(data['items'][0]['latitude'])
        denied = telemetry(day, self.devices[0].hardware_id, 100, 0, self.other_user, self.db)
        self.assertEqual(denied['total'], 0)

    def test_daily_counts_are_samples_and_filtered(self):
        from geocattle.hardware_api import daily
        data = daily(self.devices[0].hardware_id, 30, self.user, self.db)['items']
        self.assertEqual(sum(d['samples'] for d in data), 2)
        self.assertEqual(sum(d['positions'] for d in data), 1)
        self.assertEqual(sum(d['moving_samples'] for d in data), 1)
        self.assertEqual(sum(d['rest_samples'] for d in data), 1)
        self.assertEqual(max(d['temperature_max'] for d in data), 19)
        self.assertEqual(daily(self.devices[0].hardware_id,30,self.other_user,self.db)['items'], [])

    def test_receiver_stale_and_bom_file(self):
        from geocattle.hardware_api import receiver
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'status.json'
            with patch.dict(os.environ, USB_STATUS_PATH=str(path)):
                path.write_text(json.dumps({'connected':True,'updated_at':(self.now-timedelta(minutes=1)).isoformat()}), encoding='utf-8-sig')
                data=receiver(self.user)
                self.assertFalse(data['available']);self.assertFalse(data['connected'])
                path.write_text(json.dumps({'connected':True,'updated_at':datetime.now(timezone.utc).isoformat()}),encoding='utf-8')
                self.assertTrue(receiver(self.user)['connected'])

if __name__ == '__main__': unittest.main()
