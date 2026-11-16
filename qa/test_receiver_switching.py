"""One reader alternates exact USB profiles; hardware and server are simulated."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import serial
from adapters.lora_usb import Archive, capture
from adapters.receiver_profiles import load_profile, save_profile, select_mode
from qa.test_capture_runtime import Event, IdleThread, usb
from qa.test_lora_bus import SAMPLE, bus, reading, wire


def individual(seq=1):
    return wire({'packet': {**SAMPLE, 'q': seq},
                 'radio': {'rssi_dbm': -44, 'snr_db': 8}}).encode() + b'\n'


def batch(*sequences):
    records = [reading({**SAMPLE, 'q': seq}) for seq in (sequences or (1,))]
    return wire(bus(*records)).encode() + b'\n'


class StopOnWait(Event):
    def wait(self, seconds):
        raise KeyboardInterrupt('fixture stopped while awaiting selected USB')


class TrackingConnection:
    def __init__(self, label, actions, tracker, failure=KeyboardInterrupt):
        self.label, self.actions, self.tracker = label, iter(actions), tracker
        self.failure = failure

    def open(self):
        if self.tracker['active'] is not None:
            raise AssertionError('Second port opened before closing the first')
        self.tracker['active'] = self.label
        self.tracker['events'].append(('open', self.label, self.port))

    def read_until(self, *args):
        try:
            action = next(self.actions)
        except StopIteration:
            raise self.failure('fixture end')
        return action() if callable(action) else action

    def write(self, data):
        self.tracker['acks'].append((self.label, data))
        return len(data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.tracker['events'].append(('close', self.label, self.port))
        self.tracker['active'] = None
        return False


class ReceiverSwitchingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = self.directory / 'test.env'
        self.env.write_text('INGEST_KEY=synthetic-never-delivered\n', encoding='utf-8')
        self.direct = usb('COM6', 'DIRECT-T3')
        self.gateway = usb('COM8', 'GATEWAY-T3')
        self.xiao = SimpleNamespace(device='COM12', vid=0x303A, pid=0x1001,
                                    serial_number='XIAO-QA', location='1-4')
        self.tracker = {'active': None, 'events': [], 'acks': []}

    def choose(self, mode):
        def changed():
            select_mode(self.directory, mode)
            return b''
        return changed

    def connection(self, name, *actions, failure=KeyboardInterrupt):
        return TrackingConnection(name, actions, self.tracker, failure)

    def run_capture(self, connections, ports, requested='auto', event=Event):
        args = SimpleNamespace(directory=self.directory, env_file=self.env,
                               port=requested, baud=115200,
                               url='http://invalid.test/not-called')
        with patch('serial.Serial', side_effect=connections) as constructor, \
             patch('serial.tools.list_ports.comports', side_effect=ports), \
             patch('adapters.lora_usb.threading.Thread', IdleThread), \
             patch('adapters.lora_usb.threading.Event', event), \
             patch('urllib.request.urlopen', side_effect=AssertionError('API must not be called')):
            capture(args)
        state = json.loads((self.directory / 'status.json').read_text(encoding='utf-8'))
        return Archive(self.directory), state, constructor

    def bind_both(self):
        save_profile(self.directory, 'direct', self.direct)
        save_profile(self.directory, 'gateways', self.gateway)

    def test_hot_switch_closes_before_opening_and_deduplicates_same_reading(self):
        self.bind_both()
        select_mode(self.directory, 'direct')
        moved_direct, moved_gateway = usb('COM19', 'DIRECT-T3'), usb('COM23', 'GATEWAY-T3')
        connections = [self.connection('direct', individual(1), self.choose('gateways')),
                       self.connection('gateways', batch(1, 2))]
        archive, state, constructor = self.run_capture(
            connections, [[moved_direct, self.xiao, moved_gateway]] * 2, requested='COM19')
        self.assertEqual(self.tracker['events'], [
            ('open', 'direct', 'COM19'), ('close', 'direct', 'COM19'),
            ('open', 'gateways', 'COM23'), ('close', 'gateways', 'COM23')])
        self.assertEqual(constructor.call_count, 2)
        self.assertEqual(archive.stats()['captured'], 2)
        self.assertEqual(self.tracker['acks'], [('gateways', b'#GCACK,A1B2C3D4-9\n')])
        self.assertEqual(state['receiver_mode'], 'gateways')
        self.assertEqual(state['wire_format'], 'bus_v1')
        self.assertEqual(state['receiver_profiles_version'], 1)
        self.assertEqual(load_profile(self.directory, 'direct')['serial_number'], 'DIRECT-T3')
        self.assertEqual(load_profile(self.directory, 'gateways')['serial_number'], 'GATEWAY-T3')
        with archive.connection() as db:
            rows = db.execute('SELECT seq,payload FROM captures ORDER BY seq').fetchall()
        self.assertEqual([row['seq'] for row in rows], [1, 2])
        self.assertEqual(json.loads(rows[0]['payload'])['quality']['capture_method'], 'direct')
        self.assertEqual(json.loads(rows[1]['payload'])['quality']['capture_method'], 'gateways')

    def test_returning_to_direct_keeps_one_shared_archive(self):
        self.bind_both()
        select_mode(self.directory, 'direct')
        connections = [self.connection('direct-first', individual(1), self.choose('gateways')),
                       self.connection('gateways', batch(1, 2), self.choose('direct')),
                       self.connection('direct-last', individual(2), individual(3))]
        archive, state, _ = self.run_capture(connections, [[self.direct, self.gateway]] * 3)
        self.assertEqual(archive.stats()['captured'], 3)
        self.assertEqual(state['receiver_mode'], 'direct')
        self.assertEqual(state['wire_format'], 'individual')
        self.assertEqual(len(list(self.directory.glob('captures.sqlite3'))), 1)
        self.assertEqual([event[0] for event in self.tracker['events']],
                         ['open', 'close', 'open', 'close', 'open', 'close'])
        self.assertEqual(len(self.tracker['acks']), 1)

    def test_direct_mode_does_not_accept_or_ack_bus(self):
        select_mode(self.directory, 'direct')
        with self.assertLogs('geocattle.usb', level='WARNING'):
            archive, state, _ = self.run_capture([self.connection('direct', batch())], [[self.direct]])
        self.assertEqual(archive.stats()['captured'], 0)
        self.assertIsNone(load_profile(self.directory, 'direct'))
        self.assertFalse(self.tracker['acks'])
        self.assertIsNone(state['last_packet_at'])

    def test_gateway_mode_does_not_accept_individual_frame(self):
        select_mode(self.directory, 'gateways')
        with self.assertLogs('geocattle.usb', level='WARNING'):
            archive, state, _ = self.run_capture([self.connection('gateways', individual())], [[self.gateway]])
        self.assertEqual(archive.stats()['captured'], 0)
        self.assertIsNone(load_profile(self.directory, 'gateways'))
        self.assertFalse(self.tracker['acks'])
        self.assertIsNone(state['last_packet_at'])

    def test_known_profile_still_checks_expected_protocol(self):
        save_profile(self.directory, 'direct', self.direct)
        select_mode(self.directory, 'direct')
        with self.assertLogs('geocattle.usb', level='WARNING'):
            archive, _, _ = self.run_capture([self.connection('direct', batch(), individual(2))], [[self.direct]])
        self.assertEqual(archive.stats()['captured'], 1)
        self.assertFalse(self.tracker['acks'])
        with archive.connection() as db:
            self.assertEqual(db.execute('SELECT seq FROM captures').fetchone()[0], 2)

    def test_xiao_is_not_opened_as_gateway_base(self):
        select_mode(self.directory, 'gateways')
        with self.assertLogs('geocattle.usb', level='WARNING'):
            archive, state, constructor = self.run_capture([], [[self.xiao]], event=StopOnWait)
        constructor.assert_not_called()
        self.assertEqual(archive.stats()['captured'], 0)
        self.assertIsNone(state['port'])
        self.assertFalse(state['connected'])

    def test_missing_gateway_never_falls_back_to_present_direct_t3(self):
        self.bind_both()
        select_mode(self.directory, 'gateways')
        with self.assertLogs('geocattle.usb', level='WARNING') as logs:
            _, state, constructor = self.run_capture([], [[self.direct, self.xiao]], event=StopOnWait)
        constructor.assert_not_called()
        self.assertEqual(state['receiver_mode'], 'gateways')
        self.assertTrue(any('no se cambiara al otro metodo' in entry for entry in logs.output))

    def test_unbound_gateway_excludes_already_bound_direct_identity(self):
        save_profile(self.directory, 'direct', self.direct)
        select_mode(self.directory, 'gateways')
        archive, _, constructor = self.run_capture(
            [self.connection('gateways', batch())], [[self.direct, self.gateway, self.xiao]])
        constructor.assert_called_once()
        self.assertEqual(self.tracker['events'][0], ('open', 'gateways', 'COM8'))
        self.assertEqual(archive.stats()['captured'], 1)
        self.assertEqual(load_profile(self.directory, 'gateways')['serial_number'], 'GATEWAY-T3')

    def test_gateway_disconnect_and_com_renumber_keep_identity(self):
        save_profile(self.directory, 'gateways', self.gateway)
        select_mode(self.directory, 'gateways')
        moved = usb('COM31', 'GATEWAY-T3')
        connections = [self.connection('gateway-first', batch(1), failure=serial.SerialException),
                       self.connection('gateway-return', batch(2))]
        with self.assertLogs('geocattle.usb', level='WARNING'):
            archive, _, _ = self.run_capture(connections, [[self.gateway], [self.direct, moved, self.xiao]])
        self.assertEqual(archive.stats()['captured'], 2)
        self.assertEqual(self.tracker['events'], [
            ('open', 'gateway-first', 'COM8'), ('close', 'gateway-first', 'COM8'),
            ('open', 'gateway-return', 'COM31'), ('close', 'gateway-return', 'COM31')])
        self.assertEqual(len(self.tracker['acks']), 2)

    def test_switch_while_partial_line_is_pending_discards_only_partial_line(self):
        self.bind_both()
        select_mode(self.directory, 'direct')
        connections = [self.connection('direct', b'{"packet":', self.choose('gateways')),
                       self.connection('gateways', batch(2))]
        archive, _, _ = self.run_capture(connections, [[self.direct, self.gateway]] * 2)
        self.assertEqual(archive.stats()['captured'], 1)
        raw = list((self.directory / 'daily').glob('*/serial.jsonl'))
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(raw[0].read_text(encoding='utf-8').splitlines()), 1)
        self.assertEqual(self.tracker['events'][1][0], 'close')
        self.assertEqual(self.tracker['events'][2][0], 'open')


if __name__ == '__main__':
    unittest.main()
