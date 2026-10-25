"""Cross-platform host-capture configuration; no USB, Docker or DB is touched."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from scripts.start_capture import capture_context
from adapters.serial_receiver import choose_receiver


class CapturePortabilityTests(unittest.TestCase):
    def context(self, folder, platform, config, backend='auto',filename=None):
        root=Path(folder)
        for name,content in config.items():(root/name).write_text(content,encoding='utf-8')
        args=SimpleNamespace(backend=backend,env_file=Path(filename) if filename else None,directory=None,api_url=None)
        with patch('scripts.start_capture.ROOT',root),patch('scripts.start_capture.platform.system',return_value=platform):
            return capture_context(args)

    def test_windows_existing_prototype_keeps_its_native_archive_and_port(self):
        with tempfile.TemporaryDirectory() as folder:
            result=self.context(folder,'Windows',{'.env.academic':'APP_ENV=development\nSIMULATION_ENABLED=false\nWEB_PORT=8084\n'})
            self.assertEqual(result['backend'],'native')
            self.assertEqual(result['directory'],Path(folder)/'.runtime/capture')
            self.assertEqual(result['base_url'],'http://127.0.0.1:8084')

    def test_linux_uses_docker_even_if_windows_config_is_present(self):
        with tempfile.TemporaryDirectory() as folder:
            values='APP_ENV=development\nSIMULATION_ENABLED=false\nWEB_PORT=8086\nUSB_CAPTURE_DIR=.runtime/docker-capture\n'
            result=self.context(folder,'Linux',{'.env.academic':values,'.env.docker':values})
            self.assertEqual(result['backend'],'docker')
            self.assertEqual(result['directory'],Path(folder)/'.runtime/docker-capture')
            self.assertEqual(result['base_url'],'http://127.0.0.1:8086')

    def test_explicit_docker_uses_separate_configuration_on_windows(self):
        with tempfile.TemporaryDirectory() as folder:
            result=self.context(folder,'Windows',{'.env.docker':'APP_ENV=development\nSIMULATION_ENABLED=false\nWEB_PORT=18086\n'},backend='docker')
            self.assertEqual(result['backend'],'docker')
            self.assertEqual(result['base_url'],'http://127.0.0.1:18086')

    def test_physical_data_cannot_be_routed_to_simulation_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(SystemExit,'simulacion'):
                self.context(folder,'Linux',{'.env.docker':'APP_ENV=simulation\nSIMULATION_ENABLED=true\n'},backend='docker')

    def test_explicit_native_on_linux_is_rejected_with_docker_instruction(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(SystemExit,'docker'):
                self.context(folder,'Linux',{},backend='native')

    def test_linux_by_id_symlink_resolves_to_enumerated_usb_identity(self):
        port=SimpleNamespace(device='/dev/ttyUSB0',vid=6790,pid=21972,serial_number='QA',location='1-2')
        with patch('adapters.serial_receiver.os.path.realpath',return_value='/dev/ttyUSB0'):
            self.assertIs(choose_receiver([port],None,'/dev/serial/by-id/usb-QA'),port)


if __name__=='__main__':unittest.main()
