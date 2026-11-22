#!/usr/bin/env python3
"""Ejecuta mantenimiento con la configuración privada del prototipo."""
import argparse
import os
from pathlib import Path
import subprocess
from urllib.parse import quote


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=root / '.env.academic')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('smtp-test').add_argument('--to', required=True)
    commands.add_parser('mfa-reset').add_argument('--email', required=True)
    args = parser.parse_args()
    try:
        lines = args.env_file.read_text(encoding='utf-8-sig').splitlines()
    except OSError:
        parser.error('No se pudo abrir el archivo de configuración privada')
    values = {}
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    env = {**os.environ, **values, 'PYTHONPATH': str(root / 'backend'), 'PYTHONUTF8': '1'}
    if args.command == 'mfa-reset':
        try:
            port = int(values['DB_PORT'])
            database = quote(values['POSTGRES_DB'], safe='')
            password = quote(values['APP_DATABASE_PASSWORD'], safe='')
        except (KeyError, ValueError):
            parser.error('Revisa DB_PORT, POSTGRES_DB y APP_DATABASE_PASSWORD en el archivo privado')
        env['DATABASE_URL'] = f'postgresql+psycopg://geocattle_app:{password}@127.0.0.1:{port}/{database}'
        parameters = ['--email', args.email]
    else:
        parameters = ['--to', args.to]
    executable = Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python')
    candidates = [root / '.venv' / executable, root / 'backend' / '.venv' / executable]
    python = next((path for path in candidates if path.is_file()), None)
    if python is None:
        parser.error('Falta el entorno Python de GeoCattle. Ejecuta uv sync desde backend.')
    return subprocess.call(
        [str(python), '-m', 'geocattle.account_maintenance', args.command, *parameters],
        cwd=root / 'backend', env=env,
    )


if __name__ == '__main__':
    raise SystemExit(main())
