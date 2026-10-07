#!/usr/bin/env python3
"""Ejecuta el backend local cargando secretos sin pasarlos en argumentos."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['migrate', 'seed', 'serve', 'worker', 'ingestor', 'test', 'qa-users', 'qa-revoke-browser'])
    parser.add_argument('--env-file', type=Path, help='Configuración privada alternativa de simulación')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = args.env_file.resolve() if args.env_file else root / '.env'
    if not config.exists():
        parser.error('Ejecute primero python3 scripts/configure.py')
    private = {}
    for line in config.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            private[key] = value
    env = {**os.environ, **private}
    # Configuración sólo de desarrollo y QA. Operación usa el usuario restringido
    # del contenedor; migración/seed/tests necesitan el usuario de preparación.
    env['DATABASE_URL'] = 'postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@127.0.0.1:{DB_PORT}/{POSTGRES_DB}'.format(**private)
    env['PYTHONPATH'] = str(root / 'backend')
    env['MQTT_HOST'] = '127.0.0.1'
    env['MQTT_PORT'] = private.get('MQTT_PORT', '1884')
    env['MQTT_SPOOL_PATH'] = str(root / '.runtime' / 'mqtt-spool.sqlite3')
    if args.command == 'test':
        if private.get('APP_ENV') != 'simulation':
            parser.error('Las pruebas integradas requieren una base de simulación separada')
        env['TEST_DATABASE_URL'] = env['DATABASE_URL']
    python = root / 'backend' / '.venv' / 'bin' / 'python'
    if not python.exists():
        parser.error('Instale dependencias: cd backend && uv sync --extra test')
    commands = {
        'migrate': [str(python), '-m', 'geocattle.migrate'],
        'seed': [str(python), '-m', 'geocattle.seed'],
        'serve': [str(python), '-m', 'uvicorn', 'geocattle.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload'],
        'worker': [str(python), '-m', 'geocattle.worker'],
        'ingestor': [str(python), '-m', 'geocattle.ingestor'],
        'test': [str(python), '-m', 'pytest', '-q'],
        'qa-users': [str(python), str(root / 'qa' / 'seed_test_users.py')],
        'qa-revoke-browser': [str(python), '-c', 'import runpy; runpy.run_path("../qa/seed_test_users.py")["revoke_browser"]()'],
    }
    return subprocess.call(commands[args.command], cwd=root / 'backend', env=env)


if __name__ == '__main__':
    raise SystemExit(main())
