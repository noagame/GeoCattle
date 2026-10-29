"""Receiver methods use metadata only; no real USB or application database."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters.serial_receiver import ReceiverSelectionError, save_receiver
from adapters import receiver_profiles as profiles


def port(device='COM6', serial='DIRECT-T3', location='1-2', vid=0x1A86, pid=0x55D4):
    return SimpleNamespace(device=device, serial_number=serial, location=location,
                           vid=vid, pid=pid, description='USB serial')


class ReceiverProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.direct = port()
        self.gateway = port('COM8', 'GATEWAY-T3', '1-3')
        self.xiao = port('COM12', 'XIAO', '1-4', 0x303A, 0x1001)

    def test_modes_are_explicit_and_normalized(self):
        self.assertEqual(profiles.normalize_mode(' DIRECT '), 'direct')
        self.assertEqual(profiles.normalize_mode('Gateways'), 'gateways')
        for invalid in (None, True, 1, '', 'auto', 'gateway', '../direct'):
            with self.subTest(invalid=invalid), self.assertRaises(ReceiverSelectionError):
                profiles.normalize_mode(invalid)
        self.assertEqual(profiles.profile_binding_path(self.directory, 'direct').name,
                         'receiver-direct.json')

    def test_missing_mode_defaults_direct_without_creating_files(self):
        self.assertEqual(profiles.preferred_mode(self.directory), 'direct')
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_selected_mode_is_atomic_and_preserves_archives_and_profiles(self):
        capture = self.directory / 'captures.sqlite3'
        capture.write_bytes(b'untouched archive evidence')
        profiles.save_profile(self.directory, 'direct', self.direct)
        profile = profiles.profile_binding_path(self.directory, 'direct')
        before = profile.read_bytes()
        with patch.object(profiles.os, 'replace', wraps=os.replace) as replace:
            self.assertEqual(profiles.select_mode(self.directory, 'gateways'), 'gateways')
            replace.assert_called_once()
        self.assertEqual(profiles.preferred_mode(self.directory), 'gateways')
        self.assertEqual(capture.read_bytes(), b'untouched archive evidence')
        self.assertEqual(profile.read_bytes(), before)
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_failed_mode_replace_keeps_previous_selection_and_cleans_temporary(self):
        profiles.select_mode(self.directory, 'direct')
        before = (self.directory / 'receiver-mode.json').read_bytes()
        with patch.object(profiles.os, 'replace', side_effect=OSError('replace failed')):
            with self.assertRaises(OSError):
                profiles.select_mode(self.directory, 'gateways')
        self.assertEqual((self.directory / 'receiver-mode.json').read_bytes(), before)
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_corrupt_or_wrong_mode_file_fails_closed(self):
        path = self.directory / 'receiver-mode.json'
        for value in ('not json', '[]', '{"version":true,"mode":"direct"}',
                      '{"version":2,"mode":"direct"}', '{"version":1,"mode":"auto"}',
                      '{"version":1,"mode":"direct","unknown":1}'):
            with self.subTest(value=value):
                path.write_text(value, encoding='utf-8')
                with self.assertRaises(ReceiverSelectionError):
                    profiles.preferred_mode(self.directory)

    def test_legacy_receiver_is_read_only_fallback_for_direct(self):
        legacy = self.directory / 'receiver.json'
        save_receiver(legacy, self.direct)
        before = legacy.read_bytes()
        self.assertEqual(profiles.load_profile(self.directory, 'direct')['serial_number'], 'DIRECT-T3')
        self.assertIsNone(profiles.load_profile(self.directory, 'gateways'))
        profiles.save_profile(self.directory, 'direct', self.direct)
        self.assertEqual(legacy.read_bytes(), before)
        self.assertTrue(profiles.profile_binding_path(self.directory, 'direct').exists())

    def test_explicit_profile_takes_precedence_over_legacy(self):
        save_receiver(self.directory / 'receiver.json', self.direct)
        replacement = port('COM14', 'REPLACEMENT-T3')
        profiles.save_profile(self.directory, 'direct', replacement)
        self.assertEqual(profiles.load_profile(self.directory, 'direct')['serial_number'], 'REPLACEMENT-T3')

    def test_both_profiles_select_correct_identity_when_both_receivers_connected(self):
        profiles.save_profile(self.directory, 'direct', self.direct)
        profiles.save_profile(self.directory, 'gateways', self.gateway)
        values = [self.xiao, self.gateway, self.direct]
        self.assertIs(profiles.choose_profile_receiver(values, self.directory, 'direct'), self.direct)
        self.assertIs(profiles.choose_profile_receiver(values, self.directory, 'gateways'), self.gateway)

    def test_identity_survives_com_and_usb_location_changes(self):
        profiles.save_profile(self.directory, 'gateways', self.gateway)
        moved = port('COM17', 'GATEWAY-T3', '2-9')
        reused_com = port('COM8', 'ANOTHER-BOARD', '1-3')
        self.assertIs(profiles.choose_profile_receiver([reused_com, moved], self.directory, 'gateways'), moved)

    def test_absent_selected_receiver_never_uses_other_method_or_xiao(self):
        profiles.save_profile(self.directory, 'direct', self.direct)
        profiles.save_profile(self.directory, 'gateways', self.gateway)
        self.assertIsNone(profiles.choose_profile_receiver([self.direct, self.xiao], self.directory, 'gateways'))
        self.assertIsNone(profiles.choose_profile_receiver([self.gateway, self.xiao], self.directory, 'direct'))

    def test_unbound_gateway_excludes_legacy_direct_and_xiao(self):
        save_receiver(self.directory / 'receiver.json', self.direct)
        candidates = profiles.candidates_for_mode([self.xiao, self.direct, self.gateway], self.directory, 'gateways')
        self.assertEqual(candidates, [self.gateway])
        self.assertIs(profiles.choose_profile_receiver(candidates, self.directory, 'gateways'), self.gateway)
        self.assertIsNone(profiles.choose_profile_receiver([self.direct, self.xiao], self.directory, 'gateways'))

    def test_multiple_unknown_t3_boards_are_not_selected_arbitrarily(self):
        with self.assertRaises(ReceiverSelectionError):
            profiles.choose_profile_receiver([self.direct, self.gateway], self.directory, 'gateways')
        self.assertIs(profiles.choose_profile_receiver(
            [self.direct, self.gateway], self.directory, 'gateways', 'COM8'), self.gateway)

    def test_saved_profile_cannot_be_reassigned_by_manual_com(self):
        profiles.save_profile(self.directory, 'direct', self.direct)
        self.assertIsNone(profiles.choose_profile_receiver(
            [self.direct, self.gateway], self.directory, 'direct', 'COM8'))
        self.assertIs(profiles.choose_profile_receiver(
            [self.direct, self.gateway], self.directory, 'direct', 'com6'), self.direct)

    def test_same_identity_cannot_be_bound_to_two_methods_even_after_com_renumber(self):
        profiles.save_profile(self.directory, 'direct', self.direct)
        moved = port('COM9', 'DIRECT-T3', '2-1')
        with self.assertRaises(ReceiverSelectionError):
            profiles.save_profile(self.directory, 'gateways', moved)
        self.assertIsNone(profiles.load_profile(self.directory, 'gateways'))

    def test_same_location_only_matches_when_both_serial_numbers_absent(self):
        no_serial = port('COM6', None)
        profiles.save_profile(self.directory, 'direct', no_serial)
        moved = port('COM19', None)
        self.assertIs(profiles.choose_profile_receiver([moved], self.directory, 'direct'), moved)
        with self.assertRaises(ReceiverSelectionError):
            profiles.save_profile(self.directory, 'gateways', moved)
        different = port('COM19', 'DIFFERENT-SERIAL')
        self.assertIsNone(profiles.choose_profile_receiver([different], self.directory, 'direct'))

    def test_corrupt_profile_does_not_fall_back_to_legacy(self):
        save_receiver(self.directory / 'receiver.json', self.direct)
        profiles.profile_binding_path(self.directory, 'direct').write_text('broken', encoding='utf-8')
        with self.assertRaises(ReceiverSelectionError):
            profiles.load_profile(self.directory, 'direct')

    def test_duplicate_existing_profiles_fail_closed(self):
        profiles.save_profile(self.directory, 'direct', self.direct)
        save_receiver(profiles.profile_binding_path(self.directory, 'gateways'), self.direct)
        with self.assertRaises(ReceiverSelectionError):
            profiles.choose_profile_receiver([self.direct], self.directory, 'direct')

    def test_bluetooth_and_identityless_usb_are_not_candidates(self):
        bluetooth = port('COM3', None, None, None, None)
        unidentified = port('COM9', None, None)
        self.assertEqual(profiles.candidates_for_mode(
            [self.xiao, bluetooth, unidentified], self.directory, 'gateways'), [])


if __name__ == '__main__':
    unittest.main()
