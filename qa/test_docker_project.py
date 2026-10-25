"""Lifecycle contract tests: mocked Docker, no database or daemon required."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import configure
from scripts import docker_project as project


class DockerProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(project, 'ROOT', self.root).start()
        patch.object(configure, 'ROOT', self.root).start()
        self.runner = patch.object(project.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)).start()
        self.output, self.errors = io.StringIO(), io.StringIO()

    def invoke(self, *arguments):
        with contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.errors):
            return project.main(list(arguments))

    def calls(self):
        return [call.args[0] for call in self.runner.call_args_list]

    def test_prepare_generates_simulation_without_running_docker(self):
        self.assertEqual(self.invoke('prepare'), 0)
        self.runner.assert_not_called()
        values = project.read_config(self.root / '.env', 'simulation')
        self.assertEqual(values['WEB_PORT'], '8080')
        self.assertEqual(values['DB_PORT'], '55432')
        self.assertEqual(values['SIMULATION_ENABLED'], 'true')
        self.assertGreaterEqual(len(values['SESSION_SECRET']), 32)
        self.assertNotIn(values['SESSION_SECRET'], self.output.getvalue())

    def test_configure_output_option_never_overwrites_existing_configuration(self):
        destination = self.root / 'private' / 'chosen.env'
        with contextlib.redirect_stdout(self.output):
            configure.main(['--environment', 'development', '--output', str(destination)])
        before = destination.read_bytes()
        with contextlib.redirect_stdout(self.output):
            configure.main(['--environment', 'simulation', '--output', str(destination)])
        self.assertEqual(destination.read_bytes(), before)
        self.assertFalse((self.root / '.env.academic').exists())

    def test_development_has_separate_ports_project_and_capture_directory(self):
        self.assertEqual(self.invoke('prepare', '--environment', 'development'), 0)
        values = project.read_config(self.root / '.env.docker', 'development')
        expected = {'COMPOSE_PROJECT_NAME': 'geocattle-docker-academic', 'POSTGRES_DB': 'geocattle_docker_academic',
                    'WEB_PORT': '8086', 'DB_PORT': '55436', 'MQTT_PORT': '1888', 'CHIRPSTACK_PORT': '8087',
                    'TLS_PORT': '8447', 'USB_CAPTURE_DIR': '.runtime/docker-capture', 'SIMULATION_ENABLED': 'false'}
        self.assertEqual({key: values[key] for key in expected}, expected)
        self.assertFalse((self.root / '.env.academic').exists())

    def test_simulation_start_waits_then_runs_seed_and_v3_reconciliation(self):
        with patch.dict(os.environ, {'APP_ENV': 'production', 'COMPOSE_PROFILES': 'tools',
                                     'COMPOSE_FILE': 'unrelated.yaml'}, clear=False):
            self.assertEqual(self.invoke('start'), 0)
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0], ['docker', 'compose', 'version'])
        self.assertEqual(calls[1][-6:], ['up', '-d', '--build', '--wait', '--wait-timeout', '180'])
        self.assertEqual(calls[2][-5:], ['tools', 'run', '--rm', '--no-deps', 'seed'])
        self.assertEqual(calls[3][-4:], ['seed', 'python', '-m', 'geocattle.seed_v3'])
        self.assertNotIn(str(self.root / 'compose.usb.yaml'), calls[1])
        for call in self.runner.call_args_list:
            self.assertEqual(call.kwargs['env']['APP_ENV'], 'simulation')
            self.assertNotIn('COMPOSE_FILE', call.kwargs['env'])
            self.assertNotIn('COMPOSE_PROFILES', call.kwargs['env'])
            self.assertEqual(call.kwargs['cwd'], self.root)
            self.assertTrue(call.kwargs['check'])

    def test_development_without_explicit_owner_does_not_seed_or_bootstrap(self):
        self.assertEqual(self.invoke('start', '--environment', 'development'), 0)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn(str(self.root / 'compose.usb.yaml'), self.calls()[1])
        self.assertTrue((self.root / '.runtime/docker-capture').is_dir())
        self.assertIn('No se crearon cuentas', self.output.getvalue())
        self.assertNotIn('geocattle.seed', ' '.join(self.calls()[1]))

    def test_development_owner_is_explicit_and_conciliated_without_simulation_seed(self):
        self.assertEqual(self.invoke('start', '--environment', 'development', '--owner-email', 'Owner@Example.local',
                                     '--farm', 'Predio de prueba'), 0)
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[2][-6:], ['bootstrap', 'python', '-c', project.OWNER_BOOTSTRAP,
                                       'owner@example.local', 'Predio de prueba'])
        self.assertEqual(calls[3][-4:], ['seed', 'python', '-m', 'geocattle.seed_v3'])
        self.assertNotIn('geocattle.seed', [item for call in calls for item in call])
        self.assertNotIn('V3_ADMIN_PASSWORD', ' '.join(item for call in calls for item in call))

    def test_lorawan_also_enables_its_iot_broker_and_profiles_are_not_duplicated(self):
        self.assertEqual(self.invoke('start', '--profile', 'lorawan', '--profile', 'lorawan'), 0)
        call = self.calls()[1]
        self.assertEqual(call.count('iot'), 1)
        self.assertEqual(call.count('lorawan'), 1)
        self.assertLess(call.index('iot'), call.index('lorawan'))

    def test_stop_preserves_volumes_and_does_not_seed(self):
        self.invoke('prepare')
        self.runner.reset_mock()
        self.assertEqual(self.invoke('stop'), 0)
        self.assertEqual(self.calls()[-1][-1], 'down')
        for command in self.calls():
            self.assertNotIn('-v', command)
            self.assertNotIn('--volumes', command)
            self.assertNotIn('seed', command)

    def test_status_and_logs_use_same_private_configuration(self):
        custom = self.root / 'custom.env'
        self.invoke('prepare', '--env-file', str(custom))
        before = custom.read_bytes()
        self.assertEqual(self.invoke('status', '--env-file', str(custom)), 0)
        self.assertEqual(self.calls()[-1][-1], 'ps')
        self.assertEqual(self.invoke('logs', '--env-file', str(custom)), 0)
        self.assertEqual(self.calls()[-1][-3:], ['logs', '--tail', '100'])
        self.assertEqual(custom.read_bytes(), before)
        self.assertIn(str(custom), self.calls()[-1])

    def test_wrong_environment_is_rejected_without_changing_file_or_running_docker(self):
        self.invoke('prepare')
        path = self.root / '.env'
        before = path.read_bytes()
        self.runner.reset_mock()
        self.assertEqual(self.invoke('start', '--environment', 'development', '--env-file', str(path)), 1)
        self.assertEqual(path.read_bytes(), before)
        self.runner.assert_not_called()

    def test_native_academic_configuration_is_reserved_even_when_explicit(self):
        path = self.root / '.env.academic'
        path.write_text('canary - do not modify', encoding='utf-8')
        self.assertEqual(self.invoke('prepare', '--environment', 'development', '--env-file', str(path)), 1)
        self.assertEqual(path.read_text(), 'canary - do not modify')
        self.runner.assert_not_called()

    def test_backup_streams_binary_to_private_file_without_password_arguments(self):
        self.invoke('prepare')
        values = project.read_config(self.root / '.env', 'simulation')
        self.runner.reset_mock()
        def fake_run(command, **kwargs):
            if 'exec' in command:
                kwargs['stdout'].write(b'PGDMP-test')
            return subprocess.CompletedProcess(command, 0)
        self.runner.side_effect = fake_run
        self.assertEqual(self.invoke('backup'), 0)
        files = list((self.root / 'backups').glob('*.dump'))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), b'PGDMP-test')
        self.assertIn(values['COMPOSE_PROJECT_NAME'], files[0].name)
        self.assertFalse(list((self.root / 'backups').glob('*.part')))
        command = self.calls()[-1]
        self.assertIn('$POSTGRES_PASSWORD', command[-1])
        self.assertNotIn(values['POSTGRES_PASSWORD'], ' '.join(command))
        self.assertNotIn(values['POSTGRES_PASSWORD'], self.output.getvalue())
        self.assertNotIn('bash', command)

    def test_failed_backup_removes_only_its_incomplete_file(self):
        self.invoke('prepare')
        folder = self.root / 'backups'
        folder.mkdir()
        preserved = folder / 'existing.dump'
        preserved.write_bytes(b'previous valid backup')
        def fail_dump(command, **kwargs):
            if 'exec' in command:
                kwargs['stdout'].write(b'incomplete')
                raise subprocess.CalledProcessError(7, command)
            return subprocess.CompletedProcess(command, 0)
        self.runner.side_effect = fail_dump
        self.assertEqual(self.invoke('backup'), 1)
        self.assertEqual(preserved.read_bytes(), b'previous valid backup')
        self.assertEqual(list(folder.iterdir()), [preserved])

    def test_backup_collision_never_deletes_another_partial_file(self):
        self.invoke('prepare')
        values = project.read_config(self.root / '.env', 'simulation')
        folder = self.root / 'backups'
        folder.mkdir()
        existing = folder / f"{values['COMPOSE_PROJECT_NAME']}-{values['POSTGRES_DB']}-FIXED.dump.part"
        existing.write_bytes(b'other capture in progress')
        with patch.object(project, 'datetime') as clock:
            clock.now.return_value.strftime.return_value = 'FIXED'
            self.assertEqual(self.invoke('backup'), 1)
        self.assertEqual(existing.read_bytes(), b'other capture in progress')

    def test_backup_never_replaces_an_existing_complete_backup(self):
        self.invoke('prepare')
        values = project.read_config(self.root / '.env', 'simulation')
        folder = self.root / 'backups'
        folder.mkdir()
        existing = folder / f"{values['COMPOSE_PROJECT_NAME']}-{values['POSTGRES_DB']}-FIXED.dump"
        existing.write_bytes(b'previous complete backup')
        def fake_run(command, **kwargs):
            if 'exec' in command:
                kwargs['stdout'].write(b'new backup')
            return subprocess.CompletedProcess(command, 0)
        self.runner.side_effect = fake_run
        with patch.object(project, 'datetime') as clock:
            clock.now.return_value.strftime.return_value = 'FIXED'
            self.assertEqual(self.invoke('backup'), 1)
        self.assertEqual(existing.read_bytes(), b'previous complete backup')
        self.assertEqual(list(folder.iterdir()), [existing])

    def test_empty_backup_is_not_published(self):
        self.invoke('prepare')
        self.assertEqual(self.invoke('backup'), 1)
        self.assertEqual(list((self.root / 'backups').iterdir()), [])

    def test_missing_docker_returns_actionable_error_without_traceback(self):
        self.runner.side_effect = FileNotFoundError('missing')
        self.assertEqual(self.invoke('start'), 1)
        self.assertIn('Docker no esta disponible', self.errors.getvalue())
        self.assertNotIn('Traceback', self.errors.getvalue())

    def test_owner_options_must_be_explicit_and_used_together(self):
        for args in [('start', '--owner-email', 'owner@example.local'),
                     ('start', '--owner-email', 'owner@example.local', '--farm', 'Farm'),
                     ('prepare', '--environment', 'development', '--owner-email', 'owner@example.local', '--farm', 'Farm')]:
            with self.subTest(args=args), self.assertRaises(SystemExit):
                self.invoke(*args)
        self.runner.assert_not_called()

    def test_owner_bootstrap_existing_owner_never_overwrites_password(self):
        self.check_owner_bootstrap(SimpleNamespace(role='owner'), False)

    def test_owner_bootstrap_rejects_existing_nonowner(self):
        with self.assertRaises(SystemExit):
            self.check_owner_bootstrap(SimpleNamespace(role='worker'), False)

    def test_owner_bootstrap_creates_only_when_absent(self):
        self.check_owner_bootstrap(None, True)

    def check_owner_bootstrap(self, existing, should_create):
        db = Mock()
        db.scalar.return_value = existing
        session = Mock()
        session.__enter__ = Mock(return_value=db)
        session.__exit__ = Mock(return_value=False)
        database = ModuleType('geocattle.db')
        database.SessionLocal = Mock(return_value=session)
        models = ModuleType('geocattle.models')
        models.User = SimpleNamespace(username=Mock(), email=Mock())
        boot = ModuleType('geocattle.bootstrap')
        boot.bootstrap = Mock()
        sqlalchemy = ModuleType('sqlalchemy')
        sqlalchemy.select = Mock(return_value=Mock())
        sqlalchemy.func = Mock()
        sqlalchemy.or_ = Mock()
        package = ModuleType('geocattle')
        modules = {'geocattle': package, 'geocattle.db': database, 'geocattle.models': models,
                   'geocattle.bootstrap': boot, 'sqlalchemy': sqlalchemy}
        with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['bootstrap', 'owner@example.local', 'Farm']), \
             patch.dict(os.environ, {'ADMIN_PASSWORD': 'synthetic-password-123'}), contextlib.redirect_stdout(self.output):
            exec(project.OWNER_BOOTSTRAP, {})
        if should_create:
            boot.bootstrap.assert_called_once_with('owner@example.local', 'Farm', 'synthetic-password-123')
        else:
            boot.bootstrap.assert_not_called()


if __name__ == '__main__':
    unittest.main()
