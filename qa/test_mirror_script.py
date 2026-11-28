"""Contratos de scripts/mirror.py y del perfil mirror sin Docker ni PostgreSQL."""
import base64
import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mirror = load('mirror_script', ROOT / 'scripts/mirror.py')
docker_project = load('docker_project_mirror', ROOT / 'scripts/docker_project.py')
BLOB = base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(32))).decode()
KEY = f'ssh-ed25519 {BLOB} geocattle-campo'
SYNC_KEY = 'clave-ficticia-de-sincronizacion-del-servidor'
MFA_KEY = 'clave-ficticia-de-mfa-que-viene-del-pc'
REPLICA_PASSWORD = 'clave-ficticia-de-replica-del-pc'


class MirrorScriptTest(unittest.TestCase):
    def test_publication_lists_every_mirror_table_and_nothing_private(self):
        sql = mirror.publication_sql(False)
        self.assertTrue(sql.startswith('CREATE PUBLICATION geocattle_espejo FOR TABLE '))
        listed = set(sql.split('FOR TABLE ', 1)[1].split(', '))
        self.assertEqual(listed, set(mirror.mirror_tables.MIRROR))
        for private in ('login_sessions', 'mirror_outbox', 'account_tokens', 'schema_migrations'):
            self.assertNotIn(private, listed)
        self.assertIn('ALTER PUBLICATION geocattle_espejo SET TABLE', mirror.publication_sql(True))

    def test_subscription_quotes_password_and_keeps_errors_visible(self):
        sql = mirror.subscription_sql('geocattle_academic', "cl'ave\\x")
        self.assertIn("password=''cl\\''ave\\\\x''", sql)
        self.assertIn('disable_on_error = false', sql)
        self.assertIn('host=espejo-ssh port=15432', sql)
        with self.assertRaises(mirror.MirrorError):
            mirror.quote_ident('x; DROP TABLE farms')

    def test_add_missing_never_replaces_existing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env.academic'
            path.write_text('DB_PORT=55434\nMIRROR_MODE=off', encoding='utf-8')
            added = mirror.add_missing(path, {'MIRROR_MODE': 'field', 'MIRROR_SSH_HOST': 'espejo-ssh.example.org'})
            self.assertEqual(added, ['MIRROR_SSH_HOST'])
            values = mirror.read_env(path)
            self.assertEqual(values['MIRROR_MODE'], 'off')
            self.assertEqual(values['DB_PORT'], '55434')
            self.assertEqual(mirror.add_missing(path, {'MIRROR_SSH_HOST': 'otro.example.org'}), [])

    def test_tunnel_only_forwards_database_and_support_ports(self):
        values = {'DB_PORT': '55434', 'MIRROR_SSH_HOST': 'espejo-ssh.example.org'}
        with mock.patch.object(mirror, 'KEY', ROOT / 'README.md'):
            command = mirror.tunnel_command(values, cloudflared='C:/cf/cloudflared.exe')
            remote = [command[i + 1] for i, part in enumerate(command) if part == '-R']
            self.assertEqual(remote, ['0.0.0.0:15432:127.0.0.1:55434', '0.0.0.0:18084:127.0.0.1:8084'])
            self.assertIn('ExitOnForwardFailure=yes', command)
            self.assertIn('BatchMode=yes', command)
            self.assertEqual(command[-1], 'espejo@espejo-ssh.example.org')
            self.assertIn('access ssh --hostname %h', ' '.join(command))
            direct = mirror.tunnel_command({**values, 'MIRROR_SUPPORT': 'false'}, direct='127.0.0.1:2222')
            self.assertEqual(direct[-3:], ['-p', '2222', 'espejo@127.0.0.1'])
            self.assertEqual(direct.count('-R'), 1)
        # ssh separa UserKnownHostsFile por espacios: la ruta debe ir entre comillas.
        with mock.patch.object(mirror, 'RUNTIME', Path('C:/Proyecto de Titulo/GeoCattle/.runtime/espejo')), \
                mock.patch.object(mirror, 'KEY', ROOT / 'README.md'):
            command = mirror.tunnel_command(values)
            self.assertIn('UserKnownHostsFile="C:/Proyecto de Titulo/GeoCattle/.runtime/espejo/known_hosts"', command)

    def test_ssh_only_mode_jumps_through_the_server_account(self):
        values = {'DB_PORT': '55434', 'MIRROR_SSH_JUMP': 'operador@servidor.example.org:2201'}
        with mock.patch.object(mirror, 'KEY', ROOT / 'README.md'):
            first = mirror.jump_command(values)
            self.assertEqual(first[-3:], ['-p', '2201', 'operador@servidor.example.org'])
            self.assertIn('127.0.0.1:18022:172.30.248.19:22', first)
            self.assertIn('BatchMode=yes', first)
            second = mirror.tunnel_command(values)
            self.assertEqual(second[-3:], ['-p', '18022', 'espejo@127.0.0.1'])
            self.assertIn('HostKeyAlias=espejo-ssh.servidor.example.org.2201', second)
            self.assertIn('127.0.0.1:18095:web:80', second)
            self.assertNotIn('ProxyCommand', ' '.join(second))
        for bad in ('servidor', 'root;rm@x', 'a@b c', 'operador@servidor:puerto'):
            self.assertIsNone(mirror.JUMP.fullmatch(bad))

    def test_host_account_key_only_reaches_espejo_ssh(self):
        with tempfile.TemporaryDirectory() as folder:
            keys = Path(folder) / '.ssh' / 'authorized_keys'
            keys.parent.mkdir()
            keys.write_text('ssh-ed25519 OTRA llave-existente', encoding='utf-8')
            mirror.authorize_host_account(KEY, keys)
            mirror.authorize_host_account(KEY, keys)
            lines = keys.read_text(encoding='utf-8').splitlines()
            self.assertEqual(lines[0], 'ssh-ed25519 OTRA llave-existente')
            self.assertEqual(lines[1:], [f'restrict,port-forwarding,permitopen="172.30.248.19:22",command="/bin/false" {KEY}'])

    def test_first_admin_is_created_on_the_pc_only(self):
        values = {'POSTGRES_USER': 'geocattle', 'POSTGRES_PASSWORD': 'x', 'DB_PORT': '55434', 'POSTGRES_DB': 'geocattle_academic'}
        command, env = mirror.admin_command(values, 'admin@example.org', 'Admin')
        self.assertEqual(command[1:], ['-m', 'geocattle.seed_v3', '--admin-email', 'admin@example.org', '--admin-name', 'Admin'])
        self.assertIn('@127.0.0.1:55434/geocattle_academic', env['DATABASE_URL'])
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(mirror.subprocess, 'run') as run:
            path = Path(folder) / '.env.pilot'
            path.write_text('MIRROR_MODE=replica\n', encoding='utf-8')
            self.assertEqual(mirror.main(['pc-admin', '--env-file', str(path), '--email', 'admin@example.org']), 1)
            path.write_text('MIRROR_MODE=field\n', encoding='utf-8')
            with mock.patch.dict(mirror.os.environ, {'V3_ADMIN_PASSWORD': 'corta'}), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(mirror.main(['pc-admin', '--env-file', str(path), '--email', 'admin@example.org']), 1)
            run.assert_not_called()

    def test_compose_pins_espejo_ssh_address(self):
        text = (ROOT / 'compose.mirror.yaml').read_text(encoding='utf-8')
        self.assertIn('ipv4_address: 172.30.248.19', text)
        self.assertNotIn('ports:', text)

    def test_authorized_key_is_restricted_to_forwarding(self):
        self.assertTrue(mirror.PUBKEY.fullmatch(KEY))
        self.assertFalse(mirror.PUBKEY.fullmatch('ssh-rsa AAAA geocattle'))
        self.assertFalse(mirror.PUBKEY.fullmatch(KEY + '\ncommand="sh" ' + KEY))

    def test_mirror_profile_requires_cloudflare_and_adds_compose_file(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            docker_project.main(['start', '--environment', 'production', '--profile', 'mirror'])
        args = type('Args', (), {'environment': 'production', 'profile': ['cloudflare', 'mirror']})()
        command = docker_project.compose_command(args, ROOT / '.env.pilot')
        files = [command[i + 1] for i, part in enumerate(command) if part == '-f']
        self.assertEqual([Path(f).name for f in files], ['compose.yaml', 'compose.cloudflare.yaml', 'compose.mirror.yaml'])
        self.assertEqual(command.count('--profile'), 2)
        with self.assertRaises(docker_project.ProjectError):
            docker_project.validate_mirror({'MIRROR_SYNC_KEY': 'corta'})

    def test_native_restart_only_for_the_native_configuration(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(mirror.subprocess, 'run') as run:
            other = Path(folder) / '.env.academic'
            self.assertFalse(mirror.restart_native(other, {'DB_PORT': '55501'}))
            run.assert_not_called()

    def test_sshd_only_allows_reverse_forwarding(self):
        config = (ROOT / 'infrastructure/espejo-ssh/sshd_config').read_text(encoding='utf-8')
        for line in ('PasswordAuthentication no', 'AllowTcpForwarding yes', 'PermitOpen web:80', 'PermitTTY no',
                     'PermitListen 0.0.0.0:15432 0.0.0.0:18084', 'ForceCommand /sbin/nologin', 'AllowUsers espejo'):
            self.assertIn(line, config)

    def test_pc_connect_orders_steps_and_sends_secrets_only_over_ssh_stdin(self):
        steps = []

        def run(argv, **kwargs):
            self.assertFalse(any(secret in ' '.join(argv) for secret in (SYNC_KEY, MFA_KEY, REPLICA_PASSWORD)))
            action = argv[-1].split()[-1]
            steps.append(action)
            payload = json.loads(kwargs['input'])
            self.assertIn('IdentitiesOnly=yes', argv)
            self.assertIn('StrictHostKeyChecking=accept-new', argv)
            self.assertIn(f'UserKnownHostsFile="{known_hosts.as_posix()}"', argv)
            self.assertIn('operador@servidor.example.org', argv)
            if action == 'inspect':
                self.assertEqual(payload, {})
                stdout = json.dumps({'sync_key': SYNC_KEY, 'subscribed': False})
            elif action == 'configure':
                self.assertEqual(payload, {'sync_key': SYNC_KEY, 'mfa_key': MFA_KEY, 'pubkey': KEY})
                stdout = 'Llave instalada.'
            else:
                self.assertEqual(payload, {'sync_key': SYNC_KEY, 'pc_database': 'geocattle_campo',
                                           'password': REPLICA_PASSWORD})
                stdout = 'Suscripción: activa'
            return subprocess.CompletedProcess(argv, 0, stdout, '')

        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            runtime = Path(folder)
            key = runtime / 'id_ed25519'
            key.with_suffix('.pub').write_text(KEY, encoding='utf-8')
            known_hosts = runtime / 'known_hosts.ensayo'
            path = runtime / 'campo.env'
            path.write_text(f'POSTGRES_DB=geocattle_campo\nMFA_ENCRYPTION_KEY={MFA_KEY}\n'
                            f'MIRROR_REPLICA_PASSWORD={REPLICA_PASSWORD}\n', encoding='utf-8')
            with mock.patch.multiple(mirror, RUNTIME=runtime, KEY=key), \
                    mock.patch.object(mirror.subprocess, 'run', side_effect=run), \
                    mock.patch.object(mirror, 'pc_setup', side_effect=lambda *a, **k: steps.append('pc-setup')) as setup, \
                    mock.patch.object(mirror, 'keygen', side_effect=lambda *a: steps.append('keygen')), \
                    mock.patch.object(mirror, 'start_pc_tunnel', side_effect=lambda *a: steps.append('tunnel')):
                self.assertEqual(mirror.main(['pc-connect', '--ssh-jump', 'operador@servidor.example.org:2201',
                                              '--env-file', str(path), '--known-hosts', str(known_hosts), '--yes',
                                              '--no-task', '--identity-file', str(runtime / 'personal')]), 0)
            self.assertEqual(setup.call_args.kwargs, {'sync_key': SYNC_KEY})
            self.assertEqual(steps, ['inspect', 'pc-setup', 'keygen', 'configure', 'tunnel', 'subscribe'])
            self.assertIn('Suscripción: activa', output.getvalue())
            for secret in (SYNC_KEY, MFA_KEY, REPLICA_PASSWORD):
                self.assertNotIn(secret, output.getvalue())

    def test_pc_connect_rejects_non_mirror_before_preparing_the_pc(self):
        result = subprocess.CompletedProcess([], 1, '', 'Error: La API no está en modo réplica.')
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(mirror, 'RUNTIME', Path(folder)), \
                mock.patch.object(mirror.subprocess, 'run', return_value=result) as run, \
                mock.patch.object(mirror, 'pc_setup') as setup, \
                contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(mirror.main(['pc-connect', '--ssh-jump', 'operador@servidor', '--no-task', '--yes']), 1)
        self.assertEqual(run.call_count, 1)
        setup.assert_not_called()
        self.assertIn('no está en modo réplica', output.getvalue())
        self.assertIn('repite el mismo comando pc-connect', output.getvalue())

    def test_mfa_env_can_fill_empty_value_and_is_never_printed(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            runtime = Path(folder)
            env = runtime / '.env.pilot'
            env.write_text('MFA_ENCRYPTION_KEY=\n', encoding='utf-8')
            with mock.patch.object(mirror, 'RUNTIME', runtime), \
                    mock.patch.dict(mirror.os.environ, {'MIRROR_PC_MFA_KEY': MFA_KEY}), \
                    mock.patch.object(mirror.getpass, 'getpass') as ask:
                self.assertEqual(mirror.main(['server-init', '--env-file', str(env)]), 0)
                ask.assert_not_called()
                self.assertEqual(mirror.read_env(env)['MFA_ENCRYPTION_KEY'], MFA_KEY)
            self.assertNotIn(MFA_KEY, output.getvalue())

    def test_pc_connect_installs_and_runs_the_windows_task(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            runtime = Path(folder)
            path = runtime / 'campo.env'
            hosts = runtime / 'known_hosts.ensayo'
            args = SimpleNamespace(no_task=False, env_file=path, known_hosts=hosts)
            with mock.patch.object(mirror, 'os', SimpleNamespace(name='nt')), \
                    mock.patch.object(mirror, 'RUNTIME', runtime), \
                    mock.patch.object(mirror.subprocess, 'run') as run:
                mirror.start_pc_tunnel(args)
            create, start = (call.args[0] for call in run.call_args_list)
            self.assertEqual(create[:5], ['schtasks', '/Create', '/F', '/TN', mirror.TASK_NAME])
            self.assertEqual(start, ['schtasks', '/Run', '/TN', mirror.TASK_NAME])
            script = (runtime / 'tunel.cmd').read_text(encoding='utf-8')
            self.assertIn(f'"--env-file" "{path}"', script)
            self.assertIn(f'"--known-hosts" "{hosts}"', script)

    def test_remote_repeat_preserves_subscription_mfa_and_tunnel_config(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            runtime = Path(folder)
            keys = runtime / 'host_keys'
            args = SimpleNamespace(host_account=True, host_keys=keys, env_file=None, compose_file=None)
            with mock.patch.object(mirror, 'RUNTIME', runtime), \
                    mock.patch.object(mirror, 'compose', return_value=(['docker', 'compose'], {}, {})), \
                    mock.patch.object(mirror.subprocess, 'run') as run, \
                    mock.patch('docker_project.main') as start, \
                    mock.patch.object(mirror, 'server_init') as init, \
                    mock.patch.object(mirror, 'pc_reachable', return_value=True), \
                    mock.patch.object(mirror, 'subscription_exists', return_value=True), \
                    mock.patch.object(mirror, 'psql', return_value='1'), \
                    mock.patch.object(mirror, 'wait_sync') as wait, \
                    mock.patch.object(mirror, 'status', return_value=0) as status, \
                    mock.patch.object(mirror, 'subscribe') as subscribe:
                mirror.authorize(args, line=KEY)
                run.assert_called_once()
                run.reset_mock()
                self.assertEqual(mirror.configure_server(args, {'MFA_ENCRYPTION_KEY': MFA_KEY},
                                                         {'mfa_key': MFA_KEY, 'pubkey': KEY}), 0)
                self.assertEqual(mirror.subscribe_from_pc(args, {'pc_database': 'geocattle_campo'}), 0)
                run.assert_not_called()
                init.assert_not_called()
                start.assert_not_called()
                subscribe.assert_not_called()
                wait.assert_called_once_with(args)
                status.assert_called_once_with(args)
                self.assertEqual(keys.read_text(encoding='utf-8').splitlines(), [mirror.host_account_line(KEY)])

    def test_remote_retries_interrupted_mfa_restart(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            runtime = Path(folder)
            path = runtime / '.env.pilot'
            path.write_text(f'MIRROR_SYNC_KEY={SYNC_KEY}\n', encoding='utf-8')
            args = SimpleNamespace(env_file=path, skip_secrets=False, managed=True)
            payload = {'mfa_key': MFA_KEY, 'pubkey': KEY}
            with mock.patch.object(mirror, 'RUNTIME', runtime), mock.patch.object(mirror, 'authorize'), \
                    mock.patch('docker_project.main', side_effect=[1, 0]) as start:
                with self.assertRaisesRegex(mirror.MirrorError, 'quedó pendiente'):
                    mirror.configure_server(args, mirror.read_env(path), payload)
                self.assertEqual(mirror.read_env(path)['MFA_ENCRYPTION_KEY'], MFA_KEY)
                self.assertTrue(mirror.mfa_restart_pending().exists())
                mirror.configure_server(args, mirror.read_env(path), payload)
                self.assertFalse(mirror.mfa_restart_pending().exists())
                self.assertEqual(start.call_count, 2)

    def test_remote_applies_a_changed_mfa_key_once(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()) as output:
            runtime = Path(folder)
            path = runtime / '.env.pilot'
            previous_key = 'clave-ficticia-anterior-para-factores-totp'
            path.write_text(f'MIRROR_SYNC_KEY={SYNC_KEY}\nMFA_ENCRYPTION_KEY={previous_key}\n', encoding='utf-8')
            args = SimpleNamespace(env_file=path, skip_secrets=False, managed=True)
            payload = {'mfa_key': MFA_KEY, 'pubkey': KEY}
            with mock.patch.object(mirror, 'RUNTIME', runtime), mock.patch.object(mirror, 'authorize'), \
                    mock.patch('docker_project.main', return_value=0) as start:
                mirror.configure_server(args, mirror.read_env(path), payload)
                mirror.configure_server(args, mirror.read_env(path), payload)
            self.assertEqual(mirror.read_env(path)['MFA_ENCRYPTION_KEY'], MFA_KEY)
            start.assert_called_once()
            self.assertNotIn(previous_key, output.getvalue())
            self.assertNotIn(MFA_KEY, output.getvalue())


if __name__ == '__main__':
    unittest.main()
