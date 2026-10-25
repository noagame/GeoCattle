"""Receiver metadata selection and OS leases. No real USB or application DB."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.serial_receiver import (CaptureAlreadyRunning, CaptureLease,
    ReceiverSelectionError, choose_receiver, enumerate_ports, identity, load_receiver,
    receiver_record, save_receiver)


def port(device, serial='T3-QA', location='1-2', vid=0x1A86, pid=0x55D4, description='USB Serial'):
    return SimpleNamespace(device=device, serial_number=serial, location=location,
        vid=vid, pid=pid, description=description)


class ReceiverSelectionTests(unittest.TestCase):
    def test_remembered_serial_survives_com_and_usb_location_change(self):
        old = receiver_record(port('COM5'))
        moved = port('COM9', location='1-4')
        self.assertIs(choose_receiver([moved], old), moved)

    def test_remembered_receiver_never_falls_back_to_tbeam(self):
        remembered = receiver_record(port('COM5', serial='T3-QA'))
        emitter = port('COM5', serial='TBEAM-QA', location='1-2')
        self.assertIsNone(choose_receiver([emitter], remembered))
        receiver = port('COM9', serial='T3-QA', location='1-3')
        self.assertIs(choose_receiver([emitter, receiver], remembered), receiver)

    def test_initial_ambiguity_requires_explicit_selection(self):
        with self.assertRaisesRegex(ReceiverSelectionError, '-Puerto'):
            choose_receiver([port('COM5'), port('COM7', serial='TBEAM-QA')], None)

    def test_duplicated_serial_identity_never_selects_first(self):
        remembered = receiver_record(port('COM5'))
        with self.assertRaises(ReceiverSelectionError):
            choose_receiver([port('COM5'), port('COM9', location='1-3')], remembered)

    def test_location_fallback_only_when_serial_is_absent(self):
        remembered = receiver_record(port('COM5', serial=None))
        same_location = port('COM9', serial=None)
        self.assertIs(choose_receiver([same_location], remembered), same_location)
        self.assertIsNone(choose_receiver([port('COM9', serial=None, location='1-4')], remembered))
        self.assertIsNone(choose_receiver([port('COM9', serial='TBEAM-QA')], remembered))
        # A missing saved serial is not repaired by taking a different serial.
        with_serial = receiver_record(port('COM5', serial='T3-QA'))
        self.assertIsNone(choose_receiver([port('COM9', serial=None)], with_serial))

    def test_matching_serial_still_requires_same_usb_product(self):
        remembered = receiver_record(port('COM5'))
        self.assertIsNone(choose_receiver([port('COM9', vid=0x10C4)], remembered))
        self.assertIsNone(choose_receiver([port('COM9', pid=0x7523)], remembered))

    def test_explicit_port_overrides_binding_and_never_falls_back(self):
        receiver = port('COM5')
        chosen = port('COM7', serial='MANUAL-QA')
        remembered = receiver_record(receiver)
        self.assertIs(choose_receiver([receiver, chosen], remembered, requested='com7'), chosen)
        self.assertIsNone(choose_receiver([receiver], remembered, requested='COM7'))

    def test_bluetooth_is_ignored_even_if_description_mentions_usb(self):
        bluetooth = port('COM3', serial=None, location=None, vid=None, pid=None, description='CH9102 USB Serial')
        self.assertIsNone(choose_receiver([bluetooth], None))
        self.assertIsNone(choose_receiver([bluetooth], None, requested='COM3'))
        receiver = port('COM5')
        self.assertIs(choose_receiver([bluetooth, receiver], None), receiver)

    def test_single_usb_is_initial_selection_only_and_empty_is_none(self):
        receiver = port('COM5')
        self.assertIs(choose_receiver([receiver], None), receiver)
        self.assertIsNone(choose_receiver([], None))

    def test_invalid_saved_identity_fails_closed(self):
        with self.assertRaises(ReceiverSelectionError):
            choose_receiver([port('COM5')], {'vid': 0x1A86, 'pid': 0x55D4})
        with self.assertRaises(ReceiverSelectionError):
            receiver_record(port('COM5', serial=None, location=None))

    def test_enumeration_uses_metadata_only_and_sorts(self):
        values = [port('COM7'), port('COM5')]
        with patch('serial.tools.list_ports.comports', return_value=values) as listing:
            self.assertEqual([p.device for p in enumerate_ports()], ['COM5', 'COM7'])
            listing.assert_called_once_with()


class ReceiverBindingTests(unittest.TestCase):
    def test_missing_binding_and_atomic_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'receiver.json'
            self.assertIsNone(load_receiver(path))
            selected = port('COM5')
            with patch('adapters.serial_receiver.os.replace', wraps=os.replace) as replace:
                expected = save_receiver(path, selected)
                replace.assert_called_once()
            self.assertEqual(identity(selected), expected)
            self.assertEqual(load_receiver(path), expected)
            self.assertEqual(json.loads(path.read_text())['serial_number'], 'T3-QA')
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_failed_replacement_preserves_old_binding_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'receiver.json'
            original = save_receiver(path, port('COM5'))
            with patch('adapters.serial_receiver.os.replace', side_effect=OSError('simulated replace failure')):
                with self.assertRaises(OSError):
                    save_receiver(path, port('COM7', serial='NEW-QA'))
            self.assertEqual(load_receiver(path), original)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_bom_supported_and_corrupt_config_is_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'receiver.json'
            record = receiver_record(port('COM5'))
            path.write_text(json.dumps(record), encoding='utf-8-sig')
            self.assertEqual(load_receiver(path), record)
            path.write_text('{bad json', encoding='utf-8')
            with self.assertRaisesRegex(ReceiverSelectionError, 'receiver.json'):
                load_receiver(path)


class CaptureLeaseTests(unittest.TestCase):
    def test_second_instance_is_rejected_and_release_allows_new_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            first, second = CaptureLease(directory), CaptureLease(directory)
            first.acquire()
            try:
                with self.assertRaises(CaptureAlreadyRunning):
                    second.acquire()
            finally:
                first.release()
            with second:
                self.assertTrue(second.path.exists())
            # A stale lock file is deliberately retained; it is not a live PID.
            self.assertTrue(first.path.exists())
            with CaptureLease(directory):
                pass

    def test_context_exception_releases_lease_and_release_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            lease = CaptureLease(directory)
            with self.assertRaisesRegex(RuntimeError, 'simulated failure'):
                with lease:
                    raise RuntimeError('simulated failure')
            lease.release()
            with CaptureLease(directory):
                pass

    def test_same_object_acquire_is_idempotent_and_other_directories_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lease = CaptureLease(root / 'one')
            with lease:
                self.assertIs(lease.acquire(), lease)
                with CaptureLease(root / 'two'):
                    pass


if __name__ == '__main__':
    unittest.main()
