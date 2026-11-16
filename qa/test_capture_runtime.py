"""Capture safety: no real serial ports or PostgreSQL are used."""
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import serial
from adapters.lora_usb import Archive, capture, main
from adapters.serial_receiver import CaptureLease, load_receiver, save_receiver
from adapters.receiver_profiles import load_profile
from qa.test_lora_json import SAMPLE


def usb(com='COM6', serial_number='QA-RECEIVER'):
    return SimpleNamespace(device=com, vid=0x1A86, pid=0x55D4, serial_number=serial_number, location='1-2')


def rx(seq=1):
    return json.dumps({'packet': {**SAMPLE, 'q': seq}, 'radio': {'rssi_dbm': -40, 'snr_db': 8}}).encode() + b'\n'


class IdleThread:
    def __init__(self, **kwargs): pass
    def start(self): pass
    def join(self, **kwargs): pass


class Event:
    stopped = False
    def is_set(self): return self.stopped
    def set(self): self.stopped = True
    def wait(self, seconds): return self.stopped


class Connection:
    def __init__(self, lines, failure=KeyboardInterrupt): self.lines = iter(lines); self.failure = failure
    def open(self): pass
    def read_until(self, *args):
        try: return next(self.lines)
        except StopIteration: raise self.failure('fixture end')
    def __enter__(self): return self
    def __exit__(self, *args): return False


class CaptureRuntimeTests(unittest.TestCase):
    def exercise(self, folder, connections, ports, bind=False, requested='auto'):
        directory=Path(folder)
        env=directory/'test.env';env.write_text('INGEST_KEY=synthetic-local-test-key\n',encoding='utf-8')
        if bind: save_receiver(directory/'receiver.json',usb('COM5'))
        args=SimpleNamespace(directory=directory,env_file=env,port=requested,baud=115200,url='http://invalid.test/never-called')
        with patch('serial.Serial',side_effect=connections), patch('serial.tools.list_ports.comports',side_effect=ports), patch('adapters.lora_usb.threading.Thread',IdleThread), patch('adapters.lora_usb.threading.Event',Event):
            capture(args)
        return Archive(directory),json.loads((directory/'status.json').read_text(encoding='utf-8'))

    def test_emitter_without_radio_does_not_bind_or_insert(self):
        with tempfile.TemporaryDirectory() as folder:
            archive,status=self.exercise(folder,[Connection([json.dumps(SAMPLE).encode()+b'\n'])],[[usb()]])
            self.assertEqual(archive.stats()['captured'],0)
            self.assertIsNone(load_profile(Path(folder), 'direct'))
            self.assertIsNone(status['last_packet_at'])

    def test_receiver_envelope_binds_and_preserves_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            archive,status=self.exercise(folder,[Connection([rx()])],[[usb()]])
            self.assertEqual(archive.stats()['captured'],1)
            self.assertEqual(load_profile(Path(folder), 'direct')['serial_number'],'QA-RECEIVER')
            self.assertIsNotNone(status['last_packet_at'])
            self.assertFalse(status['connected'])

    def test_45_second_receiver_frame_is_archived_with_radio(self):
        packet = {**SAMPLE, 'p': 45000}
        frame = json.dumps({'packet': packet, 'radio': {'rssi_dbm': -40, 'snr_db': 8}}).encode() + b'\n'
        with tempfile.TemporaryDirectory() as folder:
            archive, status = self.exercise(folder, [Connection([frame])], [[usb()]])
            self.assertEqual(archive.stats()['captured'], 1)
            self.assertIsNotNone(status['last_packet_at'])
            self.assertEqual(load_profile(Path(folder), 'direct')['serial_number'], 'QA-RECEIVER')
            with archive.connection() as db:
                payload = json.loads(db.execute('SELECT payload FROM captures').fetchone()[0])
            self.assertEqual(payload['quality']['period_ms'], 45000)
            self.assertEqual(payload['quality']['radio']['rssi_dbm'], -40)

    def test_bound_receiver_moves_com_while_other_board_is_present(self):
        with tempfile.TemporaryDirectory() as folder:
            archive,status=self.exercise(folder,[Connection([json.dumps(SAMPLE).encode()+b'\n'])],[[usb('COM7','QA-EMITTER'),usb('COM9')]],bind=True)
            self.assertEqual(archive.stats()['captured'],1)
            with archive.connection() as db:
                payload=json.loads(db.execute('SELECT payload FROM captures').fetchone()[0])
            self.assertEqual(payload['quality']['receiver_label'],'PC-COM9')

    def test_invalid_receiver_frame_cannot_bind(self):
        message={'packet':SAMPLE,'radio':{'rssi_dbm':None,'snr_db':8}}
        with tempfile.TemporaryDirectory() as folder:
            archive,_=self.exercise(folder,[Connection([json.dumps(message).encode()+b'\n'])],[[usb()]])
            self.assertEqual(archive.stats()['captured'],0)
            self.assertIsNone(load_profile(Path(folder), 'direct'))

    def test_disconnect_reconnect_in_another_com_keeps_identity_and_two_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            archive,_=self.exercise(folder,[Connection([rx(1)],serial.SerialException),Connection([rx(2)])],[[usb('COM5')],[usb('COM6')]])
            self.assertEqual(archive.stats()['captured'],2)
            with archive.connection() as db:
                receivers=[json.loads(row[0])['quality']['receiver_label'] for row in db.execute('SELECT payload FROM captures ORDER BY id')]
            self.assertEqual(receivers,['PC-COM5','PC-COM6'])

    def test_second_main_does_not_touch_archive_or_open_usb(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);sentinel=directory/'status.json';sentinel.write_text('{"sentinel": true}',encoding='utf-8')
            with CaptureLease(directory),patch('sys.argv',['capture','--directory',folder]),patch('adapters.lora_usb.capture') as execute:
                main()
            execute.assert_not_called()
            self.assertEqual(json.loads(sentinel.read_text(encoding='utf-8')),{'sentinel':True})

    def test_legacy_reader_blocks_migration_until_paused(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'status.json';path.write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat(),'error':'old COM missing'}),encoding='utf-8')
            with patch('sys.argv',['capture','--directory',folder]),patch('adapters.lora_usb.capture') as execute:
                self.assertEqual(main(),1)
            execute.assert_not_called()


if __name__ == '__main__': unittest.main()
