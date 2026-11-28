"""Deployment package and proxy security checks with fixture credentials."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import configure, docker_project, empaquetar_despliegue


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSecurityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('docker'), 'Requires the Docker Compose CLI')
    def test_production_mirror_compose_has_no_ports_and_propagates_remote_write_switches(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'qa.env'
            configure.write_configuration('production', config, {
                **docker_project.production_overrides('geocattle.example.invalid'),
                'COMPOSE_PROJECT_NAME': 'geocattle-security-config-qa',
                'MIRROR_SYNC_KEY': 'fictitious-qa-mirror-key-for-compose',
                'MIRROR_REMOTE_ADMIN': 'false',
                'MIRROR_REMOTE_CHANGES': 'false',
            })
            env = docker_project.command_environment(docker_project.read_config(config, 'production'))
            result = subprocess.run([
                'docker', 'compose', '--env-file', str(config),
                '-f', 'compose.yaml', '-f', 'compose.cloudflare.yaml', '-f', 'compose.mirror.yaml',
                '--profile', 'cloudflare', '--profile', 'mirror', 'config', '--format', 'json',
            ], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)['services']
        self.assertEqual(set(services), {'api', 'cloudflared', 'database', 'espejo-ssh', 'migrate', 'web', 'worker'})
        for service in services.values():
            self.assertFalse(service.get('ports'))
        for service in ('api', 'migrate', 'worker'):
            with self.subTest(service=service):
                config = services[service]['environment']
                self.assertEqual(config['MIRROR_MODE'], 'replica')
                self.assertEqual(config['MIRROR_REMOTE_ADMIN'], 'false')
                self.assertEqual(config['MIRROR_REMOTE_CHANGES'], 'false')

    def test_production_rejects_short_database_and_api_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'qa.env'
            configure.write_configuration('production', config, {
                **docker_project.production_overrides('geocattle.example.invalid'),
                'TUNNEL_TOKEN': 'fictitious-qa-tunnel',
            })
            values = docker_project.read_config(config, 'production')
            docker_project.validate_cloudflare(values)
            for key in ('POSTGRES_PASSWORD', 'APP_DATABASE_PASSWORD', 'SESSION_SECRET', 'INGEST_KEY'):
                with self.subTest(key=key):
                    with self.assertRaisesRegex(docker_project.ProjectError, key):
                        docker_project.validate_cloudflare({**values, key: 'short-qa-value'})

    def test_cloudflare_rejects_wildcard_cors_alongside_public_origin(self):
        origin = 'https://geocattle.example.invalid'
        with self.assertRaisesRegex(docker_project.ProjectError, 'ALLOWED_ORIGINS'):
            docker_project.validate_cloudflare({
                'TUNNEL_TOKEN': 'fictitious-qa-tunnel',
                'INVITATION_BASE_URL': origin,
                'ALLOWED_ORIGINS': f'{origin}, *',
                'ALLOWED_HOSTS': 'geocattle.example.invalid,localhost,127.0.0.1',
                'COOKIE_SECURE': 'true',
            })

    def test_public_example_and_sources_are_the_only_packaged_fixtures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            names = ('.env.example', 'app.py', 'firmware/config.h')
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture', encoding='utf-8')
            git = subprocess.CompletedProcess([], 0, stdout='\0'.join(names).encode())
            with patch.object(empaquetar_despliegue, 'ROOT', root), \
                 patch.object(empaquetar_despliegue.subprocess, 'run', return_value=git):
                package, count, _ = empaquetar_despliegue.build(root / 'output', full=True)
            with tarfile.open(package) as archive:
                self.assertEqual(archive.getnames(), ['.env.example', 'app.py'])
            self.assertEqual(count, 2)

    def test_server_package_keeps_only_what_the_server_uses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            names = ('Abrir-GeoCattle.cmd', 'README.md', 'AGENTS.md', 'compose.yaml', 'backend/geocattle/main.py',
                     'backend/tests/test_rules.py', 'backend/AGENTS.md', 'database/migrations/001_schema.sql',
                     'docs/OPERACION.md', 'docs/DESPLIEGUE_SERVIDOR_ESPEJO.md', 'firmware/sketch.ino',
                     'frontend/src/App.tsx', 'frontend/tests/mirror.test.mjs', 'qa/test_x.py',
                     'scripts/mirror.py', 'scripts/prototype_windows.py')
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture', encoding='utf-8')
            git = subprocess.CompletedProcess([], 0, stdout='\0'.join(names).encode())
            with patch.object(empaquetar_despliegue, 'ROOT', root),                  patch.object(empaquetar_despliegue.subprocess, 'run', return_value=git):
                package, _, _ = empaquetar_despliegue.build(root / 'output')
            with tarfile.open(package) as archive:
                self.assertEqual(sorted(archive.getnames()), [
                    'AGENTS.md', 'backend/geocattle/main.py', 'compose.yaml', 'database/migrations/001_schema.sql',
                    'docs/DESPLIEGUE_SERVIDOR_ESPEJO.md', 'frontend/src/App.tsx', 'scripts/mirror.py'])
                agents = archive.extractfile('AGENTS.md').read().decode('utf-8')
            self.assertIn('Parte A', agents)
            self.assertNotEqual(agents, 'fixture')

    def test_tracked_private_paths_abort_before_creating_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for name in ('.env.qa', 'other/.ENV.local', '.runtime/fixture.txt', 'backups/fixture.dump',
                         'db.sqlite3', 'db.sqlite3-wal'):
                with self.subTest(name=name):
                    git = subprocess.CompletedProcess([], 0, stdout=name.encode() + b'\0')
                    with patch.object(empaquetar_despliegue, 'ROOT', root), \
                         patch.object(empaquetar_despliegue.subprocess, 'run', return_value=git):
                        with self.assertRaises(SystemExit):
                            empaquetar_despliegue.build(root / 'output')
                    self.assertFalse((root / 'output').exists())

    def test_linked_source_aborts_before_creating_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / 'source.py'
            target = root / 'fixture.py'
            target.write_text('fixture', encoding='utf-8')
            git = subprocess.CompletedProcess([], 0, stdout=b'source.py\0')
            with patch.object(empaquetar_despliegue, 'ROOT', root), \
                 patch.object(empaquetar_despliegue.subprocess, 'run', return_value=git), \
                 patch.object(type(source), 'resolve', return_value=target):
                with self.assertRaisesRegex(SystemExit, 'enlaces'):
                    empaquetar_despliegue.build(root / 'output')
            self.assertFalse((root / 'output').exists())

    @unittest.skipUnless(os.getenv('GEOCATTLE_QA_NGINX_IMAGE'), 'Requires a local nginx image with curl')
    def test_nginx_headers_and_body_limit_with_isolated_proxy(self):
        config = ROOT / 'infrastructure/nginx.conf'
        checks = r"""
set -eu
cp /qa/nginx.conf /etc/nginx/conf.d/default.conf
nginx -t
# Represent the connector on a separate loopback address in this isolated container.
sed -i 's/172\.30\.248\.18/127.0.0.2/g' /etc/nginx/conf.d/default.conf
nginx
curl -fsSI -H 'X-Forwarded-Proto: https' http://127.0.0.1/ > /tmp/http-headers
curl -sSI --interface 127.0.0.2 -H 'X-Forwarded-Proto: https' \
    http://127.0.0.1/mapa-local/osm/0/0/0.png > /tmp/https-headers
if grep -qi '^Strict-Transport-Security:' /tmp/http-headers; then exit 1; fi
grep -qi '^HTTP/1.1 404' /tmp/https-headers
grep -qi '^Strict-Transport-Security: max-age=31536000' /tmp/https-headers
grep -qi '^Server: nginx' /tmp/https-headers
if grep -qi '^Server: nginx/' /tmp/https-headers; then exit 1; fi
grep -qi '^Content-Security-Policy: .*frame-ancestors' /tmp/https-headers
grep -qi '^X-Frame-Options: DENY' /tmp/https-headers
grep -qi '^X-Content-Type-Options: nosniff' /tmp/https-headers
dd if=/dev/zero of=/tmp/oversize bs=1048576 count=3 2>/dev/null
test "$(curl -s -o /dev/null -w '%{http_code}' --data-binary @/tmp/oversize \
    http://127.0.0.1/api/v1/ingest/receiver-batch)" = 413
"""
        result = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'sh',
            '--mount', f'type=bind,source={config},target=/qa/nginx.conf,readonly',
            os.environ['GEOCATTLE_QA_NGINX_IMAGE'], '-c', checks,
        ], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
