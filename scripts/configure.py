#!/usr/bin/env python3
"""Generate private local configuration without replacing an existing file."""
import argparse
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'simulation': ('.env', 'simulation', '8080', '55432', '1884', '8081', '8443'),
    'development': ('.env.academic', 'academic', '8084', '55434', '1886', '8085', '8445'),
    'production': ('.env.pilot', 'pilot', '8082', '55433', '1885', '8083', '8444'),
}


def write_configuration(environment='simulation', output=None, overrides=None):
    """Return the chosen Path; atomically create it only when absent.

    Overrides are for trusted Python callers such as docker_project, not CLI
    input. Existing configuration and credentials are never rewritten.
    """
    filename, label, web, database, mqtt, chirpstack, tls = PROFILES[environment]
    path = Path(output) if output is not None else ROOT / filename
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if path.exists():
        print(f'{path.name} ya existe. Se conserva sin cambios.')
        return path
    simulation = environment == 'simulation'
    token = lambda: secrets.token_hex(32)
    values = {
        'COMPOSE_PROJECT_NAME': f'geocattle-{label}',
        'APP_ENV': environment,
        'SIMULATION_ENABLED': str(simulation).lower(),
        'POSTGRES_DB': f'geocattle_{label}',
        'POSTGRES_USER': 'geocattle',
        'POSTGRES_PASSWORD': token(),
        'APP_DATABASE_PASSWORD': token(),
        'SESSION_SECRET': token(),
        'INGEST_KEY': token(),
        'DEMO_PASSWORD': secrets.token_urlsafe(18) if simulation else '',
        'ADMIN_PASSWORD': '' if simulation else secrets.token_urlsafe(18),
        'COOKIE_SECURE': str(environment == 'production').lower(),
        'ALLOWED_ORIGINS': (f'https://localhost:{tls},https://127.0.0.1:{tls}' if environment == 'production'
            else f'http://localhost:{web},http://127.0.0.1:{web},http://localhost:5173,http://127.0.0.1:5173'),
        'WEB_PORT': web,
        'TLS_PORT': tls,
        'DB_PORT': database,
        'MQTT_USERNAME': 'geocattle',
        'MQTT_PASSWORD': token(),
        'MQTT_PORT': mqtt,
        'MQTT_TOPIC': 'application/+/device/+/event/up,geocattle/academic/telemetry',
        'MQTT_SPOOL_PATH': '/data/mqtt-spool.sqlite3',
        'CHIRPSTACK_DB_PASSWORD': token(),
        'CHIRPSTACK_API_SECRET': token(),
        'CHIRPSTACK_PORT': chirpstack,
        'CONFIG_DOWNLINK_ENABLED': 'false',
        'CONFIG_CODEC_VALIDATED': 'false',
        'CHIRPSTACK_APPLICATION_ID': '',
        'CONFIG_FPORT': '10',
        'NOTIFICATION_WEBHOOK_URL': '',
    }
    values.update(overrides or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f'{path.name} ya existe. Se conserva sin cambios.')
        return path
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write('# Configuracion privada generada; no incluir en Git.\n')
        stream.write('\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
    print(f'Creado {path.name} con secretos aleatorios. Conservar como archivo privado.')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', choices=PROFILES, default='simulation')
    parser.add_argument('--output', type=Path, help='Archivo privado de salida; nunca sobrescribe uno existente')
    args = parser.parse_args(argv)
    write_configuration(args.environment, args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
