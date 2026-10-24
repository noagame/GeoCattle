"""Inicio local Windows: PostgreSQL/PostGIS, GeoCattle y captura USB.

Los binarios PostgreSQL estan en .runtime/postgres16/pgsql; no modifica el
PostgreSQL instalado en Windows. Para COM5 ejecutar con el usuario de Windows.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters.lora_usb import load_env


def environment(migration=False):
    values = load_env(ROOT / '.env.academic')
    user = values['POSTGRES_USER'] if migration else 'geocattle_app'
    password = values['POSTGRES_PASSWORD'] if migration else values['APP_DATABASE_PASSWORD']
    from sqlalchemy import URL
    url = URL.create('postgresql+psycopg', username=user, password=password,
                     host='127.0.0.1', port=int(values['DB_PORT']), database=values['POSTGRES_DB'])
    env = {**os.environ, **values, 'DATABASE_URL': url.render_as_string(hide_password=False),
           'PYTHONPATH': str(ROOT / 'backend'), 'PYTHONUTF8': '1',
           'TEMP': str(ROOT / '.runtime/tmp'), 'TMP': str(ROOT / '.runtime/tmp'),
           'USB_STATUS_PATH': str(ROOT / '.runtime/capture/status.json')}
    return env


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.5)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def start_database():
    values = load_env(ROOT / '.env.academic')
    port = int(values['DB_PORT'])
    if listening(port):
        return
    subprocess.run([str(ROOT / '.runtime/postgres16/pgsql/bin/pg_ctl.exe'),
        '-D', str(ROOT / '.runtime/pgdata-academic'),
        '-l', str(ROOT / '.runtime/postgres-academic.log'),
        '-o', f'-p {port} -h 127.0.0.1', '-w', 'start'], check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def provision():
    import psycopg
    from psycopg import sql
    values = load_env(ROOT / '.env.academic')
    args = dict(host='127.0.0.1', port=int(values['DB_PORT']),
                user=values['POSTGRES_USER'], password=values['POSTGRES_PASSWORD'])
    with psycopg.connect(**args, dbname='postgres', autocommit=True) as db:
        if not db.execute('SELECT 1 FROM pg_database WHERE datname=%s', (values['POSTGRES_DB'],)).fetchone():
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(values['POSTGRES_DB'])))
    env = environment(migration=True)
    subprocess.run([sys.executable, '-m', 'geocattle.migrate'], cwd=ROOT, env=env, check=True)
    # La cuenta y el dispositivo fisico inicial son idempotentes. Sin animales ficticios.
    code = '''
import json,os
from pathlib import Path
from sqlalchemy import select
from geocattle.db import SessionLocal
from geocattle.models import User,Device,Farm
from geocattle.bootstrap import bootstrap
from geocattle.seed_v3 import reconcile_legacy
from geocattle.domain import append_audit
username='prototipo@geocattle.local'
with SessionLocal() as db:
    exists=db.scalar(select(User).where(User.username==username))
if not exists:
    bootstrap(username,'Prototipo fisico GeoCattle',os.environ['ADMIN_PASSWORD'])
    Path('.runtime/acceso_prototipo.json').write_text(json.dumps({'url':'http://localhost:8084','usuario':username,'contrasena':os.environ['ADMIN_PASSWORD']},indent=2),encoding='utf-8')
with SessionLocal.begin() as db:
    reconcile_legacy(db)
    user=db.scalar(select(User).where(User.username==username))
    if not user or not user.farm_id: raise RuntimeError('Cuenta de prototipo sin predio')
    existing=db.scalar(select(Device).where(Device.hardware_id=='REAL01'))
    if existing and existing.farm_id!=user.farm_id: raise RuntimeError('REAL01 ya pertenece a otro predio')
    if not existing:
        device=Device(farm_id=user.farm_id,hardware_id='REAL01',name='Collar fisico REAL01',transport='academic',interval_seconds=30)
        db.add(device);db.flush()
        append_audit(db,user.farm_id,user.id,'device',device.id,'prototype_provision',after={'hardware_id':'REAL01','interval_seconds':30,'note':'Ventana de supervision; firmware informa su periodo real en quality.period_ms. No es confirmacion remota.'})
print('Cuenta, predio y REAL01 preparados. Sin asignacion a bovino.')
'''
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, check=True)


def spawn(name, arguments, env):
    folder = ROOT / '.runtime'
    pidfile = folder / f'{name}.pid'
    if pidfile.exists():
        try:
            # Windows: OpenProcess comprueba que el proceso registrado sigue vivo.
            if os.name == 'nt':
                import ctypes
                api = ctypes.WinDLL('kernel32', use_last_error=True)
                api.OpenProcess.restype = ctypes.c_void_p
                handle = api.OpenProcess(0x1000, False, int(pidfile.read_text()))
                if handle:
                    exit_code = ctypes.c_ulong()
                    api.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(exit_code))
                    api.CloseHandle(ctypes.c_void_p(handle))
                    if exit_code.value == 259:
                        print(f'{name}: ya esta ejecutandose')
                        return
        except (ValueError, OSError):
            pass
    with (folder / f'{name}.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen(arguments, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    pidfile.write_text(str(process.pid))
    print(f'{name}: iniciado PID {process.pid}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'prepare', 'capture', 'status'])
    parser.add_argument('--stay', action='store_true', help='Mantener supervisor en primer plano')
    parser.add_argument('--no-usb', action='store_true', help='Captura iniciada aparte con el usuario Windows')
    args = parser.parse_args()
    os.chdir(ROOT)
    (ROOT / '.runtime/capture').mkdir(parents=True, exist_ok=True)
    if args.action == 'status':
        print('PostgreSQL:', listening(55434), 'GeoCattle:', listening(8084))
        path = ROOT / '.runtime/capture/status.json'
        print(path.read_text() if path.exists() else 'Sin estado del capturador')
        return
    if args.action in ('prepare', 'start'):
        start_database()
        provision()
    if args.action == 'start':
        if not (ROOT / 'frontend/dist/index.html').exists():
            raise SystemExit('Falta compilar frontend: consultar docs/USB_COM5.md')
        env = environment()
        if not listening(8084):
            spawn('prototype-api', [sys.executable, '-m', 'uvicorn', 'geocattle.local_app:app',
                                   '--host', '127.0.0.1', '--port', '8084'], env)
        spawn('prototype-worker', [sys.executable, '-m', 'geocattle.worker'], env)
    if args.action in ('capture', 'start') and not args.no_usb:
        active = False
        try:
            from datetime import datetime, timezone
            status = json.loads((ROOT / '.runtime/capture/status.json').read_text(encoding='utf-8'))
            active = status.get('connected') and (datetime.now(timezone.utc) - datetime.fromisoformat(status['updated_at'])).total_seconds() < 15
        except (OSError, ValueError, KeyError):
            pass
        if active:
            print('Captura COM5: ya activa; no se abre otro lector')
        else:
            spawn('prototype-usb', [sys.executable, '-u', '-m', 'adapters.lora_usb', '--port', 'COM5'], environment())
    if args.action == 'start':
        print('GeoCattle: http://localhost:8084/#hardware')
        print('Acceso privado: .runtime/acceso_prototipo.json')
    if args.stay:
        print('Supervisor activo. Ctrl+C termina el supervisor.', flush=True)
        while True:
            time.sleep(5)


if __name__ == '__main__':
    main()
