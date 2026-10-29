"""Run with GEOCATTLE_REPO pointing to the unchanged GeoCattle checkout."""
import copy
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'backend'))
from adapters.lora_usb import Archive, decode
from adapters import lora_usb as staged
from adapters import lora_bus
from adapters.lora_bus import decode_many
from geocattle.schemas import TelemetryIn

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
SAMPLE = {'v': 5, 'id': 'REAL01', 's': '0123456789ABCDEF', 'q': 1,
          'u': 45000, 'g': [-33.45, -70.66, 500, 8, 1.2], 't': 18.25,
          'a': [0.1, -0.2, 0.95], 'm': [1, 0.086],
          'b': [3935, 73, 1, 0, 0], 'p': 45000, 'f': 0, 'e': 2,
          'd': [6200, 40, 0]}


def reading(packet=None, **transport):
    return {'packet': copy.deepcopy(packet or SAMPLE),
            'radio': {'rssi_dbm': -53, 'snr_db': 7.5},
            'transport': {'delay_ms': 3200, 'origin_gateway': 1,
                          'hops': 1, 'path': 2, **transport}}


def bus(*records, **overrides):
    return {'gc_bus': 1, 'receiver': 'BASE01', 'batch': 'A1B2C3D4-9',
            'readings': list(records or [reading()]), **overrides}


def wire(value):
    return json.dumps(value, allow_nan=False, separators=(',', ':'))


class BusProtocolTests(unittest.TestCase):
    def test_reading_preserves_api_contract_and_marks_estimated_delay(self):
        result = decode_many(wire(bus()), NOW, receiver='PC-COM6')
        self.assertTrue(result.is_bus)
        self.assertEqual(result.errors, ())
        payload, original = result.readings[0]
        checked = TelemetryIn.model_validate(payload)
        self.assertEqual(checked.observed_at, NOW - timedelta(milliseconds=3200))
        self.assertEqual(checked.quality['capture_received_at'], NOW.isoformat())
        self.assertEqual(checked.quality['receiver_label'], 'PC-COM6')
        self.assertTrue(checked.quality['transport']['estimated'])
        self.assertEqual(checked.quality['transport']['radio_scope'], 'collar_to_first_receiver')
        self.assertEqual(checked.quality['radio']['rssi_dbm'], -53)
        self.assertEqual(json.loads(original), SAMPLE)

    def test_four_different_collars_preserve_all_readings(self):
        records = [reading({**SAMPLE, 'id': f'REAL0{i}'}) for i in range(1, 5)]
        result = decode_many(wire(bus(*records)), NOW)
        self.assertEqual([p['hardware_id'] for p, _ in result.readings],
                         ['REAL01', 'REAL02', 'REAL03', 'REAL04'])
        self.assertFalse(result.errors)

    def test_bad_sibling_does_not_discard_valid_readings(self):
        bad = reading({**SAMPLE, 'g': [None, -70.66, -1, 0, 99.99]})
        result = decode_many(wire(bus(reading(), bad, reading({**SAMPLE, 'q': 2}))), NOW)
        self.assertEqual([p['seq'] for p, _ in result.readings], [1, 2])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].index, 2)

    def test_all_bad_records_report_errors(self):
        result = decode_many(wire(bus({'packet': SAMPLE})), NOW)
        self.assertFalse(result.readings)
        self.assertEqual(len(result.errors), 1)

    def test_empty_and_oversized_batch_rejected(self):
        for records in ([], [reading()] * 5):
            with self.subTest(size=len(records)), self.assertRaises(ValueError):
                decode_many(wire(bus(readings=records)), NOW)

    def test_malformed_outer_envelope_rejected(self):
        for changes in ({'gc_bus': True}, {'gc_bus': 2}, {'extra': 1},
                        {'receiver': 'BAD ID'}, {'batch': 'A1B2C3D4-4294967296'},
                        {'batch': 'bad'}, {'readings': {}}, {'readings': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                decode_many(wire(bus(**changes)), NOW)

    def test_duplicate_keys_and_nonfinite_json_reject_complete_line(self):
        text = wire(bus())
        for bad in (text.replace('"gc_bus":1', '"gc_bus":1,"gc_bus":1'),
                    text.replace('"q":1', '"q":1,"q":1'),
                    text.replace('"delay_ms":3200', '"delay_ms":NaN')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                decode_many(bad, NOW)

    def test_delay_is_bounded_integer_and_marks_partial_failure(self):
        for value in (-1, 1_800_001, True, 3.0, '3', None):
            result = decode_many(wire(bus(reading(delay_ms=value))), NOW)
            self.assertFalse(result.readings)
            self.assertTrue(result.errors)
        result = decode_many(wire(bus(reading(delay_ms=1_800_000))), NOW)
        self.assertFalse(result.errors)
        self.assertEqual(result.readings[0][0]['observed_at'],
                         (NOW - timedelta(minutes=30)).isoformat())

    def test_routes_are_coherent_for_direct_and_two_hops(self):
        valid = [reading(origin_gateway=0, hops=0, path=0),
                 reading(origin_gateway=1, hops=1, path=2),
                 reading(origin_gateway=2, hops=1, path=4),
                 reading(origin_gateway=1, hops=2, path=6),
                 reading(origin_gateway=2, hops=2, path=6)]
        for record in valid:
            self.assertFalse(decode_many(wire(bus(record)), NOW).errors)
        for t in ({'origin_gateway': 0}, {'origin_gateway': 2},
                  {'path': 3}, {'path': 7}, {'hops': 2}, {'path': True}):
            self.assertTrue(decode_many(wire(bus(reading(**t))), NOW).errors)

    def test_old_individual_json_csv_and_diagnostics_remain_compatible(self):
        envelope = {'packet': SAMPLE, 'radio': {'rssi_dbm': -53, 'snr_db': 7.5}}
        for line in (wire(SAMPLE), wire(envelope), 'Contenido: ' + wire(SAMPLE)):
            result = decode_many(line, NOW)
            self.assertFalse(result.is_bus)
            self.assertEqual(result.readings, (decode(line, NOW),))
        self.assertFalse(decode_many('# GPS estado=SIN SAT', NOW).readings)

    def test_same_reading_across_routes_batches_and_direct_is_idempotent(self):
        first = decode_many(wire(bus()), NOW).readings[0]
        second = decode_many(wire(bus(reading(origin_gateway=2, path=6, hops=2),
                                      batch='01020304-10')), NOW + timedelta(seconds=2)).readings[0]
        direct = decode(wire(SAMPLE), NOW + timedelta(seconds=4))
        self.assertEqual(first[1], second[1])
        self.assertEqual(first[1], direct[1])
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(folder)
            self.assertTrue(archive.enqueue(*first))
            self.assertFalse(archive.enqueue(*second))
            self.assertFalse(archive.enqueue(*direct))
            self.assertEqual(archive.stats()['captured'], 1)

    def test_conflicting_same_identity_still_rejected_by_archive(self):
        first = decode_many(wire(bus()), NOW).readings[0]
        changed = decode_many(wire(bus(reading({**SAMPLE, 't': 20}))), NOW).readings[0]
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(folder)
            archive.enqueue(*first)
            with self.assertRaises(ValueError):
                archive.enqueue(*changed)

    def test_oversized_line_and_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            decode_many(' ' * 8193, NOW)
        with self.assertRaises(ValueError):
            decode_many(wire(bus()), NOW.replace(tzinfo=None))

    def test_invalid_radio_is_not_allowed_to_bind_receiver(self):
        record = reading()
        record['radio']['rssi_dbm'] = True
        result = decode_many(wire(bus(record)), NOW)
        self.assertFalse(result.readings)
        self.assertTrue(result.errors)


class BusCaptureTests(unittest.TestCase):
    def exercise(self, folder, frames, on_write=None, write_error=None):
        # Reuse the checkout's serial fixture; never open a physical USB port.
        from qa.test_capture_runtime import Connection, Event, IdleThread, usb
        directory = Path(folder)
        env = directory / 'test.env'
        env.write_text('INGEST_KEY=synthetic-never-delivered\n', encoding='utf-8')
        args = SimpleNamespace(directory=directory, env_file=env, port='auto',
                               baud=115200, url='http://invalid.test/not-called')
        self.write_attempts = []
        attempts = self.write_attempts

        class BusConnection(Connection):
            def write(self, data):
                attempts.append(data)
                if on_write:
                    on_write(data)
                if write_error:
                    raise write_error
                return len(data)

        with patch('serial.Serial', return_value=BusConnection(frames)), \
             patch('serial.tools.list_ports.comports', return_value=[usb()]), \
             patch.object(staged.threading, 'Thread', IdleThread), \
             patch.object(staged.threading, 'Event', Event), \
             patch('urllib.request.urlopen', side_effect=AssertionError('API is deliberately offline in this test')):
            staged.capture(args)
        return Archive(directory)

    def test_staged_capture_archives_bus_once_and_enqueues_each_reading(self):
        records = [reading({**SAMPLE, 'q': i}) for i in range(1, 5)]
        frame = wire(bus(*records)).encode() + b'\n'
        self.assertGreater(len(frame), 1024)
        with tempfile.TemporaryDirectory() as folder:
            archive = self.exercise(folder, [frame])
            self.assertEqual(archive.stats()['captured'], 4)
            self.assertTrue((Path(folder) / 'receiver.json').exists())
            raw = list((Path(folder) / 'daily').glob('*/serial.jsonl'))
            self.assertEqual(len(raw), 1)
            self.assertEqual(len(raw[0].read_text(encoding='utf-8').splitlines()), 1)
            self.assertEqual(self.write_attempts, [b'#GCACK,A1B2C3D4-9\n'])

    def test_staged_capture_preserves_valid_siblings_and_legacy_frame(self):
        bad = reading({**SAMPLE, 'g': [None, -70.66, -1, 0, 99.99]})
        frame = wire(bus(reading(), bad, reading({**SAMPLE, 'q': 2}))).encode() + b'\n'
        direct = wire({'packet': {**SAMPLE, 'q': 3},
                       'radio': {'rssi_dbm': -44, 'snr_db': 8}}).encode() + b'\n'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertLogs('geocattle.usb', level='WARNING') as logs:
                archive = self.exercise(folder, [frame, direct])
            self.assertEqual(archive.stats()['captured'], 3)
            self.assertTrue(any('Lectura 2 invalida' in item for item in logs.output))
            self.assertFalse(self.write_attempts)

    def test_staged_capture_conflict_does_not_drop_later_valid_siblings(self):
        frame = wire(bus(reading(), reading({**SAMPLE, 't': 20}),
                         reading({**SAMPLE, 'q': 2}))).encode() + b'\n'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertLogs('geocattle.usb', level='WARNING'):
                archive = self.exercise(folder, [frame])
            self.assertEqual(archive.stats()['captured'], 2)
            self.assertFalse(self.write_attempts)

    def test_host_ack_occurs_only_after_sqlite_commit_and_without_api(self):
        with tempfile.TemporaryDirectory() as folder:
            def assert_committed(ack):
                self.assertEqual(ack, b'#GCACK,A1B2C3D4-9\n')
                # A separate connection sees the row only after the commit.
                with closing(sqlite3.connect(Path(folder) / 'captures.sqlite3')) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM captures').fetchone()[0], 1)
                    self.assertEqual(db.execute('SELECT status FROM captures').fetchone()[0], 'pending')

            archive = self.exercise(folder, [wire(bus()).encode() + b'\n'], on_write=assert_committed)
            self.assertEqual(archive.stats()['pending'], 1)
            self.assertEqual(self.write_attempts, [b'#GCACK,A1B2C3D4-9\n'])

    def test_repeated_committed_batch_is_acknowledged_again(self):
        first = wire(bus()).encode() + b'\n'
        repeated = wire(bus(reading(delay_ms=8200))).encode() + b'\n'
        with tempfile.TemporaryDirectory() as folder:
            archive = self.exercise(folder, [first, repeated])
            self.assertEqual(archive.stats()['captured'], 1)
            self.assertEqual(self.write_attempts, [b'#GCACK,A1B2C3D4-9\n'] * 2)

    def test_serial_write_failure_keeps_durable_records_and_can_retry(self):
        frame = wire(bus()).encode() + b'\n'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertLogs('geocattle.usb', level='WARNING') as logs:
                archive = self.exercise(folder, [frame], write_error=OSError('synthetic USB write failure'))
            self.assertEqual(archive.stats()['captured'], 1)
            self.assertTrue(any('No se envio ACK USB' in item for item in logs.output))
            recovered = self.exercise(folder, [frame])
            self.assertEqual(recovered.stats()['captured'], 1)
            self.assertEqual(self.write_attempts, [b'#GCACK,A1B2C3D4-9\n'])

    def test_archive_rejection_never_acknowledges_bus(self):
        frame = wire(bus()).encode() + b'\n'
        # A ValueError represents archive's conflicting identity rejection.
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(staged.Archive, 'enqueue', side_effect=ValueError('synthetic archive failure')):
                with self.assertLogs('geocattle.usb', level='WARNING'):
                    archive = self.exercise(folder, [frame])
            self.assertEqual(archive.stats()['captured'], 0)
            self.assertFalse(self.write_attempts)

    def test_sqlite_commit_failure_never_acknowledges_bus(self):
        frame = wire(bus()).encode() + b'\n'
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(staged.Archive, 'enqueue', side_effect=sqlite3.OperationalError('synthetic disk failure')):
                with self.assertLogs('geocattle.usb', level='WARNING'):
                    archive = self.exercise(folder, [frame])
            self.assertEqual(archive.stats()['captured'], 0)
            self.assertFalse(self.write_attempts)


if __name__ == '__main__':
    unittest.main()
