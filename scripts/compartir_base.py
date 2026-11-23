#!/usr/bin/env python3
"""Exporta el prototipo nativo e importa la copia en desarrollo nativo o Docker."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote
from uuid import uuid4

if __package__:
    from . import docker_project
else:
    import docker_project

ROOT = docker_project.ROOT
RUNTIME = ROOT / '.runtime'
TABLES = ('farms', 'users', 'animals', 'devices', 'assignments', 'geofences',
          'telemetry', 'events', 'audit_log', 'mfa_factors', 'request_metrics', 'schema_migrations')
NO_SIMULATION = """SELECT NOT EXISTS (SELECT FROM farms WHERE environment <> 'development')
                      AND NOT EXISTS (SELECT FROM telemetry WHERE source = 'sim')"""


class ShareError(RuntimeError):
    pass


def check_migrations(applied, available):
    if not applied or applied != available[:len(applied)]:
        raise ShareError('Migraciones incompatibles. Si la copia es más reciente, actualiza GeoCattle y vuelve a importar.')


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def checksum(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def checked_archive(path):
    sidecar = path.with_suffix('.sha256')
    if not sidecar.is_file():
        raise ShareError(f'Falta {sidecar.name} junto al archivo .dump.')
    expected = sidecar.read_text(encoding='ascii').strip()
    with path.open('rb') as stream:
        if not re.fullmatch('[a-f0-9]{64}', expected) or checksum(stream) != expected:
            raise ShareError('El SHA-256 no coincide. Pide otra copia de los archivos al remitente.')
        stream.seek(0)
        yield stream


class Postgres:
    def __init__(self, values, command=None):
        self.values = values
        self.database = values['POSTGRES_DB']
        if (not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', self.database)
                or self.database in ('postgres', 'template0', 'template1')):
            raise ShareError('POSTGRES_DB debe identificar una base local de GeoCattle.')
        self.command = command
        self.env = {key: value for key, value in os.environ.items() if not key.upper().startswith('PG')}
        self.env.update(PGPASSWORD=values['POSTGRES_PASSWORD'], PGCONNECT_TIMEOUT='5', PGCLIENTENCODING='UTF8')

    def run(self, utility, database, *args, **streams):
        from_compose = self.command is not None
        executable = utility if from_compose else str(RUNTIME / f'postgres16/pgsql/bin/{utility}.exe')
        command = [executable, '--host=127.0.0.1', '--port=' + ('5432' if from_compose else self.values['DB_PORT']),
                   '--username=' + self.values['POSTGRES_USER'], '--no-password']
        if database is not None:
            command += ['--dbname=' + database]
        if from_compose:
            command = self.command + ['exec', '-T', 'database', 'sh', '-c',
                                      'export PGPASSWORD="$POSTGRES_PASSWORD" PGCONNECT_TIMEOUT=5 PGCLIENTENCODING=UTF8; exec "$@"',
                                      'sh', *command]
        # PostgreSQL can include COPY row contents in errors. Keep them out of the terminal.
        result = subprocess.run(command + list(args), cwd=ROOT, stderr=subprocess.DEVNULL,
                                env=docker_project.command_environment(self.values) if from_compose else self.env,
                                **streams)
        if result.returncode:
            raise ShareError(f'{utility} falló en {database or "el archivo"} (código {result.returncode}).')
        return result.stdout

    def sql(self, database, *statements, transaction=False):
        options = ['--no-psqlrc', '--tuples-only', '--no-align', '--quiet', '--set=ON_ERROR_STOP=1']
        if transaction:
            options.append('--single-transaction')
        for statement in statements:
            options += ['--command', statement]
        return self.run('psql', database, *options, stdout=subprocess.PIPE).decode('utf-8').splitlines()

    def dump(self, database, target, *options):
        partial = target.with_suffix('.dump.part')
        with os.fdopen(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            try:
                self.run('pg_dump', database, '--format=custom', *options, stdout=stream)
                if os.fstat(stream.fileno()).st_size == 0:
                    raise ShareError('pg_dump produjo un archivo vacío.')
            except Exception:
                stream.close()
                partial.unlink(missing_ok=True)
                raise
        partial.replace(target)

    def restore(self, database, stream):
        self.run('pg_restore', database, '--single-transaction', '--no-owner', '--no-privileges',
                 stdin=stream, stdout=subprocess.DEVNULL)

    @contextmanager
    def staging(self):
        name = 'geocattle_share_' + uuid4().hex
        self.sql('postgres', f'CREATE DATABASE {name} TEMPLATE template0')
        try:
            yield name
        finally:
            self.sql('postgres', f'DROP DATABASE IF EXISTS {name}')

    def migrate(self, database):
        values = self.values
        user, password = (quote(values[key], safe='') for key in ('POSTGRES_USER', 'POSTGRES_PASSWORD'))
        host = 'database:5432' if self.command else f'127.0.0.1:{values["DB_PORT"]}'
        url = f'postgresql+psycopg://{user}:{password}@{host}/{database}'
        env = {**docker_project.command_environment(values), 'DATABASE_URL': url}
        if self.command:
            command = self.command + ['run', '--rm', '--no-deps', '--build', '-e', 'DATABASE_URL', 'migrate']
        else:
            command = [sys.executable, '-m', 'geocattle.migrate']
            env['PYTHONPATH'] = str(ROOT / 'backend')
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise ShareError('Fallaron las migraciones o los permisos en la base temporal. Revisa el entorno de GeoCattle.')


def native(*, start=False):
    if os.name != 'nt':
        raise ShareError('El prototipo nativo requiere Windows. Usa --destino docker para importar en Linux.')
    if __package__:
        from . import prototype_windows
    else:
        import prototype_windows
    prototype_windows.require_installation()
    values = docker_project.read_config(prototype_windows.CONFIG, 'development')
    if not values.get('DB_PORT', '').isdigit():
        raise ShareError('Falta un DB_PORT válido en .env.academic.')
    pg = Postgres(values)
    if start:
        prototype_windows.start_database()
    paths = pg.sql('postgres', 'SHOW data_directory')
    if len(paths) != 1 or Path(paths[0]).resolve() != prototype_windows.PG_DATA.resolve():
        raise ShareError('El puerto de .env.academic no corresponde al PostgreSQL del prototipo.')
    return pg


def docker(env_file):
    args = argparse.Namespace(environment='development', env_file=env_file, profile=['lorawan'])
    path = docker_project.config_path(args)
    values = docker_project.read_config(path, args.environment)
    env = docker_project.command_environment(values)
    command = docker_project.compose_command(args, path)
    pg = Postgres(values, command)
    active = docker_project.run(command + ['ps', '--services', '--status', 'running'], env,
                                capture_output=True, text=True).stdout.splitlines()
    if {'api', 'worker', 'ingestor', 'migrate'}.intersection(active):
        raise ShareError('Detén el proyecto Docker de destino antes de importar.')
    docker_project.run(command + ['up', '-d', '--wait', 'database'], env)
    return pg


def verify_restore(pg, archive, expected, compare_sql):
    with pg.staging() as database:
        with checked_archive(archive) as stream:
            pg.restore(database, stream)
        rows = pg.sql(database, *compare_sql)
        if rows != expected:
            raise ShareError('La restauración no coincide con los datos de la instantánea.')
    print('Restauración temporal comprobada y eliminada.')
    for table, count in zip(TABLES, rows):
        print(f'  {table} = {count}')
    print(f'  cuentas activas = {rows[len(TABLES)]}')


def export(pg, include_metrics, verify):
    import psycopg

    date = stamp()
    folder = RUNTIME / 'compartir' / f'geocattle-{date}'
    counts_sql = [f'SELECT count(*) FROM {table}' for table in TABLES]
    compare_sql = [*counts_sql, 'SELECT count(*) FROM users WHERE active',
                   "SELECT md5(string_agg(to_jsonb(u)::text, '' ORDER BY id)) FROM users u",
                   "SELECT md5(string_agg(to_jsonb(f)::text, '' ORDER BY id)) FROM mfa_factors f"]
    values = pg.values
    with psycopg.connect(host='127.0.0.1', port=values['DB_PORT'], dbname=pg.database,
                         user=values['POSTGRES_USER'], password=values['POSTGRES_PASSWORD'], connect_timeout=5) as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if not db.execute(NO_SIMULATION).fetchone()[0]:
            raise ShareError('La base de origen contiene datos de otro entorno o telemetría simulada.')
        migrations = [row[0] for row in db.execute('SELECT version FROM schema_migrations ORDER BY version')]
        snapshot = db.execute('SELECT pg_export_snapshot()').fetchone()[0]
        if verify:
            db.execute("SET LOCAL TIME ZONE 'UTC'")
            expected = [str(value) if value is not None else ''
                        for query in compare_sql for (value,) in db.execute(query)]
            if not include_metrics:
                expected[TABLES.index('request_metrics')] = '0'
        folder.mkdir(mode=0o700, parents=True)
        archive = folder / 'geocattle.dump'
        options = [] if include_metrics else ['--exclude-table-data=public.request_metrics']
        pg.dump(pg.database, archive, '--snapshot=' + snapshot, *options)
    with archive.open('rb') as stream:
        digest = checksum(stream)
    archive.with_suffix('.sha256').write_text(digest + '\n', encoding='ascii')
    if verify:
        verify_restore(pg, archive, expected, ["SET TIME ZONE 'UTC'", *compare_sql])
    metrics = 'incluidas' if include_metrics else 'omitidas (se conserva la tabla)'
    (folder / 'LEEME.md').write_text(
        f'# Copia privada de GeoCattle\n\nFecha UTC `{date}`. Métricas HTTP {metrics}.\n\n'
        'Contiene datos personales, hashes de contraseña y datos cifrados de MFA. '
        'Conserva el `.dump` y `.sha256` juntos y envíalos por un canal privado.\n\n'
        'Desde la raíz de GeoCattle en Windows nativo:\n\n'
        '```powershell\n.\\.venv\\Scripts\\python.exe scripts/compartir_base.py importar RUTA/geocattle.dump --destino nativo\n```\n\n'
        'Desde la raíz en Linux con Docker:\n\n'
        '```bash\npython3 scripts/compartir_base.py importar RUTA/geocattle.dump --destino docker\n```\n\n'
        'Consulta **Compartir una copia del prototipo** en `docs/OPERACION.md` para '
        'preparar el destino y conservar o restablecer TOTP. Usa `py -3` en Docker para Windows.\n\n'
        '## Migraciones de la copia\n\n' + ''.join(f'- `{version}`\n' for version in migrations), encoding='utf-8')
    print(f'Archivo: {archive} ({archive.stat().st_size} bytes)\nSHA-256: {digest}')


def destination_state(pg):
    rows = pg.sql('postgres', f"SELECT oid, (SELECT count(*) FROM pg_stat_activity WHERE datid = d.oid)"
                             f" FROM pg_database d WHERE datname = '{pg.database}'")
    if not rows:
        return 0
    oid, sessions = map(int, rows[0].split('|'))
    if sessions:
        raise ShareError('La base de destino tiene conexiones activas. Detén la API, el worker y la captura antes de importar.')
    return oid


def import_archive(pg, stream):
    existing_oid = destination_state(pg)
    if existing_oid:
        folder = RUNTIME / 'backups'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup = folder / f'antes-de-importar-{pg.database}-{stamp()}.dump'
        pg.dump(pg.database, backup)
        print(f'Respaldo del destino: {backup}', flush=True)

    previous = 'geocattle_previous_' + uuid4().hex
    with pg.staging() as database:
        pg.restore(database, stream)
        versions = pg.sql(database, 'SELECT version FROM schema_migrations ORDER BY version')
        available = sorted(path.name for path in (ROOT / 'database/migrations').glob('*.sql'))
        check_migrations(versions, available)
        if pg.sql(database, NO_SIMULATION) != ['t']:
            raise ShareError('La copia contiene datos de otro entorno o telemetría simulada.')
        pg.migrate(database)
        # Take the same lock for simultaneous imports and check that the backed-up database is still current.
        commands = ["SELECT pg_advisory_xact_lock(545108229)", f"""
            DO $$ BEGIN
                IF NOT COALESCE((SELECT oid = {existing_oid} FROM pg_database WHERE datname = '{pg.database}'),
                                {str(not existing_oid).lower()}) THEN
                    RAISE EXCEPTION 'La base de destino ya es otra';
                END IF;
            END $$
            """]
        if existing_oid:
            commands.append(f'ALTER DATABASE {pg.database} RENAME TO {previous}')
        commands.append(f'ALTER DATABASE {database} RENAME TO {pg.database}')
        try:
            pg.sql('postgres', *commands, transaction=True)
        except ShareError as error:
            raise ShareError('No se pudo activar la copia. Comprueba que el destino no cambió y que no tiene conexiones.') from error
    if existing_oid:
        try:
            pg.sql('postgres', f'DROP DATABASE {previous}')
        except ShareError:
            print(f'La copia está activa. La base anterior sigue disponible con el nombre {previous}.', file=sys.stderr)
    print(f'Importación terminada en {pg.database}. Inicia GeoCattle en el entorno de destino.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    exporter = commands.add_parser('exportar', help='Lee la base del prototipo en ejecución')
    exporter.add_argument('--incluir-metricas', action='store_true', help='Conservar las métricas HTTP')
    exporter.add_argument('--verificar', action='store_true', help='Restaurar y comparar en una base temporal')
    importer = commands.add_parser('importar', help='Reemplaza la base de desarrollo de destino con respaldo previo')
    importer.add_argument('archivo', type=Path)
    importer.add_argument('--destino', required=True, choices=('nativo', 'docker'))
    importer.add_argument('--env-file', type=Path, help='Configuración Docker alternativa (predeterminada: .env.docker)')
    args = parser.parse_args(argv)
    try:
        if args.action == 'exportar':
            export(native(), args.incluir_metricas, args.verificar)
        else:
            if args.env_file and args.destino != 'docker':
                parser.error('--env-file solo se usa con --destino docker')
            with checked_archive(args.archivo) as stream:
                pg = native(start=True) if args.destino == 'nativo' else docker(args.env_file)
                import_archive(pg, stream)
        return 0
    except (ShareError, docker_project.ProjectError, OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    except ImportError:
        print('Error: usa el entorno Python del prototipo (.venv) para exportar o importar en Windows nativo.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
