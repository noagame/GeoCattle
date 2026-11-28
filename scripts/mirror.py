#!/usr/bin/env python3
"""Modo espejo: el PC del campo replica su base al servidor web (docs/planificacion/PLAN_MODO_ESPEJO.md).

PC del campo (Windows, prototipo nativo con .env.academic):
  python scripts/mirror.py pc-connect --ssh-jump usuario@servidor.example.org  # instala y verifica el espejo
  python scripts/mirror.py pc-setup --ssh-jump usuario@servidor.example.org    # solo SSH (recomendado)
  python scripts/mirror.py pc-setup --server-url https://geocattle.example.org --ssh-host espejo-ssh.example.org
  python scripts/mirror.py keygen
  python scripts/mirror.py pc-admin --email admin@example.org   # primer administrador de plataforma
  python scripts/mirror.py tunnel             # en primer plano; install-task lo deja al iniciar sesión
  python scripts/mirror.py install-task
  python scripts/mirror.py pc-status

Servidor (Debian, Docker, .env.pilot):
  python3 scripts/mirror.py server-init
  python3 scripts/mirror.py authorize id_ed25519.pub --host-account   # con --ssh-jump en el PC
  python3 scripts/mirror.py subscribe --pc-database geocattle_academic
  python3 scripts/mirror.py status
  python3 scripts/mirror.py refresh           # tras migrar servidor y PC
  python3 scripts/mirror.py resync            # tras un corte mayor al tope de WAL

Las claves se piden en consola sin eco y se guardan solo en el archivo privado de cada lado.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
from geocattle import mirror_tables  # noqa: E402

RUNTIME = ROOT / '.runtime' / 'espejo'
PC_ENV = ROOT / '.env.academic'
SERVER_ENV = ROOT / '.env.pilot'
KEY = RUNTIME / 'id_ed25519'
SLOT = mirror_tables.SUBSCRIPTION
PG_HOME = ROOT / '.runtime/postgres16/pgsql'
PG_DATA = ROOT / '.runtime/pgdata-academic'
DB_PORT_REMOTE = 15432
WEB_PORT_REMOTE = 18084
# Modo solo SSH: el PC entra con la cuenta del servidor y salta a espejo-ssh por su IP fija de Docker
# (compose.mirror.yaml), sin publicar puertos. La bandeja web vuelve al PC por un reenvío local.
ESPEJO_IP = '172.30.248.19'
INBOX_LOCAL_PORT = 18095
INBOX_TARGET = 'web:80'
JUMP_LOCAL_PORT = 18022
JUMP = re.compile(r'^([a-z_][a-z0-9_.-]{0,31})@([A-Za-z0-9][A-Za-z0-9.-]{0,252})(?::(\d{1,5}))?$')
WAL_KEEP = '2GB'
PUBKEY = re.compile(r'^ssh-ed25519 [A-Za-z0-9+/]{68}(?:={0,2})(?: [^\r\n]{0,100})?$')
HOST = re.compile(r'^[a-z0-9-]+(?:\.[a-z0-9-]+)+$')
DB_NAME = re.compile(r'^[a-z_][a-z0-9_]{0,62}$')
TASK_NAME = 'GeoCattle Espejo'
PRIVATE_SQL = ("SET log_statement = 'none';\nSET log_min_error_statement = 'panic';\n"
               "SET log_min_messages = 'panic';\n"
               'SET log_duration = off;\nSET log_min_duration_statement = -1;\n'
               'SET log_min_duration_sample = -1;\n')


class MirrorError(RuntimeError):
    pass


# ------------------------------------------------------------------ archivos privados
def read_env(path):
    if not path.is_file():
        raise MirrorError(f'Falta el archivo privado {path}.')
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        values[key.strip()] = value
    return values


def add_missing(path, additions):
    """Agrega claves ausentes al final del archivo privado; nunca reemplaza un valor existente."""
    current = read_env(path)
    missing = {key: value for key, value in additions.items() if key not in current}
    if not missing:
        return []
    text = path.read_text(encoding='utf-8-sig')
    lines = [] if text.endswith('\n') or not text else ['']
    lines += ['', '# Modo espejo (scripts/mirror.py)'] + [f'{key}={value}' for key, value in missing.items()]
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(lines) + '\n')
    return sorted(missing)


def ask_secret(label, minimum=32):
    value = getpass.getpass(f'{label}: ').strip()
    if len(value) < minimum:
        raise MirrorError(f'{label} debe tener al menos {minimum} caracteres.')
    return value


def set_env_values(path, updates):
    current = read_env(path)
    changes = {key: value for key, value in updates.items() if current.get(key) != value}
    if not changes:
        return []
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    for index, line in enumerate(lines):
        key = line.partition('=')[0].strip()
        if key in changes:
            lines[index] = f'{key}={changes[key]}'
    if missing := changes.keys() - current.keys():
        lines += ['', '# Modo espejo (scripts/mirror.py)']
        lines += [f'{key}={changes[key]}' for key in sorted(missing)]
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write('\n'.join(lines) + '\n')
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return sorted(changes)


def checked_secret(value, label, minimum=32):
    if not isinstance(value, str) or len(value.strip()) < minimum or any(c in value for c in '\r\n\0'):
        raise MirrorError(f'{label} requiere al menos {minimum} caracteres en una sola línea.')
    return value


# ------------------------------------------------------------------ SQL compartido
def quote_ident(name):
    if not re.fullmatch(r'[a-z_][a-z0-9_]*', name):
        raise MirrorError(f'Identificador inválido: {name}')
    return name


def quote_literal(value):
    return "'" + value.replace("'", "''") + "'"


def table_list():
    return ', '.join(quote_ident(name) for name in mirror_tables.mirror_tables())


def publication_sql(exists):
    verb = 'ALTER PUBLICATION {} SET TABLE {}' if exists else 'CREATE PUBLICATION {} FOR TABLE {}'
    return verb.format(quote_ident(mirror_tables.PUBLICATION), table_list())


def grants_sql(database):
    role = quote_ident(mirror_tables.REPLICA_ROLE)
    return [f'GRANT CONNECT ON DATABASE {quote_ident(database)} TO {role}',
            f'GRANT USAGE ON SCHEMA public TO {role}',
            f'GRANT SELECT ON {table_list()}, schema_migrations TO {role}']


def conninfo(database, password, host='espejo-ssh', port=DB_PORT_REMOTE):
    def part(value):
        return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"
    return (f'host={host} port={port} dbname={part(database)} user={mirror_tables.REPLICA_ROLE} '
            f'password={part(password)} connect_timeout=10 keepalives_idle=30')


def subscription_sql(database, password):
    return (f'CREATE SUBSCRIPTION {quote_ident(mirror_tables.SUBSCRIPTION)} '
            f'CONNECTION {quote_literal(conninfo(database, password))} '
            f'PUBLICATION {quote_ident(mirror_tables.PUBLICATION)} '
            'WITH (copy_data = true, disable_on_error = false, slot_name = '
            f'{quote_literal(SLOT)})')


# ------------------------------------------------------------------ PC del campo
def pc_connect(values):
    import psycopg
    return psycopg.connect(host='127.0.0.1', port=int(values['DB_PORT']), dbname=values['POSTGRES_DB'],
                           user=values['POSTGRES_USER'], password=values['POSTGRES_PASSWORD'],
                           autocommit=True, connect_timeout=5)


def restart_native(path, values):
    # Solo la base nativa que describe .env.academic; otra configuración se reinicia a mano.
    if path.resolve() != PC_ENV.resolve() or not (PG_HOME / 'bin/pg_ctl.exe').exists() \
            or not (PG_DATA / 'PG_VERSION').exists():
        return False
    port = int(values['DB_PORT'])
    subprocess.run([str(PG_HOME / 'bin/pg_ctl.exe'), '-D', str(PG_DATA), '-l',
                    str(ROOT / '.runtime/postgres-academic.log'), '-o', f'-p {port} -h 127.0.0.1',
                    '-w', '-m', 'fast', 'restart'], check=True)
    return True


def pc_setup(args, *, sync_key=None):
    path = args.env_file or PC_ENV
    values = read_env(path)
    for key in ('DB_PORT', 'POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD'):
        if not values.get(key):
            raise MirrorError(f'{path.name} no define {key}.')
    if sync_key is not None:
        if values.get('MIRROR_MODE') == 'replica' or values.get('APP_ENV') == 'production':
            raise MirrorError('Usa el archivo privado del PC del campo para pc-connect.')
        if values.get('MIRROR_SYNC_KEY') not in (None, '', sync_key):
            raise MirrorError(f'{path.name} ya pertenece a otro espejo (MIRROR_SYNC_KEY distinta).')
        if not DB_NAME.fullmatch(values['POSTGRES_DB']):
            raise MirrorError('POSTGRES_DB del PC tiene un nombre inválido.')
        checked_secret(values.get('MFA_ENCRYPTION_KEY') or values.get('SESSION_SECRET'), 'MFA_ENCRYPTION_KEY del PC')
        if values.get('MIRROR_REPLICA_PASSWORD'):
            checked_secret(values['MIRROR_REPLICA_PASSWORD'], 'MIRROR_REPLICA_PASSWORD del PC', 20)
    with pc_connect(values) as db:
        if db.execute('SHOW wal_level').fetchone()[0] != 'logical':
            db.execute("ALTER SYSTEM SET wal_level = 'logical'")
            db.execute(f"ALTER SYSTEM SET max_slot_wal_keep_size = '{WAL_KEEP}'")
            pending_restart = True
        else:
            db.execute(f"ALTER SYSTEM SET max_slot_wal_keep_size = '{WAL_KEEP}'")
            db.execute('SELECT pg_reload_conf()')
            pending_restart = False
    if pending_restart:
        if args.no_restart or not restart_native(path, values):
            print('PostgreSQL necesita reiniciarse para activar wal_level=logical. '
                  'Reinicia la base y repite el mismo comando.')
            return 2
        print('PostgreSQL reiniciado con replicación lógica.')
    additions = {'MIRROR_MODE': 'field'}
    if not values.get('MFA_ENCRYPTION_KEY') and values.get('SESSION_SECRET'):
        # Misma materia que el respaldo actual (SESSION_SECRET): los factores TOTP siguen válidos.
        additions['MFA_ENCRYPTION_KEY'] = values['SESSION_SECRET']
    if not values.get('MIRROR_REPLICA_PASSWORD'):
        additions['MIRROR_REPLICA_PASSWORD'] = secrets.token_urlsafe(30)
    if args.server_url:
        if not re.fullmatch(r'https://[a-z0-9-]+(?:\.[a-z0-9-]+)+', args.server_url):
            raise MirrorError('--server-url debe ser https://DOMINIO, sin ruta.')
        additions['MIRROR_SERVER_URL'] = args.server_url
    if args.ssh_jump:
        if not JUMP.fullmatch(args.ssh_jump):
            raise MirrorError('--ssh-jump debe ser USUARIO@SERVIDOR o USUARIO@SERVIDOR:PUERTO.')
        additions['MIRROR_SSH_JUMP'] = args.ssh_jump
        if not args.server_url:
            # La bandeja del servidor llega por el mismo túnel SSH (reenvío local hacia web:80).
            additions['MIRROR_SERVER_URL'] = f'http://127.0.0.1:{INBOX_LOCAL_PORT}'
    if args.ssh_host:
        if not HOST.fullmatch(args.ssh_host):
            raise MirrorError('--ssh-host debe ser un nombre DNS, por ejemplo espejo-ssh.example.org.')
        additions['MIRROR_SSH_HOST'] = args.ssh_host
    if sync_key is not None:
        additions['MIRROR_SYNC_KEY'] = sync_key
    elif 'MIRROR_SYNC_KEY' not in values and not args.skip_secrets:
        additions['MIRROR_SYNC_KEY'] = ask_secret('MIRROR_SYNC_KEY del servidor (archivo .env.pilot)')
    if 'MIRROR_SSH_ACCESS_ID' not in values and args.ssh_host and not args.skip_secrets:
        print('Token de servicio de Cloudflare Access para el hostname SSH (Enter vacío si no usa Access).')
        token_id = getpass.getpass('Client ID: ').strip()
        if token_id:
            additions['MIRROR_SSH_ACCESS_ID'] = token_id
            additions['MIRROR_SSH_ACCESS_SECRET'] = ask_secret('Client Secret', 16)
    added = set_env_values(path, additions) if sync_key is not None else add_missing(path, additions)
    values = read_env(path)
    role = quote_ident(mirror_tables.REPLICA_ROLE)
    with pc_connect(values) as db:
        for statement in PRIVATE_SQL.splitlines():
            db.execute(statement)
        exists = db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (mirror_tables.REPLICA_ROLE,)).fetchone()
        verb = 'ALTER' if exists else 'CREATE'
        db.execute(f'{verb} ROLE {role} WITH LOGIN REPLICATION NOSUPERUSER NOCREATEDB NOCREATEROLE '
                   f'PASSWORD {quote_literal(values["MIRROR_REPLICA_PASSWORD"])}')
        for statement in grants_sql(values['POSTGRES_DB']):
            db.execute(statement)
        published = db.execute('SELECT 1 FROM pg_publication WHERE pubname=%s',
                               (mirror_tables.PUBLICATION,)).fetchone()
        db.execute(publication_sql(bool(published)))
        count = db.execute('SELECT count(*) FROM pg_publication_tables WHERE pubname=%s',
                           (mirror_tables.PUBLICATION,)).fetchone()[0]
    if added:
        print(f'Agregado a {path.name}: {", ".join(added)}')
    print(f'Publicación {mirror_tables.PUBLICATION}: {count} tablas. Rol {mirror_tables.REPLICA_ROLE} listo.')
    if sync_key is not None:
        return 0
    print('Reinicia GeoCattle (Abrir-GeoCattle.cmd) para que el worker entre en modo campo.')
    print(f'En el servidor: python3 scripts/mirror.py subscribe --pc-database {values["POSTGRES_DB"]}')
    print(f'La clave de réplica está en MIRROR_REPLICA_PASSWORD de {path.name}; se pide allí sin eco.')
    print(f'Copia también MFA_ENCRYPTION_KEY de {path.name} al servidor (server-init la pide): '
          'sin ella el TOTP de las cuentas no funciona en la web.')
    return 0


def pc_status(args):
    values = read_env(args.env_file or PC_ENV)
    with pc_connect(values) as db:
        level = db.execute('SHOW wal_level').fetchone()[0]
        slot = db.execute("""SELECT active, wal_status,
                pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots
                WHERE slot_name=%s""", (SLOT,)).fetchone()
        tables = db.execute('SELECT count(*) FROM pg_publication_tables WHERE pubname=%s',
                            (mirror_tables.PUBLICATION,)).fetchone()[0]
        beat = db.execute('SELECT max(at) FROM mirror_heartbeat').fetchone()[0] if db.execute(
            "SELECT to_regclass('mirror_heartbeat')").fetchone()[0] else None
    print(f'wal_level={level} tablas publicadas={tables} pulso={beat or "sin pulso"}')
    if slot:
        print(f'slot {SLOT}: {"conectado" if slot[0] else "desconectado"}, estado WAL {slot[1]}, retenido {slot[2]}')
    else:
        print(f'Sin slot {SLOT}: el servidor aún no se suscribe.')
    return 0


def admin_command(values, email, name, promote=False):
    # Las cuentas se crean solo en el PC: el espejo las recibe por la réplica (el servidor no escribe).
    from sqlalchemy import URL
    url = URL.create('postgresql+psycopg', username=values['POSTGRES_USER'], password=values['POSTGRES_PASSWORD'],
                     host='127.0.0.1', port=int(values['DB_PORT']), database=values['POSTGRES_DB'])
    env = {**os.environ, **values, 'DATABASE_URL': url.render_as_string(hide_password=False),
           'PYTHONPATH': str(ROOT / 'backend'), 'PYTHONUTF8': '1'}
    command = [sys.executable, '-m', 'geocattle.seed_v3', '--admin-email', email, '--admin-name', name]
    return command + ['--promote'] * promote, env


def pc_admin(args):
    values = read_env(args.env_file or PC_ENV)
    if values.get('MIRROR_MODE', 'off') == 'replica':
        raise MirrorError('En el servidor espejo no se crean cuentas: ejecuta pc-admin en el PC del campo.')
    email = args.email.strip().lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email) or len(email) > 254:
        raise MirrorError('--email debe ser un correo válido.')
    try:
        pc_connect(values).close()
    except Exception as error:  # psycopg.OperationalError sin importar psycopg aquí
        raise MirrorError('La base del PC está apagada: abre GeoCattle con Abrir-GeoCattle.cmd y repite pc-admin. '
                          'No se creó ninguna cuenta.') from error
    command, env = admin_command(values, email, args.name, args.promote)
    if args.promote:
        # La cuenta conserva su contraseña: no se pide ni se cambia.
        if not args.yes and input(f'¿Elevar {email} a administrador de plataforma? Escribe SI: ').strip().upper() != 'SI':
            raise MirrorError('Cancelado; no se cambió nada.')
    else:
        password = os.environ.get('V3_ADMIN_PASSWORD', '')
        if not password:
            password = getpass.getpass('Contraseña del administrador (12+ caracteres): ')
            if getpass.getpass('Repite la contraseña: ') != password:
                raise MirrorError('Las contraseñas no coinciden.')
        if len(password) < 12:
            raise MirrorError('La contraseña requiere al menos 12 caracteres.')
        env['V3_ADMIN_PASSWORD'] = password
    if subprocess.run(command, cwd=ROOT, env=env).returncode:
        raise MirrorError('No se creó ni se cambió el administrador (motivo arriba).')
    print('Entra a GeoCattle en el PC con ese correo y activa la doble verificación en Mi perfil. '
          'Con el túnel activo la cuenta llega al espejo y sirve igual en la web.')
    return 0


def pc_drop_slot(args):
    values = read_env(args.env_file or PC_ENV)
    with pc_connect(values) as db:
        row = db.execute('SELECT active FROM pg_replication_slots WHERE slot_name=%s', (SLOT,)).fetchone()
        if not row:
            print('No hay slot que retirar.')
            return 0
        if row[0]:
            raise MirrorError('El slot está en uso; desactiva primero la suscripción del servidor.')
        db.execute('SELECT pg_drop_replication_slot(%s)', (SLOT,))
    print(f'Slot {SLOT} retirado. El servidor necesita resync.')
    return 0


def protect_key():
    """OpenSSH de Windows rechaza llaves que heredan permisos de la carpeta (p. ej. OneDrive)."""
    if os.name == 'nt' and KEY.exists():
        user = os.environ.get('USERNAME') or getpass.getuser()
        subprocess.run(['icacls', str(KEY), '/inheritance:r', '/grant:r', f'{user}:F'],
                       check=True, stdout=subprocess.DEVNULL)


def keygen(args):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if KEY.exists():
        print(f'Ya existe {KEY}; se conserva.')
    else:
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'geocattle-campo', '-f', str(KEY)],
                       check=True)
    protect_key()
    public_key = KEY.with_suffix('.pub')
    if not public_key.exists():
        # Un corte puede dejar la llave privada lista antes de guardar su parte pública.
        recovered = subprocess.run(['ssh-keygen', '-y', '-f', str(KEY)], check=True,
                                   stdin=subprocess.DEVNULL, capture_output=True, encoding='utf-8').stdout.strip()
        if not PUBKEY.fullmatch(recovered):
            raise MirrorError('La llave privada del túnel debe ser Ed25519.')
        public_key.write_text(recovered + '\n', encoding='utf-8')
    if not getattr(args, 'quiet', False):
        print('Copia esta línea al servidor y autorízala con: python3 scripts/mirror.py authorize ARCHIVO.pub')
        print(public_key.read_text(encoding='utf-8').strip())
    return 0


def ssh_host_options(known_hosts=None):
    # Huellas fijadas: la primera conexión las registra y después un cambio de llave se rechaza.
    path = known_hosts or RUNTIME / 'known_hosts'
    return ['-o', f'UserKnownHostsFile="{path.as_posix()}"', '-o', 'StrictHostKeyChecking=accept-new']


def jump_parts(jump):
    match = JUMP.fullmatch(jump or '')
    if not match:
        raise MirrorError('MIRROR_SSH_JUMP debe ser USUARIO@SERVIDOR o USUARIO@SERVIDOR:PUERTO.')
    port = int(match.group(3) or 22)
    if not 1 <= port <= 65535:
        raise MirrorError('El puerto de MIRROR_SSH_JUMP debe estar entre 1 y 65535.')
    return match.group(1), match.group(2), port


def jump_command(values, known_hosts=None):
    # Primer tramo: tu cuenta SSH del servidor, solo para reenviar hacia espejo-ssh (IP fija de Docker).
    user, host, port = jump_parts(values.get('MIRROR_SSH_JUMP'))
    return ['ssh', '-F', 'none', '-N', '-T', '-i', str(KEY), '-o', 'IdentitiesOnly=yes',
            *ssh_host_options(known_hosts),
            '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-o', 'BatchMode=yes', '-L', f'127.0.0.1:{JUMP_LOCAL_PORT}:{ESPEJO_IP}:22',
            '-p', str(port), f'{user}@{host}']


def tunnel_command(values, direct=None, cloudflared='cloudflared', known_hosts=None):
    if not KEY.exists():
        raise MirrorError('Falta la llave del PC. Ejecuta: python scripts/mirror.py keygen')
    host = values.get('MIRROR_SSH_HOST', '')
    jump = values.get('MIRROR_SSH_JUMP', '')
    command = ['ssh', '-F', 'none', '-N', '-T', '-i', str(KEY), '-o', 'IdentitiesOnly=yes',
               *ssh_host_options(known_hosts),
               '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
               '-o', 'BatchMode=yes',
               '-R', f'0.0.0.0:{DB_PORT_REMOTE}:127.0.0.1:{int(values["DB_PORT"])}']
    if values.get('MIRROR_SUPPORT', 'true').lower() != 'false':
        command += ['-R', f'0.0.0.0:{WEB_PORT_REMOTE}:127.0.0.1:8084']
    if direct or jump:
        command += ['-L', f'127.0.0.1:{INBOX_LOCAL_PORT}:{INBOX_TARGET}']
    if direct:
        address, _, port = direct.rpartition(':')
        command += ['-p', str(int(port)), f'espejo@{address}']
    elif jump:
        # Segundo tramo: espejo-ssh a través del reenvío del primero; la huella se fija con un alias estable.
        _, server, port = jump_parts(jump)
        command += ['-o', f'HostKeyAlias=espejo-ssh.{server}.{port}', '-p', str(JUMP_LOCAL_PORT), 'espejo@127.0.0.1']
    else:
        if not HOST.fullmatch(host):
            raise MirrorError('Configura MIRROR_SSH_HOST en el archivo privado (pc-setup --ssh-host).')
        command += ['-o', f'ProxyCommand="{cloudflared}" access ssh --hostname %h', f'espejo@{host}']
    return command


def tunnel(args):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(RUNTIME / 'tunel.lock') as acquired:
        if not acquired:
            print('Ya hay un túnel del espejo en ejecución en este PC.')
            return 0
        return maintain_tunnel(args)


@contextmanager
def exclusive_lock(path):
    with path.open('a+b') as stream:
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        except OSError as error:
            if os.name != 'nt' or error.errno != 13:  # ERROR_LOCK_VIOLATION se traduce a EACCES.
                raise
            yield False
        else:
            yield True


def maintain_tunnel(args):
    path = args.env_file or PC_ENV
    values = read_env(path)
    cloudflared = Path(values.get('MIRROR_CLOUDFLARED') or shutil.which('cloudflared') or 'cloudflared').as_posix()
    command = tunnel_command(values, args.direct, cloudflared, args.known_hosts)
    env = {**os.environ}
    if values.get('MIRROR_SSH_ACCESS_ID'):
        env['TUNNEL_SERVICE_TOKEN_ID'] = values['MIRROR_SSH_ACCESS_ID']
        env['TUNNEL_SERVICE_TOKEN_SECRET'] = values.get('MIRROR_SSH_ACCESS_SECRET', '')
    protect_key()
    delay = 5
    while True:
        started = time.monotonic()
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')
        print(f'{stamp} túnel: conectando', flush=True)
        try:
            code = run_tunnel(command, env, values if not args.direct else {}, args.known_hosts)
        except FileNotFoundError as error:
            raise MirrorError('No se encontró ssh o cloudflared en PATH.') from error
        except KeyboardInterrupt:
            return 0
        if args.once:
            return code
        delay = 5 if time.monotonic() - started > 120 else min(delay * 2, 30)
        print(f'túnel: cerrado (código {code}); reintento en {delay} s', flush=True)
        time.sleep(delay)


def wait_port(port, process, timeout=30):
    import socket
    end = time.monotonic() + timeout
    while time.monotonic() < end and process.poll() is None:
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.5)
    return False


def run_tunnel(command, env, values, known_hosts=None):
    if not values.get('MIRROR_SSH_JUMP'):
        return subprocess.run(command, env=env).returncode
    jump = subprocess.Popen(jump_command(values, known_hosts), env=env)
    try:
        if not wait_port(JUMP_LOCAL_PORT, jump):
            print('túnel: el servidor no aceptó el primer tramo SSH (cuenta, llave o reenvío)', flush=True)
            return jump.poll() if jump.poll() is not None else 255
        return subprocess.run(command, env=env).returncode
    finally:
        if jump.poll() is None:
            jump.terminate()
            try:
                jump.wait(10)
            except subprocess.TimeoutExpired:
                jump.kill()


def tunnel_arguments(args):
    command = ['-u', str(ROOT / 'scripts/mirror.py'), 'tunnel']
    if args.env_file:
        command += ['--env-file', str(args.env_file.resolve())]
    if args.known_hosts:
        command += ['--known-hosts', str(args.known_hosts.resolve())]
    return command


def install_task(args):
    if os.name != 'nt':
        raise MirrorError('install-task es para el PC Windows del campo.')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    script = RUNTIME / 'tunel.cmd'
    python = ROOT / '.venv/Scripts/pythonw.exe'
    if not python.exists():
        python = Path(sys.executable)
    invocation = ' '.join(f'"{part}"' for part in [str(python), *tunnel_arguments(args)])
    script.write_text(f'@echo off\ncd /d "{ROOT}"\n{invocation} >> "{RUNTIME / "tunel.log"}" 2>&1\n',
                      encoding='utf-8', newline='\r\n')
    subprocess.run(['schtasks', '/Create', '/F', '/TN', TASK_NAME, '/SC', 'ONLOGON', '/RL', 'LIMITED',
                    '/TR', f'"{script}"'], check=True)
    print('Tarea "GeoCattle Espejo" creada: abre el túnel al iniciar sesión. Registro en .runtime/espejo/tunel.log')
    print('Para iniciarla ahora: schtasks /Run /TN "GeoCattle Espejo"')
    return 0


# ------------------------------------------------------------------ servidor
def compose(args):
    import docker_project
    path = (args.env_file or SERVER_ENV).resolve()
    values = docker_project.read_config(path, 'production')
    ns = argparse.Namespace(environment='production', profile=['cloudflare', 'mirror'])
    command = docker_project.compose_command(ns, path)
    for extra in args.compose_file or []:
        command += ['-f', str(Path(extra).resolve())]
    return command, docker_project.command_environment(values), values


def psql(args, sql, *, remote_password=None, remote_db=None, check=True):
    command, env, _ = compose(args)
    inner = 'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    extra = []
    if remote_password is not None:
        env = {**env, 'PGPASSWORD': remote_password}
        extra = ['-e', 'PGPASSWORD']
        inner = (f'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -h espejo-ssh -p {DB_PORT_REMOTE} '
                 f'-U {mirror_tables.REPLICA_ROLE} -d {remote_db}')
    result = subprocess.run(command + ['exec', '-T', *extra, 'database', 'sh', '-c', inner], cwd=ROOT, env=env,
                            input=sql, text=True, capture_output=True, encoding='utf-8')
    if check and result.returncode:
        raise MirrorError((result.stderr or result.stdout).strip() or 'psql falló')
    return result.stdout.strip()


def server_init(args):
    path = args.env_file or SERVER_ENV
    additions = {'MIRROR_SYNC_KEY': secrets.token_urlsafe(36), 'MIRROR_SOURCE_ENVIRONMENT': 'development'}
    current = read_env(path)
    added = []
    if not args.skip_secrets:
        # Los secretos TOTP llegan cifrados desde el PC: el servidor usa la misma clave.
        label = 'MFA_ENCRYPTION_KEY del PC (archivo .env.academic)'
        value = os.environ.get('MIRROR_PC_MFA_KEY')
        if value is not None or not current.get('MFA_ENCRYPTION_KEY'):
            key = checked_secret(value, label) if value is not None else ask_secret(label)
            added = set_env_values(path, {'MFA_ENCRYPTION_KEY': key})
        elif not getattr(args, 'managed', False):
            print('MFA_ENCRYPTION_KEY ya existe en el servidor: debe ser igual a la del PC.')
    added += add_missing(path, additions)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    keys = RUNTIME / 'authorized_keys'
    if not keys.exists():
        keys.write_text('', encoding='utf-8')
    os.chmod(keys, 0o644)
    if added:
        print(f'Agregado a {path.name}: {", ".join(added)}')
    if not getattr(args, 'managed', False):
        print('Arranca con: python3 scripts/docker_project.py start --environment production '
              '--profile cloudflare --profile mirror')
    return 0


def authorize(args, *, line=None):
    if line is None:
        line = (sys.stdin.read() if args.pubkey == '-' else Path(args.pubkey).read_text(encoding='utf-8')).strip()
    if not PUBKEY.fullmatch(line):
        raise MirrorError('Se espera una sola línea ssh-ed25519 (id_ed25519.pub del PC).')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    restricted = (f'restrict,port-forwarding,permitlisten="0.0.0.0:{DB_PORT_REMOTE}",'
                  f'permitlisten="0.0.0.0:{WEB_PORT_REMOTE}",permitopen="{INBOX_TARGET}" {line}\n')
    if args.host_account:
        print(authorize_host_account(line, args.host_keys or Path.home() / '.ssh' / 'authorized_keys'))
    keys = RUNTIME / 'authorized_keys'
    pending = RUNTIME / 'espejo-ssh-restart.pending'
    if not keys.exists() or keys.read_text(encoding='utf-8') != restricted:
        pending.touch()
        keys.write_text(restricted, encoding='utf-8')
        os.chmod(keys, 0o644)
    if not pending.exists():
        print('Llave del túnel ya autorizada en espejo-ssh.')
        return 0
    command, env, _ = compose(args)
    subprocess.run(command + ['restart', 'espejo-ssh'], cwd=ROOT, env=env, check=True)
    pending.unlink()
    print('Clave del PC autorizada solo para reenvío. espejo-ssh reiniciado.')
    return 0


def replica_password(args):
    value = os.environ.get('MIRROR_REPLICA_PASSWORD')
    return value or ask_secret('MIRROR_REPLICA_PASSWORD del PC (archivo .env.academic)', 20)


def versions(text):
    return [item for item in text.split(',') if item]


def wait_sync(args, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = psql(args, "SELECT count(*) FILTER (WHERE srsubstate <> 'r') || '/' || count(*) "
                           'FROM pg_subscription_rel')
        pending, total = (int(x) for x in (state or '0/0').split('/'))
        if total and not pending:
            print(f'Copia inicial terminada: {total} tablas sincronizadas.')
            return
        print(f'Copiando: {total - pending}/{total} tablas listas...', flush=True)
        time.sleep(5)
    raise MirrorError('La copia inicial no terminó a tiempo; revisa: python3 scripts/mirror.py status')


def subscription_exists(args):
    return bool(psql(args, f"SELECT 1 FROM pg_subscription WHERE subname='{mirror_tables.SUBSCRIPTION}' "
                           'AND subdbid = (SELECT oid FROM pg_database WHERE datname = current_database())'))


def pc_reachable(args):
    command, env, _ = compose(args)
    probe = subprocess.run(command + ['exec', '-T', 'database', 'pg_isready', '-h', 'espejo-ssh', '-p',
                                     str(DB_PORT_REMOTE)], cwd=ROOT, env=env, capture_output=True)
    return probe.returncode == 0


def subscribe(args):
    if not DB_NAME.fullmatch(args.pc_database):
        raise MirrorError('--pc-database debe ser el POSTGRES_DB del PC.')
    if subscription_exists(args):
        raise MirrorError('La suscripción ya existe. Usa status, refresh o resync.')
    password = replica_password(args)
    if not pc_reachable(args):
        raise MirrorError('El PC no responde por el túnel. Revisa la tarea "GeoCattle Espejo" en el PC.')
    remote = versions(psql(args, "SELECT string_agg(version, ',' ORDER BY version) FROM schema_migrations",
                           remote_password=password, remote_db=args.pc_database))
    local = versions(psql(args, "SELECT string_agg(version, ',' ORDER BY version) FROM schema_migrations"))
    if remote != local:
        raise MirrorError(f'Migraciones distintas (servidor {local[-1:] or "-"}, PC {remote[-1:] or "-"}). '
                          'Actualiza ambos lados con la misma versión de GeoCattle.')
    if not args.yes:
        answer = input('Se vaciarán las tablas espejo del servidor y se copiará la base del PC. ¿Continuar? [s/N] ')
        if answer.strip().lower() not in ('s', 'si', 'sí'):
            print('Sin cambios.')
            return 1
    if not args.no_backup:
        import docker_project
        command, env, values = compose(args)
        docker_project.backup(command, env, values)
    psql(args, f'TRUNCATE TABLE {table_list()} CASCADE;')
    try:
        psql(args, PRIVATE_SQL + subscription_sql(args.pc_database, password) + ';')
    except MirrorError as error:
        raise MirrorError('PostgreSQL no pudo crear la suscripción. Revisa el estado y el registro de la base.') from error
    print('Suscripción creada. Copiando la base del PC...')
    wait_sync(args)
    return status(args)


def status(args):
    rows = psql(args, f"""SELECT s.subenabled, coalesce(st.received_lsn::text, '-'),
        coalesce(to_char(st.latest_end_time, 'YYYY-MM-DD HH24:MI:SS TZ'), '-'),
        coalesce(extract(epoch FROM now() - st.latest_end_time)::int::text, '-')
        FROM pg_subscription s LEFT JOIN pg_stat_subscription st ON st.subid = s.oid AND st.relid IS NULL
        WHERE s.subname = '{mirror_tables.SUBSCRIPTION}'
          AND s.subdbid = (SELECT oid FROM pg_database WHERE datname = current_database())""")
    if not rows:
        print('Sin suscripción. Ejecuta subscribe.')
        return 1
    enabled, lsn, last, lag = rows.splitlines()[0].split('|')
    errors = psql(args, f"""SELECT coalesce(apply_error_count, 0) || '|' || coalesce(sync_error_count, 0)
        FROM pg_stat_subscription_stats WHERE subname = '{mirror_tables.SUBSCRIPTION}'""") or '0|0'
    beat = psql(args, "SELECT coalesce(to_char(max(at), 'YYYY-MM-DD HH24:MI:SS TZ') || ' (hace ' || "
                      "extract(epoch FROM now() - max(at))::int || ' s)', 'sin pulso') FROM mirror_heartbeat")
    print(f'Suscripción: {"activa" if enabled == "t" else "DETENIDA"}')
    print(f'Último mensaje del PC: {last} (hace {lag} s), LSN {lsn}')
    print(f'Errores aplicar/copiar: {errors.replace("|", "/")}. Pulso del campo: {beat}')
    if enabled != 't':
        print('Revisa el registro con docker compose logs database; tras corregir: python3 scripts/mirror.py enable')
    return 0 if enabled == 't' else 2


def refresh(args):
    psql(args, f'ALTER SUBSCRIPTION {mirror_tables.SUBSCRIPTION} REFRESH PUBLICATION WITH (copy_data = true);')
    psql(args, f'ALTER SUBSCRIPTION {mirror_tables.SUBSCRIPTION} ENABLE;')
    print('Publicación refrescada y suscripción activa.')
    return status(args)


def enable(args):
    psql(args, f'ALTER SUBSCRIPTION {mirror_tables.SUBSCRIPTION} ENABLE;')
    return status(args)


def resync(args):
    if not args.yes:
        answer = input('Se eliminará la suscripción y se copiará de nuevo toda la base del PC. ¿Continuar? [s/N] ')
        if answer.strip().lower() not in ('s', 'si', 'sí'):
            print('Sin cambios.')
            return 1
    name = mirror_tables.SUBSCRIPTION
    if psql(args, f"SELECT 1 FROM pg_subscription WHERE subname='{name}'"):
        psql(args, f'ALTER SUBSCRIPTION {name} DISABLE;')
        dropped = subprocess.run(compose(args)[0] + ['exec', '-T', 'database', 'sh', '-c',
                                 f'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
                                 f'-c "DROP SUBSCRIPTION {name}"'],
                                 cwd=ROOT, env=compose(args)[1], capture_output=True, text=True)
        if dropped.returncode:
            psql(args, f'ALTER SUBSCRIPTION {name} SET (slot_name = NONE);')
            psql(args, f'DROP SUBSCRIPTION {name};')
            print('El PC no respondió: su slot quedó huérfano. En el PC ejecuta: python scripts/mirror.py pc-drop-slot')
    args.yes = True
    return subscribe(args)


# ------------------------------------------------------------------ conexión desde el PC
def remote_command(args, action, payload=None):
    user, host, port = jump_parts(args.ssh_jump)
    command = ['ssh', '-a', '-x', '-T', *ssh_host_options(args.known_hosts), '-o', 'BatchMode=yes',
               '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=3', '-p', str(port)]
    if args.identity_file:
        command += ['-i', str(args.identity_file.resolve()), '-o', 'IdentitiesOnly=yes']
    remote = f'cd -- {shlex.quote(args.server_dir)} && exec python3 -u scripts/mirror.py pc-remote {action}'
    result = subprocess.run([*command, f'{user}@{host}', remote], input=json.dumps(payload or {}),
                            encoding='utf-8', capture_output=True, timeout=1200)
    stdout, stderr = result.stdout, result.stderr
    for name in ('sync_key', 'mfa_key', 'password'):
        if secret := (payload or {}).get(name):
            stdout = stdout.replace(secret, '[oculto]')
            stderr = stderr.replace(secret, '[oculto]')
    if result.returncode:
        if result.returncode == 255:
            raise MirrorError('Falló el SSH personal. Comprueba la cuenta, la llave, el puerto y la huella del servidor.')
        if action != 'inspect' and stdout.strip():
            print(stdout.rstrip())
        if action == 'subscribe' and result.returncode == 2:
            raise MirrorError('La suscripción existe y está detenida. Revisa el estado mostrado arriba.')
        detail = next((line for line in stderr.splitlines() if line.startswith('Error: ')), '')
        raise MirrorError(detail.removeprefix('Error: ') or
                          f'Falló el paso remoto {action}. Comprueba --server-dir y que el paquete incluya pc-connect.')
    return stdout.strip()


def start_pc_tunnel(args):
    if not args.no_task:
        install_task(args)
        subprocess.run(['schtasks', '/Run', '/TN', TASK_NAME], check=True)
        return
    options = ({'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
               if os.name == 'nt' else {'start_new_session': True})
    with (RUNTIME / 'tunel.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, *tunnel_arguments(args)], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options)
    print(f'Túnel en segundo plano (PID {process.pid}). Registro en .runtime/espejo/tunel.log.', flush=True)


def pc_connect_mirror(args):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(RUNTIME / 'pc-connect-local.lock') as acquired:
        if not acquired:
            raise MirrorError('Ya hay un pc-connect en ejecución en este PC.')
        return connect_mirror(args)


def connect_mirror(args):
    stage = 'verificar el servidor'
    try:
        if not args.no_task and os.name != 'nt':
            raise MirrorError('La tarea programada requiere Windows. Usa --no-task para iniciar el túnel en segundo plano.')
        if args.known_hosts:
            args.known_hosts = args.known_hosts.resolve()
        print('1/5 Comprobando el servidor espejo con tu llave SSH personal…', flush=True)
        try:
            remote = json.loads(remote_command(args, 'inspect'))
            sync_key = checked_secret(remote['sync_key'], 'MIRROR_SYNC_KEY del servidor')
            subscribed = remote['subscribed']
            if not isinstance(subscribed, bool):
                raise ValueError('subscribed')
        except (ValueError, TypeError, KeyError) as error:
            raise MirrorError('El servidor no entregó una respuesta de espejo válida.') from error
        if not subscribed and not args.yes:
            answer = input('La primera conexión reemplazará las tablas espejo del servidor con los datos del PC. ¿Continuar? [s/N] ')
            if answer.strip().lower() not in ('s', 'si', 'sí'):
                print('Conexión cancelada.')
                return 1

        stage = 'preparar la base y la llave del PC'
        print('2/5 Preparando la replicación y la llave del túnel en el PC…', flush=True)
        path = (args.env_file or PC_ENV).resolve()
        setup = argparse.Namespace(env_file=path, ssh_jump=args.ssh_jump, server_url=None, ssh_host=None,
                                   no_restart=False, skip_secrets=True)
        if code := pc_setup(setup, sync_key=sync_key):
            raise MirrorError(f'La preparación de PostgreSQL quedó pendiente (código {code}).')
        values = read_env(path)
        keygen(argparse.Namespace(quiet=True))

        stage = 'configurar el servidor'
        print('3/5 Configurando MFA y autorizando la llave restringida del túnel…', flush=True)
        result = remote_command(args, 'configure', {'sync_key': sync_key, 'mfa_key': values['MFA_ENCRYPTION_KEY'],
                                                     'pubkey': KEY.with_suffix('.pub').read_text(encoding='utf-8').strip()})
        if result:
            print(result, flush=True)

        stage = 'iniciar el túnel y los servicios del PC'
        print('4/5 Iniciando el túnel del PC…', flush=True)
        start_pc_tunnel(args)
        if os.name == 'nt' and path == PC_ENV.resolve():
            from prototype_windows import start_app
            start_app(reload_configuration=True)

        stage = 'conectar y comprobar la suscripción'
        print('5/5 Esperando la conexión con PostgreSQL y la copia inicial de datos…', flush=True)
        payload = {'sync_key': sync_key, 'pc_database': values['POSTGRES_DB']}
        if not subscribed:
            payload['password'] = values['MIRROR_REPLICA_PASSWORD']
        print(remote_command(args, 'subscribe', payload))
        return 0
    except (EOFError, MirrorError, OSError, subprocess.SubprocessError) as error:
        raise MirrorError(f'No se pudo {stage}. {error} Corrige la causa y repite el mismo comando pc-connect.') from error
    except Exception as error:
        # Los errores de clientes de base de datos pueden incluir SQL y datos privados.
        raise MirrorError(f'No se pudo {stage} ({type(error).__name__}). '
                          'Comprueba que PostgreSQL y GeoCattle estén iniciados y repite el mismo comando pc-connect.') from error


def verify_server(args):
    import docker_project
    try:
        command, env, values = compose(args)
        docker_project.validate_mirror(values)
    except docker_project.ProjectError as error:
        raise MirrorError('El servidor no está preparado como espejo. Completa la Parte A en el servidor correcto.') from error
    profiles = subprocess.run(command + ['config', '--profiles'], cwd=ROOT, env=env,
                              capture_output=True, encoding='utf-8')
    if profiles.returncode or 'mirror' not in profiles.stdout.splitlines():
        raise MirrorError('El servidor no tiene un perfil Compose mirror válido. Revisa la Parte A.')
    if not mfa_restart_pending().exists() or args.step == 'subscribe':
        mode = subprocess.run(command + ['exec', '-T', 'api', 'printenv', 'MIRROR_MODE'], cwd=ROOT, env=env,
                              capture_output=True, encoding='utf-8')
        if mode.returncode or mode.stdout.strip() != 'replica':
            raise MirrorError('La API del servidor no está ejecutándose en modo réplica. Revisa el arranque de la Parte A.')
    return values


def mfa_restart_pending():
    return RUNTIME / 'mfa-restart.pending'


def configure_server(args, values, payload):
    import docker_project
    key = checked_secret(payload.get('mfa_key'), 'MFA_ENCRYPTION_KEY del PC')
    line = payload.get('pubkey', '')
    if not PUBKEY.fullmatch(line):
        raise MirrorError('La llave pública del túnel del PC es inválida.')
    current = values.get('MFA_ENCRYPTION_KEY')
    pending = mfa_restart_pending()
    if current != key:
        pending.touch()
        os.environ['MIRROR_PC_MFA_KEY'] = key
        try:
            server_init(args)
        finally:
            os.environ.pop('MIRROR_PC_MFA_KEY', None)
    authorize(args, line=line)
    if pending.exists():
        print('Aplicando la clave MFA a los servicios del espejo…', flush=True)
        if docker_project.main(['start', '--environment', 'production', '--env-file', str(args.env_file or SERVER_ENV),
                                '--profile', 'cloudflare', '--profile', 'mirror']):
            raise MirrorError('El arranque del espejo quedó pendiente. Revisa Docker y vuelve a conectar desde el PC.')
        pending.unlink()
    else:
        print('El servidor ya tiene la clave MFA del PC.')
    return 0


def subscribe_from_pc(args, payload):
    args.pc_database = payload.get('pc_database', '')
    if not DB_NAME.fullmatch(args.pc_database):
        raise MirrorError('POSTGRES_DB del PC tiene un nombre inválido.')
    deadline = time.monotonic() + 90
    while not pc_reachable(args):
        if time.monotonic() >= deadline:
            raise MirrorError('El servidor no alcanza PostgreSQL por el túnel. Revisa .runtime/espejo/tunel.log en el PC.')
        time.sleep(2)
    if subscription_exists(args):
        print('La suscripción ya existe; se conserva.')
        if psql(args, f"SELECT 1 FROM pg_subscription WHERE subname='{SLOT}' AND subenabled "
                      'AND subdbid = (SELECT oid FROM pg_database WHERE datname = current_database())'):
            wait_sync(args)
        return status(args)
    if 'password' not in payload:
        raise MirrorError('La suscripción desapareció durante la conexión. Repite pc-connect para crearla.')
    os.environ['MIRROR_REPLICA_PASSWORD'] = checked_secret(payload['password'], 'MIRROR_REPLICA_PASSWORD del PC', 20)
    try:
        return subscribe(args)
    finally:
        os.environ.pop('MIRROR_REPLICA_PASSWORD', None)


def pc_remote(args):
    # Solo se usa con la cuenta SSH personal en Linux. Serializa los intentos del PC en este despliegue.
    import fcntl
    from docker_project import ProjectError
    args.env_file = SERVER_ENV
    args.compose_file = None
    try:
        payload = json.load(sys.stdin)
    except ValueError as error:
        raise MirrorError('Solicitud inválida del PC.') from error
    if not isinstance(payload, dict):
        raise MirrorError('Solicitud inválida del PC.')
    values = verify_server(args)
    if args.step == 'inspect':
        print(json.dumps({'sync_key': values['MIRROR_SYNC_KEY'], 'subscribed': subscription_exists(args)}))
        return 0
    with (RUNTIME / 'pc-connect.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        values = verify_server(args)
        if payload.get('sync_key') != values['MIRROR_SYNC_KEY']:
            raise MirrorError('La clave de sincronización del servidor cambió. Revisa la instalación antes de continuar.')
        args.managed = args.host_account = args.yes = True
        args.skip_secrets = args.no_backup = False
        args.host_keys = None
        try:
            if args.step == 'configure':
                return configure_server(args, values, payload)
            return subscribe_from_pc(args, payload)
        except ProjectError as error:
            raise MirrorError(str(error)) from error


# ------------------------------------------------------------------ CLI
def host_account_line(line):
    # En la cuenta del servidor la llave solo sirve para saltar a espejo-ssh: sin shell ni otros destinos.
    # command= anula cualquier orden o consola; el túnel usa -N y no la necesita.
    return f'restrict,port-forwarding,permitopen="{ESPEJO_IP}:22",command="/bin/false" {line}'


def authorize_host_account(line, keys):
    keys = Path(keys)
    keys.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    text = keys.read_text(encoding='utf-8') if keys.exists() else ''
    blob = line.split()[1]
    if any(blob in existing.split() for existing in text.splitlines()):
        return f'La llave del PC ya figura en {keys}; se conserva esa línea.'
    with keys.open('a', encoding='utf-8', newline='\n') as handle:
        if text and not text.endswith('\n'):
            handle.write('\n')
        handle.write(host_account_line(line) + '\n')
    os.chmod(keys, 0o600)
    return f'Llave del PC agregada a {keys}, limitada a saltar a {ESPEJO_IP}:22.'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)

    def command(name, handler, help_text):
        item = sub.add_parser(name, help=help_text)
        item.add_argument('--env-file', type=Path, help='Archivo privado (PC: .env.academic, servidor: .env.pilot)')
        item.set_defaults(handler=handler)
        return item

    item = command('pc-connect', pc_connect_mirror, 'PC: conecta, configura y verifica el espejo por SSH')
    item.add_argument('--ssh-jump', required=True, help='Cuenta personal USUARIO@SERVIDOR[:PUERTO]')
    item.add_argument('--server-dir', default='/srv/GeoCattle', help='Directorio del paquete en el servidor')
    item.add_argument('--identity-file', type=Path, help='Llave SSH personal, si no está en el agente o en ~/.ssh')
    item.add_argument('--known-hosts', type=Path, help='Archivo alternativo de huellas SSH (p. ej. para QA)')
    item.add_argument('--no-task', action='store_true', help='Mantiene el túnel en segundo plano, sin tarea de Windows')
    item.add_argument('--yes', action='store_true', help='Confirma la copia inicial en el servidor espejo')
    item = sub.add_parser('pc-remote')
    item.add_argument('step', choices=('inspect', 'configure', 'subscribe'))
    item.set_defaults(handler=pc_remote)
    item = command('pc-setup', pc_setup, 'PC: activa la réplica lógica, el rol y la publicación')
    item.add_argument('--server-url')
    item.add_argument('--ssh-host')
    item.add_argument('--ssh-jump', help='USUARIO@SERVIDOR[:PUERTO]: túnel solo por SSH, sin Cloudflare Access')
    item.add_argument('--no-restart', action='store_true')
    item.add_argument('--skip-secrets', action='store_true', help='No pedir claves (pruebas)')
    command('pc-status', pc_status, 'PC: estado del slot y de la publicación')
    item = command('pc-admin', pc_admin, 'PC: crea el primer administrador de plataforma (llega al espejo)')
    item.add_argument('--email', required=True)
    item.add_argument('--name', default='Administrador de plataforma')
    item.add_argument('--promote', action='store_true',
                      help='Eleva una cuenta existente sin predios ni membresías vigentes (conserva contraseña)')
    item.add_argument('--yes', action='store_true', help=argparse.SUPPRESS)
    command('pc-drop-slot', pc_drop_slot, 'PC: retira un slot huérfano antes de resync')
    command('keygen', keygen, 'PC: crea la llave SSH del túnel')
    item = command('tunnel', tunnel, 'PC: mantiene el túnel inverso hacia espejo-ssh')
    item.add_argument('--known-hosts', type=Path)
    item.add_argument('--direct', help='HOST:PUERTO sin Cloudflare (solo pruebas locales)')
    item.add_argument('--once', action='store_true')
    item = command('install-task', install_task, 'PC: tarea de Windows que abre el túnel al iniciar sesión')
    item.add_argument('--known-hosts', type=Path)
    item = command('server-init', server_init, 'Servidor: claves y archivos del espejo')
    item.add_argument('--skip-secrets', action='store_true', help='No pedir la MFA_ENCRYPTION_KEY todavía (primera pasada de una instalación nueva, o pruebas)')
    for name, handler, text in (('status', status, 'Servidor: estado de la suscripción'),
                                ('refresh', refresh, 'Servidor: incorpora tablas nuevas tras migrar'),
                                ('enable', enable, 'Servidor: reactiva la suscripción tras un error')):
        item = command(name, handler, text)
        item.add_argument('--compose-file', action='append', help='Archivo Compose adicional (pruebas)')
    item = command('authorize', authorize, 'Servidor: autoriza la llave pública del PC solo para reenvío')
    item.add_argument('pubkey', help='Archivo .pub o - para leer desde stdin')
    item.add_argument('--host-account', action='store_true',
                      help='Agrega también la llave a ~/.ssh/authorized_keys, solo para saltar a espejo-ssh')
    item.add_argument('--host-keys', type=Path, help=argparse.SUPPRESS)
    item.add_argument('--compose-file', action='append')
    for name, handler in (('subscribe', subscribe), ('resync', resync)):
        item = command(name, handler, 'Servidor: copia la base del PC y sigue en vivo')
        item.add_argument('--pc-database', required=True)
        item.add_argument('--yes', action='store_true')
        item.add_argument('--no-backup', action='store_true')
        item.add_argument('--compose-file', action='append')
    args = parser.parse_args(argv)
    try:
        return args.handler(args) or 0
    except (MirrorError, OSError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
