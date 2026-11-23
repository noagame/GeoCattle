"""Exercise collar identification without opening a physical serial port."""
import json
from io import BytesIO
import unittest
from unittest.mock import Mock, patch

from pathlib import Path
import tempfile

from scripts.register_collar_usb import choose_farm, post_candidate, read_collar


DESCRIPTOR = {
    'type': 'geocattle_collar', 'version': 1, 'hardware_id': 'GC-0123456789AB',
    'transport': 'academic', 'interval_seconds': 45,
}
LEGACY_PACKET = {
    'v': 5, 'id': 'REAL01', 's': '0123456789ABCDEF', 'q': 2, 'u': 48000,
    'g': [None, None, -1, 0, None], 't': None, 'a': [None, None, None],
    'm': [-1, None], 'b': [-1, -1, 0, 0, 1], 'p': 45000, 'f': 7, 'e': 1,
}


def serial_line(message):
    return json.dumps(message, separators=(',', ':')).encode() + b'\r\n'


class RegisterCollarUsbTests(unittest.TestCase):
    def read_stream(self, chunks):
        stream = iter(chunks)
        elapsed = 0
        port = Mock()

        def read_until(**kwargs):
            nonlocal elapsed
            elapsed += 1
            return next(stream, b'')

        port.read_until.side_effect = read_until
        self.enterContext(patch('scripts.register_collar_usb.time.monotonic', side_effect=lambda: elapsed))
        serial = self.enterContext(patch('serial.Serial'))
        serial.return_value.__enter__.return_value = port
        return port

    def test_current_firmware_answers_the_query(self):
        port = self.read_stream([serial_line(DESCRIPTOR)])
        self.assertEqual(read_collar('COM_TEST'), {
            'hardware_id': 'GC-0123456789AB', 'interval_seconds': 45, 'transport': 'academic',
        })
        port.write.assert_called_once_with(b'\nGEOCATTLE_IDENTIFY_V1\n')

    def test_posts_identification_to_the_scoped_ingest_api(self):
        self.read_stream([serial_line({**DESCRIPTOR, 'firmware_version': 'QA-1'})])
        descriptor = read_collar('COM_TEST')
        opener = Mock()
        receipt = {'id': 'candidate-id', 'status': 'pending', 'hardware_id': DESCRIPTOR['hardware_id']}
        opener.open.return_value = BytesIO(serial_line(receipt))
        farm_id = 'bb410a6e-0d11-42bf-8b57-70a25b7b13f9'
        self.assertEqual(post_candidate(opener, 'http://127.0.0.1:8084', descriptor, 'test-key', farm_id), receipt)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8084/api/v1/v3/device-candidates')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(dict(request.header_items())['X-ingest-key'], 'test-key')
        self.assertEqual(dict(request.header_items())['X-farm-id'], farm_id)
        self.assertEqual(json.loads(request.data), {
            'hardware_id': DESCRIPTOR['hardware_id'], 'interval_seconds': 45,
            'firmware_version': 'QA-1', 'transport': 'academic', 'source': 'usb',
        })

    def test_legacy_firmware_is_detected_after_a_full_transmission_interval(self):
        record = serial_line(LEGACY_PACKET)
        diagnostics = [b'# GEOCATTLE T-BEAM AXP2101\r\n', b'# NMEA $GPGGA\r\n']
        self.read_stream([*diagnostics, *([b''] * 43), record[:50], b'', record[50:]])
        self.assertEqual(read_collar('COM_TEST'), {
            'hardware_id': 'REAL01', 'interval_seconds': 45, 'transport': 'academic',
        })

    def test_receiver_envelopes_and_invalid_legacy_frames_cannot_register_a_collar(self):
        envelope = {'packet': LEGACY_PACKET, 'radio': {'rssi_dbm': -40, 'snr_db': 9.5}}
        self.read_stream([
            serial_line(envelope),
            serial_line({'v': 5, 'id': 'REAL01', 'p': 45000}),
            serial_line({**LEGACY_PACKET, 'f': 0}),
        ])
        with self.assertRaisesRegex(ValueError, 'No se recibió la identificación USB'):
            read_collar('COM_TEST')

    def test_overlong_serial_line_cannot_supply_an_identity_suffix(self):
        self.read_stream([b'x' * 1024, serial_line(LEGACY_PACKET)])
        with self.assertRaises(ValueError):
            read_collar('COM_TEST')

    def farm_opener(self, farms):
        opener = Mock()
        opener.open.return_value = BytesIO(json.dumps({'items': farms}).encode())
        return opener

    def test_single_physical_farm_is_used_without_asking(self):
        farm = {'id': 'bb410a6e-0d11-42bf-8b57-70a25b7b13f9', 'name': 'Unico'}
        ask = Mock(side_effect=AssertionError('no debe preguntar'))
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / '.env.academic'
            self.assertEqual(str(choose_farm(self.farm_opener([farm]), 'http://x', 'k', env, ask)), farm['id'])
            self.assertFalse(env.exists())

    def test_several_farms_ask_once_and_remember_the_choice(self):
        farms = [{'id': 'bb410a6e-0d11-42bf-8b57-70a25b7b13f9', 'name': 'El cipres'},
                 {'id': '7c22cb24-916c-4be4-aee2-254c343f212b', 'name': 'Prototipo'}]
        opener = self.farm_opener(farms)
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / '.env.academic'
            env.write_text('INGEST_KEY=secreto', encoding='utf-8')
            answers = iter(['9', '2', ''])
            with patch('builtins.print'):
                chosen = choose_farm(opener, 'http://x', 'k', env, lambda _: next(answers))
            self.assertEqual(str(chosen), farms[1]['id'])
            text = env.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('INGEST_KEY=secreto\n'))
            self.assertIn(f"INGEST_FARM_ID={farms[1]['id']}\n", text)
            answers = iter(['1', 's'])
            with patch('builtins.print'):
                choose_farm(self.farm_opener(farms), 'http://x', 'k', env, lambda _: next(answers))
            self.assertEqual(env.read_text(encoding='utf-8').count('INGEST_FARM_ID='), 1)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'http://x/api/v1/v3/device-candidates/capture-farms')
        self.assertEqual(dict(request.header_items())['X-ingest-key'], 'k')

    def test_no_active_physical_farm_is_explained(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'No hay predios'):
                choose_farm(self.farm_opener([]), 'http://x', 'k', Path(folder) / '.env', Mock())

    def receiver_port(self, serial):
        return Mock(device='COM9', vid=0x1A86, pid=0x55D4, serial_number=serial, location='1-2')

    def write_profile(self, folder, name, serial):
        (Path(folder) / name).write_text(json.dumps({
            'version': 1, 'device': 'COM6', 'vid': 0x1A86, 'pid': 0x55D4, 'serial_number': serial, 'location': '1-2',
        }), encoding='utf-8')

    def test_gateway_base_is_never_released_as_a_collar(self):
        from scripts.register_collar_usb import release_direct_receiver
        with tempfile.TemporaryDirectory() as folder:
            self.write_profile(folder, 'receiver-gateways.json', 'BASE')
            with self.assertRaisesRegex(ValueError, 'base de Gateways'):
                release_direct_receiver(folder, self.receiver_port('BASE'), Mock())
            self.assertTrue((Path(folder) / 'receiver-gateways.json').exists())

    def test_direct_receiver_becomes_a_collar_only_after_confirmation(self):
        from scripts.register_collar_usb import release_direct_receiver
        with tempfile.TemporaryDirectory() as folder:
            self.write_profile(folder, 'receiver.json', 'DIRECTA')
            self.write_profile(folder, 'receiver-gateways.json', 'BASE')
            with patch('builtins.print'), self.assertRaisesRegex(ValueError, 'sigue registrada'):
                release_direct_receiver(folder, self.receiver_port('DIRECTA'), lambda _: '')
            self.assertTrue((Path(folder) / 'receiver.json').exists())
            with patch('builtins.print'):
                self.assertTrue(release_direct_receiver(folder, self.receiver_port('DIRECTA'), lambda _: 's'))
            names = sorted(path.name for path in Path(folder).iterdir())
            self.assertNotIn('receiver.json', names)
            self.assertTrue(any(name.startswith('receiver-retirada-') for name in names))
            self.assertIn('receiver-gateways.json', names)
            self.assertFalse(release_direct_receiver(folder, self.receiver_port('OTRO'), Mock()))

    def test_saved_farm_is_shown_and_can_be_changed(self):
        from uuid import UUID
        from scripts.register_collar_usb import confirm_saved_farm
        farms = [{'id': 'bb410a6e-0d11-42bf-8b57-70a25b7b13f9', 'name': 'El cipres'},
                 {'id': '7c22cb24-916c-4be4-aee2-254c343f212b', 'name': 'Prototipo'}]
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / '.env.academic'
            env.write_text(f"INGEST_KEY=k\nINGEST_FARM_ID={farms[1]['id']}\n", encoding='utf-8')
            saved = UUID(farms[1]['id'])
            with patch('builtins.print'):
                self.assertEqual(confirm_saved_farm(self.farm_opener(farms), 'http://x', 'k', env, saved, lambda _: ''), saved)
            answers = iter(['c', '1', ''])
            with patch('builtins.print'):
                changed = confirm_saved_farm(self.farm_opener(farms), 'http://x', 'k', env, saved, lambda _: next(answers))
            self.assertEqual(str(changed), farms[0]['id'])
            text = env.read_text(encoding='utf-8')
            self.assertIn(f"INGEST_FARM_ID={farms[0]['id']}\n", text)
            self.assertEqual(text.count('INGEST_FARM_ID='), 1)
            self.assertTrue(text.startswith('INGEST_KEY=k\n'))

    def test_inactive_saved_farm_asks_again(self):
        from uuid import UUID
        from scripts.register_collar_usb import confirm_saved_farm
        farms = [{'id': 'bb410a6e-0d11-42bf-8b57-70a25b7b13f9', 'name': 'Unico'}]
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / '.env.academic'
            env.write_text('INGEST_FARM_ID=7c22cb24-916c-4be4-aee2-254c343f212b\n', encoding='utf-8')
            with patch('builtins.print'):
                chosen = confirm_saved_farm(self.farm_opener(farms), 'http://x', 'k', env,
                                            UUID('7c22cb24-916c-4be4-aee2-254c343f212b'), Mock())
            self.assertEqual(str(chosen), farms[0]['id'])
            self.assertIn(f"INGEST_FARM_ID={farms[0]['id']}", env.read_text(encoding='utf-8'))

