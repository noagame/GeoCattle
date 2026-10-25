#!/usr/bin/env python3
"""Docker Compose lifecycle for Windows and Linux, without a host shell.

Examples:
  python scripts/docker_project.py start
  python scripts/docker_project.py start --environment development
  python scripts/docker_project.py start --environment development --owner-email owner@example.local --farm "Mi predio"
The USB capture runs separately on the host. No action deletes Docker volumes.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
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
    path = args.env_file or Path('.env' if args.environment == 'simulation' else '.env.docker')
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


def prepare(args):
    path = config_path(args)
    overrides = DOCKER_ACADEMIC if args.environment == 'development' else None
    write_configuration(args.environment, path, overrides)
    values = read_config(path, args.environment)
    print(f'Configuracion Docker: {path}')
    return path, values


def command_environment(values):
    env = dict(os.environ)
    # Explicit CLI profiles/files and the selected private configuration win.
    for key in ('COMPOSE_PROFILES', 'COMPOSE_FILE', 'COMPOSE_ENV_FILES'):
        env.pop(key, None)
    env.update(values)
    return env


def compose_command(args, path):
    command = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(path),
               '-f', str(ROOT / 'compose.yaml')]
    if args.environment == 'development':
        command += ['-f', str(ROOT / 'compose.usb.yaml')]
    profiles = list(dict.fromkeys(args.profile))
    if 'lorawan' in profiles and 'iot' not in profiles:
        profiles.insert(0, 'iot')  # ChirpStack uses the local broker.
    for profile in profiles:
        command += ['--profile', profile]
    return command


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
    parser.add_argument('--environment', choices=('simulation', 'development'), default='simulation')
    parser.add_argument('--env-file', type=Path, help='Configuracion privada alternativa; no se sobrescribe')
    parser.add_argument('--profile', action='append', choices=('iot', 'lorawan'), default=[])
    parser.add_argument('--owner-email', help='Crear propietario de development si no existe')
    parser.add_argument('--farm', help='Nombre del predio para ese nuevo propietario')
    args = parser.parse_args(argv)
    if bool(args.owner_email) != bool(args.farm):
        parser.error('--owner-email y --farm se usan juntos')
    if args.owner_email:
        if args.action != 'start' or args.environment != 'development':
            parser.error('La creacion de propietario requiere start --environment development')
        args.owner_email = args.owner_email.strip().lower()
        args.farm = args.farm.strip()
        if '@' not in args.owner_email or len(args.owner_email) > 254 or not args.farm:
            parser.error('Indica un correo y nombre de predio validos')
    try:
        if args.action in ('prepare', 'start'):
            path, values = prepare(args)
        else:
            path = config_path(args)
            values = read_config(path, args.environment)
        if args.action == 'prepare':
            return 0
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
                run(tools + ['seed', 'python', '-m', 'geocattle.seed_v3'], env)
            else:
                print('No se crearon cuentas. Para preparar un propietario, repite start --environment development')
                print('con el mismo --env-file y las opciones --owner-email CORREO --farm "Nombre del predio".')
            print(f"GeoCattle: http://localhost:{values.get('WEB_PORT', '8080')}")
            if args.environment == 'development':
                print('La captura USB se inicia aparte en el anfitrion; no se cargan datos sinteticos.')
            print('El administrador V3 se provisiona por separado; consulta README.md. No se crea automaticamente.')
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
