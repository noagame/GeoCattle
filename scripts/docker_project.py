#!/usr/bin/env python3
"""Ciclo de vida de Docker Compose en Windows y Linux, sin shell del anfitrión.

Ejemplos:
  python scripts/docker_project.py start
  python scripts/docker_project.py start --environment development
  python scripts/docker_project.py start --environment development --owner-email owner@example.local --farm "Mi predio"
  python scripts/docker_project.py start --environment production --profile cloudflare
  python scripts/docker_project.py start --environment production --profile cloudflare --profile mirror
En simulación se cargan datos sintéticos. En desarrollo no se cargan y la
captura USB se ejecuta aparte en el anfitrión. La creación de propietario
requiere start en desarrollo o producción. Los volúmenes se conservan.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

try:
    from .configure import write_configuration
except ImportError:
    from configure import write_configuration

ROOT = Path(__file__).resolve().parents[1]
DOCKER_ACADEMIC = {
    'COMPOSE_PROJECT_NAME': 'geocattle-docker-academic',
    'POSTGRES_DB': 'geocattle_docker_academic',
    'WEB_PORT': '8086', 'DB_PORT': '55436', 'MQTT_PORT': '1888',
    'CHIRPSTACK_PORT': '8087', 'TLS_PORT': '8447',
    'ALLOWED_ORIGINS': 'http://localhost:8086,http://127.0.0.1:8086',
    'USB_CAPTURE_DIR': '.runtime/docker-capture',
}
# Runs inside the bootstrap container. The password stays in its environment.
OWNER_BOOTSTRAP = """
import os, sys
from sqlalchemy import func, or_, select
from geocattle.db import SessionLocal
from geocattle.models import User
from geocattle.bootstrap import bootstrap
email, farm = sys.argv[1:]
with SessionLocal() as db:
    existing = db.scalar(select(User).where(or_(func.lower(User.username) == email, func.lower(User.email) == email)))
    if existing and existing.role != 'owner':
        raise SystemExit('La cuenta existe con otro perfil; no se cambio su acceso.')
if existing:
    print('Propietario existente: credenciales, estado y predio conservados.')
else:
    bootstrap(email, farm, os.environ.get('ADMIN_PASSWORD', ''))
    print('Propietario y predio preparados. Conservar el archivo privado de acceso.')
"""


class ProjectError(RuntimeError):
    pass


def config_path(args):
    defaults = {'simulation': '.env', 'development': '.env.docker', 'production': '.env.pilot'}
    path = args.env_file or Path(defaults[args.environment])
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if path == (ROOT / '.env.academic').resolve():
        raise ProjectError('La configuracion USB .env.academic esta reservada. Usa .env.docker u otro archivo Docker.')
    return path


def read_config(path, environment):
    if not path.is_file():
        raise ProjectError('Falta configuracion. Ejecuta primero la accion prepare para ese entorno.')
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        values[key] = value
    if values.get('APP_ENV') != environment or values.get('SIMULATION_ENABLED', '').lower() != str(environment == 'simulation').lower():
        raise ProjectError('El archivo pertenece a otro entorno. No se modifico; elige el --environment y --env-file correctos.')
    if not re.fullmatch('[a-z0-9][a-z0-9_-]*', values.get('COMPOSE_PROJECT_NAME', '')):
        raise ProjectError('COMPOSE_PROJECT_NAME debe identificar un proyecto Docker local valido.')
    required = ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'APP_DATABASE_PASSWORD',
                'SESSION_SECRET', 'INGEST_KEY', 'MQTT_PASSWORD', 'CHIRPSTACK_DB_PASSWORD', 'CHIRPSTACK_API_SECRET')
    if any(not values.get(key) for key in required):
        raise ProjectError('Faltan valores requeridos en el archivo privado; no se reemplazaron credenciales existentes.')
    if environment == 'development' and not values.get('USB_CAPTURE_DIR'):
        values['USB_CAPTURE_DIR'] = DOCKER_ACADEMIC['USB_CAPTURE_DIR']
    return values


def production_overrides(domain):
    # Public origin, tunnel placeholder and V3 administrator password for a new .env.pilot.
    return {'ALLOWED_HOSTS': f'{domain},localhost,127.0.0.1', 'ALLOWED_ORIGINS': f'https://{domain}',
            'INVITATION_BASE_URL': f'https://{domain}', 'TUNNEL_TOKEN': 'TOKEN_FICTICIO_DE_CLOUDFLARE',
            'V3_ADMIN_PASSWORD': secrets.token_urlsafe(18)}


def prepare(args):
    path = config_path(args)
    overrides = DOCKER_ACADEMIC if args.environment == 'development' else None
    if args.domain:
        if path.exists():
            print(f'{path.name} ya existe: --domain no modifica una configuracion existente.')
        overrides = production_overrides(args.domain)
    write_configuration(args.environment, path, overrides)
    values = read_config(path, args.environment)
    print(f'Configuracion Docker: {path}')
    return path, values


def command_environment(values):
    env = {**os.environ, **values}
    # Explicit CLI profiles/files and the selected private configuration win.
    for key in ('COMPOSE_PROFILES', 'COMPOSE_FILE', 'COMPOSE_ENV_FILES'):
        env.pop(key, None)
    if values.get('APP_ENV') == 'production':
        env['COMPOSE_PROFILES'] = 'cloudflare'
    return env


def compose_command(args, path):
    command = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(path),
               '-f', str(ROOT / 'compose.yaml')]
    if args.environment == 'development':
        command += ['-f', str(ROOT / 'compose.usb.yaml')]
    if 'cloudflare' in args.profile:
        command += ['-f', str(ROOT / 'compose.cloudflare.yaml')]
    if 'mirror' in args.profile:
        command += ['-f', str(ROOT / 'compose.mirror.yaml')]
    profiles = list(dict.fromkeys(args.profile))
    if 'lorawan' in profiles and 'iot' not in profiles:
        profiles.insert(0, 'iot')  # ChirpStack uses the local broker.
    for profile in profiles:
        command += ['--profile', profile]
    return command


def validate_cloudflare(values):
    token = values.get('TUNNEL_TOKEN', '').strip()
    if not token or token == 'TOKEN_FICTICIO_DE_CLOUDFLARE':
        raise ProjectError('Configura TUNNEL_TOKEN en el archivo privado de producción.')
    url = values.get('INVITATION_BASE_URL', '')
    match = re.fullmatch(r'https://([a-z0-9-]+(?:\.[a-z0-9-]+)+)', url)
    origins = {origin.strip() for origin in values.get('ALLOWED_ORIGINS', '').split(',')}
    if '*' in origins:
        raise ProjectError('ALLOWED_ORIGINS debe enumerar orígenes sin comodín.')
    if not match or url not in origins:
        raise ProjectError('Usa el mismo origen HTTPS público en INVITATION_BASE_URL y ALLOWED_ORIGINS.')
    hosts = {host.strip() for host in values.get('ALLOWED_HOSTS', '').split(',')}
    if not {match[1], 'localhost', '127.0.0.1'} <= hosts or any('*' in host for host in hosts):
        raise ProjectError('ALLOWED_HOSTS debe incluir el dominio público, localhost y 127.0.0.1 sin comodines.')
    if values.get('COOKIE_SECURE', '').lower() != 'true':
        raise ProjectError('El perfil cloudflare requiere COOKIE_SECURE=true.')
    for key in ('POSTGRES_PASSWORD', 'APP_DATABASE_PASSWORD', 'SESSION_SECRET', 'INGEST_KEY'):
        if len(values.get(key, '').strip()) < 32:
            raise ProjectError(f'{key} requiere al menos 32 caracteres en producción.')


def validate_mirror(values):
    if len(values.get('MIRROR_SYNC_KEY', '').strip()) < 32:
        raise ProjectError('El perfil mirror requiere MIRROR_SYNC_KEY. Ejecuta: python3 scripts/mirror.py server-init')
    if not (ROOT / '.runtime/espejo/authorized_keys').is_file():
        raise ProjectError('Falta .runtime/espejo/authorized_keys. Ejecuta: python3 scripts/mirror.py server-init')


def run(command, env, **kwargs):
    try:
        return subprocess.run(command, cwd=ROOT, env=env, check=True, **kwargs)
    except FileNotFoundError as error:
        raise ProjectError('Docker no esta disponible en PATH. Instala o inicia Docker y Docker Compose 2+.') from error
    except subprocess.CalledProcessError as error:
        raise ProjectError(f'Docker Compose termino con codigo {error.returncode}. Los volumenes se conservan.') from error


def backup(command, env, values):
    folder = ROOT / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    database = re.sub('[^A-Za-z0-9_-]', '_', values['POSTGRES_DB'])
    target = folder / f"{values['COMPOSE_PROJECT_NAME']}-{database}-{stamp}.dump"
    partial = target.with_suffix('.dump.part')
    # POSIX sh is inside the database image; no Bash or host shell is invoked.
    dump = ['exec', '-T', 'database', 'sh', '-c',
            'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom']
    created = False
    try:
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, 'wb') as stream:
            run(command + dump, env, stdout=stream)
        if partial.stat().st_size == 0:
            raise ProjectError('Respaldo vacio: no se publico el archivo incompleto.')
        if target.exists():
            raise ProjectError('Ya existe un respaldo con ese nombre; no se reemplazo.')
        partial.replace(target)
    except Exception:
        if created:
            partial.unlink(missing_ok=True)
        raise
    print(f'Respaldo creado: {target}')
    print('Comprobar restauracion por separado; este comando no modifica la base ni los volumenes.')
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'start', 'stop', 'status', 'logs', 'backup'))
    parser.add_argument('--environment', choices=('simulation', 'development', 'production'), default='simulation')
    parser.add_argument('--env-file', type=Path, help='Configuracion privada alternativa; no se sobrescribe')
    parser.add_argument('--profile', action='append', choices=('iot', 'lorawan', 'cloudflare', 'mirror'), default=[])
    parser.add_argument('--owner-email', help='Crear propietario de un entorno físico si no existe')
    parser.add_argument('--farm', help='Nombre del predio para ese nuevo propietario')
    parser.add_argument('--admin-email', help='Aprovisionar administrador V3 en producción con V3_ADMIN_PASSWORD')
    parser.add_argument('--domain', help='Dominio público de producción para un .env.pilot nuevo')
    args = parser.parse_args(argv)
    if args.domain:
        args.domain = args.domain.strip().lower()
        if args.environment != 'production' or args.action not in ('prepare', 'start'):
            parser.error('--domain requiere prepare o start en production')
        if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', args.domain) or args.domain in ('localhost', '127.0.0.1'):
            parser.error('Usa un dominio público sin esquema ni ruta, por ejemplo geocattle.example.com')
    if 'cloudflare' in args.profile and (args.environment != 'production' or not set(args.profile) <= {'cloudflare', 'mirror'}):
        parser.error('El perfil cloudflare usa production y se activa por separado de iot y lorawan')
    if 'mirror' in args.profile and 'cloudflare' not in args.profile:
        parser.error('El perfil mirror es el servidor espejo y requiere --profile cloudflare')
    if args.environment == 'production' and args.action != 'prepare' and 'cloudflare' not in args.profile:
        parser.error('El despliegue de production requiere --profile cloudflare')
    if bool(args.owner_email) != bool(args.farm):
        parser.error('--owner-email y --farm se usan juntos')
    if args.admin_email:
        args.admin_email = args.admin_email.strip().lower()
        if args.action != 'start' or args.environment != 'production':
            parser.error('--admin-email requiere start en production')
        if '@' not in args.admin_email or len(args.admin_email) > 254:
            parser.error('Usa un correo válido para el administrador V3')
    if args.owner_email:
        if args.action != 'start' or args.environment == 'simulation':
            parser.error('La creacion de propietario requiere start en development o production')
        args.owner_email = args.owner_email.strip().lower()
        args.farm = args.farm.strip()
        if '@' not in args.owner_email or len(args.owner_email) > 254 or not args.farm:
            parser.error('Indica un correo y nombre de predio validos')
        if args.owner_email == args.admin_email:
            parser.error('Usa correos distintos para el propietario y el administrador V3')
    try:
        if args.action in ('prepare', 'start'):
            path, values = prepare(args)
        else:
            path = config_path(args)
            values = read_config(path, args.environment)
        if args.action == 'prepare':
            return 0
        if args.action == 'start' and args.environment == 'production':
            validate_cloudflare(values)
            if 'mirror' in args.profile:
                validate_mirror(values)
                if args.admin_email or args.owner_email:
                    raise ProjectError('En el servidor espejo las cuentas llegan del PC; no uses --admin-email ni --owner-email.')
            if args.admin_email and len(values.get('V3_ADMIN_PASSWORD', '')) < 12:
                raise ProjectError('Configura V3_ADMIN_PASSWORD en el archivo privado para aprovisionar el administrador V3.')
        env = command_environment(values)
        run(['docker', 'compose', 'version'], env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        command = compose_command(args, path)
        if args.action == 'start':
            if args.environment == 'development':
                capture = Path(values.get('USB_CAPTURE_DIR', '.runtime/docker-capture'))
                (capture if capture.is_absolute() else ROOT / capture).mkdir(parents=True, exist_ok=True)
            print('Iniciando Docker; la primera descarga y compilacion puede tardar varios minutos.', flush=True)
            run(command + ['up', '-d', '--build', '--wait', '--wait-timeout', '180'], env)
            tools = command + ['--profile', 'tools', 'run', '--rm', '--no-deps']
            if args.environment == 'simulation':
                run(tools + ['seed'], env)
                run(tools + ['seed', 'python', '-m', 'geocattle.seed_v3'], env)
                print('Simulacion preparada. Acceso demo y contrasena: archivo privado seleccionado.')
            elif args.owner_email:
                run(tools + ['bootstrap', 'python', '-c', OWNER_BOOTSTRAP, args.owner_email, args.farm], env)
            elif 'mirror' in args.profile:
                print('Las cuentas de GeoCattle llegan del PC cuando el dueño ejecuta pc-connect.')
            elif not args.admin_email:
                print('No se crearon cuentas. Para preparar un propietario, usa --owner-email CORREO --farm "Nombre del predio".')
            if args.owner_email or args.admin_email:
                seed = tools + ['seed', 'python', '-m', 'geocattle.seed_v3']
                if args.admin_email:
                    seed += ['--admin-email', args.admin_email]
                run(seed, env)
            url = values['INVITATION_BASE_URL'] if args.environment == 'production' else f"http://localhost:{values.get('WEB_PORT', '8080')}"
            print(f'GeoCattle: {url}')
            if args.environment == 'development':
                print('La captura USB se inicia aparte en el anfitrion; no se cargan datos sinteticos.')
            if args.admin_email:
                print('El administrador V3 debe inscribir TOTP para acceder.')
            elif 'mirror' not in args.profile:
                print('Para aprovisionar el administrador V3 consulta la guía del entorno.')
        elif args.action == 'stop':
            run(command + ['down'], env)
            print('Contenedores detenidos. Volumenes y datos conservados.')
        elif args.action == 'status':
            run(command + ['ps'], env)
        elif args.action == 'logs':
            run(command + ['logs', '--tail', '100'], env)
        else:
            backup(command, env, values)
        return 0
    except (ProjectError, OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
