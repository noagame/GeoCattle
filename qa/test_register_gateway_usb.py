"""Pruebas de protocolo USB y API usando flujos falsos sin placas físicas."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from adapters.receiver_profiles import save_profile
from scripts import register_gateway_usb as gateway


EUI = '021122fffe334455'
DESCRIPTOR = {'gateway_eui': EUI, 'node_id': None, 'firmware': 'gateway-bus-v1.1'}


def frame(kind='geocattle_gateway', **changes):
    item = {'type': kind, 'version': 1, 'provisioned': False, **DESCRIPTOR, **changes}
    return json.dumps(item).encode('utf-8') + b'\r\n'


class FakeSerial:
    def __init__(self, *data):
        self.frames = list(data)
        self.commands = []

    def write(self, command):
        self.commands.append(command)

    @property
    def in_waiting(self):
        return len(self.frames[0]) if self.frames else 0

    def read(self, size):
        if not self.frames:
            raise AssertionError('Expected a matching reply before EOF')
        block = self.frames.pop(0)
        if len(block) > size:
            self.frames.insert(0, block[size:])
        return block[:size]


class GatewayUsbTest(unittest.TestCase):
    def test_parse_unprovisioned_and_refuse_invalid_replies(self):
        self.assertEqual(gateway.parse_usb_line(frame()), ('geocattle_gateway', DESCRIPTOR))
        self.assertEqual(gateway.parse_usb_line(frame(node_id=0)), ('geocattle_gateway', DESCRIPTOR))
        for changes in ({'node_id': True}, {'node_id': 3}, {'node_id': '1'}, {'provisioned': True},
                        {'version': True}, {'version': 2}, {'gateway_eui': 'invalid'}, {'firmware': ' '}):
            with self.subTest(changes=changes):
                self.assertIsNone(gateway.parse_usb_line(frame(**changes)))
        self.assertIsNone(gateway.parse_usb_line(b'{"type":"geocattle_gateway","node_id":null,"node_id":1}'))
        for line in (b'{"gc_bus":1}', b'{"type":"geocattle_receiver"}', b'{"type":"geocattle_collar"}'):
            with self.assertRaisesRegex(ValueError, 'receptora'):
                gateway.parse_usb_line(line)

    def test_never_open_a_bound_receiver_even_if_com_changed(self):
        with TemporaryDirectory() as directory:
            port = SimpleNamespace(device='COM18', vid=0x1234, pid=0x3333, serial_number='base-test', location=None)
            save_profile(Path(directory), 'gateways', port)
            port.device = 'COM28'
            with self.assertRaisesRegex(ValueError, 'receptora registrada'):
                gateway.reject_receiver(Path(directory), port)
            other = SimpleNamespace(device='COM18', vid=0x1234, pid=0x3333, serial_number='gateway', location=None)
            gateway.reject_receiver(Path(directory), other)

    def test_detection_is_framed_and_ignores_diagnostics(self):
        correct = frame()
        link = FakeSerial(b'# aviso\n', correct[:17], correct[17:])
        identified = gateway.serial_exchange(link, 'GEOCATTLE_IDENTIFY_V1', lambda kind, data: kind == 'geocattle_gateway')
        self.assertEqual(identified, DESCRIPTOR)
        self.assertEqual(link.commands, [b'\nGEOCATTLE_IDENTIFY_V1\n'])

    def test_reserve_serial_confirmation_and_then_approval(self):
        ident = str(uuid4())
        tape = []
        wrong = frame('geocattle_gateway_node', gateway_eui='0011223344556677', node_id=2, provisioned=True)
        right = frame('geocattle_gateway_node', node_id=2, provisioned=True)
        link = FakeSerial(wrong, right)
        csrf = {'X-CSRF-Token': 'test-csrf'}

        def api(_opener, path, body, **headers):
            tape.append(path)
            self.assertEqual(headers, csrf)
            if path.endswith('/reserve'):
                self.assertEqual(link.commands, [])
                return {'reserved_node_id': 2, 'gateway_eui': EUI}
            self.assertEqual(link.commands, [f'\nGEOCATTLE_SET_NODE_V1 {EUI} 2\n'.encode('ascii')])
            self.assertEqual(body, {'confirmed_eui': EUI, 'confirmed_node_id': 2, 'name': 'Gateway QA'})
            return {'gateway': {'name': 'Gateway QA', 'node_id': 2}}

        with patch.object(gateway, 'request_json', side_effect=api), patch('builtins.input', return_value='Gateway QA'):
            self.assertEqual(gateway.enroll(link, None, csrf, {'id': ident}, DESCRIPTOR)['node_id'], 2)
        self.assertEqual(tape, [f'{gateway.ENDPOINT}/{ident}/reserve', f'{gateway.ENDPOINT}/{ident}/approve'])

    def test_no_approval_when_storage_fails(self):
        link = FakeSerial(frame('geocattle_gateway_error', error='nvs'))
        with (patch.object(gateway, 'request_json', return_value={'reserved_node_id': 1, 'gateway_eui': EUI}) as api,
              patch('builtins.input', return_value=''), self.assertRaisesRegex(ValueError, 'memoria')):
            gateway.enroll(link, None, {}, {'id': str(uuid4())}, DESCRIPTOR)
        self.assertEqual(api.call_count, 1)
