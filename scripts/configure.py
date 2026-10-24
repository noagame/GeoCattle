#!/usr/bin/env python3
"""Genera credenciales locales sin sobrescribir una configuración existente."""
import argparse
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--environment', choices=['simulation', 'development', 'production'], default='simulation')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    simulation = args.environment == 'simulation'
    profiles = {
        'simulation': ('.env', 'simulation', '8080', '55432', '1884', '8081', '8443'),
        'development': ('.env.academic', 'academic', '8084', '55434', '1886', '8085', '8445'),
        'production': ('.env.pilot', 'pilot', '8082', '55433', '1885', '8083', '8444'),
    }
    filename, label, web_port, db_port, mqtt_port, chirpstack_port, tls_port = profiles[args.environment]
    path = root / filename
    if path.exists():
        print(f'{path.name} ya existe. Se conserva sin cambios.')
        return
    secret = lambda: secrets.token_hex(32)
    values = {
        'COMPOSE_PROJECT_NAME': f'geocattle-{label}',
        'APP_ENV': args.environment,
        'SIMULATION_ENABLED': str(simulation).lower(),
        'POSTGRES_DB': f'geocattle_{label}',
        'POSTGRES_USER': 'geocattle',
        'POSTGRES_PASSWORD': secret(),
        'APP_DATABASE_PASSWORD': secret(),
        'SESSION_SECRET': secret(),
        'INGEST_KEY': secret(),
        'DEMO_PASSWORD': secrets.token_urlsafe(18) if simulation else '',
        'ADMIN_PASSWORD': '' if simulation else secrets.token_urlsafe(18),
        'COOKIE_SECURE': str(args.environment == 'production').lower(),
        'ALLOWED_ORIGINS': (f'https://localhost:{tls_port},https://127.0.0.1:{tls_port}' if args.environment == 'production'
                            else f'http://localhost:{web_port},http://127.0.0.1:{web_port},http://localhost:5173,http://127.0.0.1:5173'),
        'WEB_PORT': web_port,
        'TLS_PORT': tls_port,
        'DB_PORT': db_port,
        'MQTT_USERNAME': 'geocattle',
        'MQTT_PASSWORD': secret(),
        'MQTT_PORT': mqtt_port,
        'MQTT_TOPIC': 'application/+/device/+/event/up,geocattle/academic/telemetry',
        'MQTT_SPOOL_PATH': '/data/mqtt-spool.sqlite3',
        'CHIRPSTACK_DB_PASSWORD': secret(),
        'CHIRPSTACK_API_SECRET': secret(),
        'CHIRPSTACK_PORT': chirpstack_port,
        'CONFIG_DOWNLINK_ENABLED': 'false',
        'CONFIG_CODEC_VALIDATED': 'false',
        'CHIRPSTACK_APPLICATION_ID': '',
        'CONFIG_FPORT': '10',
        'NOTIFICATION_WEBHOOK_URL': '',
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write('# Configuración privada generada; no incluir en control de versiones.\n')
        file.write('\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
    print(f'Creado {path.name} con secretos aleatorios y permisos 600.')
    print('Las credenciales de acceso se encuentran en ese archivo privado.')


if __name__ == '__main__':
    main()
