"""Exercise collar identification without opening a physical serial port."""
import json
from io import BytesIO
import unittest
from unittest.mock import Mock, patch

from scripts.register_collar_usb import post_candidate, read_collar


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
