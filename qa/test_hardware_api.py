"""PostgreSQL integration checks. All fixture changes are rolled back."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

@unittest.skipUnless(os.environ.get('GEOCATTLE_TEST_DATABASE') == '1' and bool(os.environ.get('TEST_DATABASE_URL')),
    'Requires GEOCATTLE_TEST_DATABASE=1 and an explicit migrated TEST_DATABASE_URL')
class HardwareTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine, func
        from sqlalchemy.engine import make_url
        from sqlalchemy.orm import Session
        from zoneinfo import ZoneInfo
        from geocattle.models import Farm, Device, Telemetry, User, OwnerAccount, FarmMembership
        from geocattle.settings import settings

        url = make_url(os.environ['TEST_DATABASE_URL'])
        if url.get_backend_name() != 'postgresql':
            raise RuntimeError('Hardware QA requires a dedicated PostgreSQL/PostGIS test database')
        engine = create_engine(url)
        self.addCleanup(engine.dispose)
        connection = engine.connect()
        self.addCleanup(connection.close)
        outer = connection.begin()
        self.addCleanup(lambda: outer.rollback() if outer.is_active else None)
        self.db = Session(connection, join_transaction_mode='create_savepoint', expire_on_commit=False)
        self.addCleanup(self.db.close)

        # Freeze the API clock at local noon: pagination still sees both fixture
        # readings when CI happens to run in the first ten minutes of a day.
        self.now = datetime.now(ZoneInfo('America/Santiago')).replace(hour=12, minute=0,
            second=0, microsecond=0).astimezone(timezone.utc)
        fixed_now = self.now
        class FixtureDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now.astimezone(tz) if tz is not None else fixed_now.replace(tzinfo=None)
        clock = patch('geocattle.hardware_api.datetime', FixtureDateTime)
        clock.start()
        self.addCleanup(clock.stop)

        token = uuid4().hex[:12]
        owners, farms = [], []
        for index in range(2):
            email = f'hardware-{token}-{index}@qa.invalid'
            owner = User(username=email, email=email, full_name='QA hardware fixture',
                password_hash='qa-fixture-unused-for-authentication', role='owner', active=True)
            self.db.add(owner); self.db.flush()
            account = OwnerAccount(owner_user_id=owner.id, display_name='QA hardware account', max_farms=1)
            self.db.add(account); self.db.flush()
            farm = Farm(name='QA hardware transaction only', account_id=account.id,
                environment=settings().app_env, timezone='America/Santiago')
            self.db.add(farm); self.db.flush()
            owner.farm_id = farm.id
            self.db.add(FarmMembership(farm_id=farm.id, user_id=owner.id, role_code='owner',
                granted_by=owner.id, valid_from=self.now-timedelta(days=1)))
            owners.append(owner); farms.append(farm)
        self.db.flush()
        self.user, self.other_user = owners
        self.devices = []
        for index, farm in enumerate((farms[0].id, farms[0].id, farms[1].id)):
            device = Device(farm_id=farm, hardware_id=f'QA{token}{index}', name='Rolled back fixture',
                transport='academic', interval_seconds=30)
            self.db.add(device); self.db.flush(); self.devices.append(device)
        self.rows = []
        for seq, seconds, fix in ((1, 600, True), (2, 10, False)):
            row = Telemetry(farm_id=farms[0].id, device_id=self.devices[0].id, session_id=token, seq=seq,
                observed_at=self.now-timedelta(seconds=seconds), received_at=self.now,
                point=func.ST_SetSRID(func.ST_MakePoint(-70.6,-33.4),4326) if fix else None,
                gnss_valid=fix, latitude=-33.4 if fix else None, longitude=-70.6 if fix else None,
                surface_temperature_c=17+seq, activity_index=.1*seq, battery_mv=3900, source='academic',
                quality={'movement_state':'rest' if seq==1 else 'moving','period_ms':35000,'test_fixture':True})
            self.db.add(row); self.db.flush(); self.rows.append(row)

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
                path.write_text(json.dumps({'connected':True,'updated_at':self.now.isoformat()}),encoding='utf-8')
                self.assertTrue(receiver(self.user)['connected'])

if __name__ == '__main__': unittest.main()
