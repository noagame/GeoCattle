#!/usr/bin/env python3
"""Puente NDJSON XBee/USB o stdin → API, con cola persistente y ACK de escritura.

No decodifica Zigbee ni una carga LoRaWAN. El receptor entrega el contrato lógico
documentado; `observed_at`, sesión y secuencia deben proceder del nodo.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import urllib.error
import urllib.request


class Spool:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY, hardware_id TEXT NOT NULL,
                session_id TEXT NOT NULL, seq INTEGER NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                UNIQUE(hardware_id, session_id, seq))''')
        path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            # SQLite's transaction context does not close the connection.
            # Close explicitly to release the file handle on Windows.
            db.close()

    def enqueue(self, payload):
        identity = (payload['hardware_id'], payload['session_id'], payload['seq'])
        if not all(isinstance(value, str) and value for value in identity[:2]):
            raise ValueError('Identidad y sesión requeridas')
        if type(identity[2]) is not int or identity[2] < 0:
            raise ValueError('Secuencia entera no negativa requerida')
        instant = datetime.fromisoformat(payload['observed_at'].replace('Z', '+00:00'))
        if instant.tzinfo is None:
            raise ValueError('observed_at requiere zona horaria')
        payload.setdefault('schema_version', 1)
        payload.setdefault('source', 'academic')
        with self.connection() as db:
            # Duplicados idénticos son reentregas. Un cambio de carga con la misma
            # identidad es un error de emisor, no una nueva observación.
            old = db.execute('SELECT payload FROM queue WHERE hardware_id=? AND session_id=? AND seq=?', identity).fetchone()
            body = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
            if old:
                if old[0] != body:
                    raise ValueError('Secuencia repetida con contenido diferente')
                return
            if db.execute('SELECT count(*) FROM queue').fetchone()[0] >= 10000:
                raise OverflowError('Cola llena: no se confirma ni descarta la captura')
            db.execute('INSERT INTO queue(hardware_id,session_id,seq,payload) VALUES(?,?,?,?)', (*identity, body))

    def deliver(self, url, key, on_ack):
        with self.connection() as db:
            rows = db.execute("SELECT id,payload FROM queue WHERE status='pending' ORDER BY id LIMIT 100").fetchall()
        committed = 0
        for identity, body in rows:
            request = urllib.request.Request(url, body.encode(), {'Content-Type': 'application/json', 'X-Ingest-Key': key}, method='POST')
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    result = json.load(response)
                if not isinstance(result, dict) or not result.get('id'):
                    raise ValueError('La API no confirmó identidad persistida')
            except (urllib.error.URLError, TimeoutError, ValueError) as error:
                permanent = isinstance(error, urllib.error.HTTPError) and error.code in (400, 403, 404, 409, 422)
                reason = f'HTTP {error.code}' if isinstance(error, urllib.error.HTTPError) else type(error).__name__
                with self.connection() as db:
                    db.execute('UPDATE queue SET attempts=attempts+1,status=?,last_error=? WHERE id=?', ('failed' if permanent else 'pending', reason, identity))
                if not permanent:
                    break
                print(f'Captura {identity} conservada para revisión: {reason}', file=sys.stderr)
                continue
            payload = json.loads(body)
            on_ack({'persisted': True, 'id': result['id'], 'hardware_id': payload['hardware_id'], 'session_id': payload['session_id'], 'seq': payload['seq'], 'duplicate': bool(result.get('duplicate'))})
            with self.connection() as db:
                db.execute('DELETE FROM queue WHERE id=?', (identity,))
            committed += 1
        return committed

    def remaining(self):
        with self.connection() as db:
            return db.execute('SELECT count(*) FROM queue').fetchone()[0]


def read_private_env(path):
    if not path:
        return
    for line in Path(path).read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='USB/serial, ej. /dev/ttyUSB0; sin valor lee stdin')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--env-file', help='Configuración privada del ambiente, sin ejecutar su contenido')
    parser.add_argument('--url', default='http://localhost:8080/api/v1/ingest/telemetry')
    parser.add_argument('--spool', type=Path, default=Path('.runtime/academic-spool.sqlite3'))
    parser.add_argument('--retry-only', action='store_true', help='Reintentar cola existente sin leer mensajes')
    args = parser.parse_args()
    read_private_env(args.env_file)
    key = os.environ.get('INGEST_KEY')
    if not key:
        parser.error('Defina INGEST_KEY en entorno o --env-file. No se acepta por argumento.')
    spool = Spool(args.spool)
    serial_port = None
    if args.port:
        try:
            import serial
        except ImportError:
            parser.error('Instale adapters/requirements.txt para utilizar USB/serial')
        serial_port = serial.Serial(args.port, args.baud, timeout=1, write_timeout=2)
    stop = threading.Event()
    lock = threading.Lock()

    def acknowledge(value):
        encoded = (json.dumps(value, separators=(',', ':')) + '\n').encode()
        with lock:
            if serial_port:
                serial_port.write(encoded)
                serial_port.flush()
            else:
                sys.stdout.buffer.write(encoded)
                sys.stdout.buffer.flush()

    def retry():
        while not stop.wait(2):
            spool.deliver(args.url, key, acknowledge)

    thread = threading.Thread(target=retry, daemon=True)
    if not args.retry_only:
        thread.start()
    try:
        if not args.retry_only:
            stream = serial_port or sys.stdin.buffer
            buffer = b''
            while True:
                raw = stream.read(1) if serial_port else stream.readline(65537)
                if not raw:
                    if serial_port:
                        continue
                    break
                buffer += raw
                if len(buffer) > 65536:
                    raise ValueError('Mensaje NDJSON excede 64 KiB')
                if not buffer.endswith(b'\n'):
                    continue
                try:
                    payload = json.loads(buffer)
                    if not isinstance(payload, dict):
                        raise ValueError('Mensaje debe ser objeto JSON')
                    spool.enqueue(payload)
                except (ValueError, KeyError, TypeError) as error:
                    print(f'Mensaje rechazado, sin ACK: {error}', file=sys.stderr)
                buffer = b''
        # Evitar dos entregas concurrentes del mismo spool al terminar stdin.
        stop.set()
        if thread.is_alive():
            thread.join(timeout=7)
        while spool.deliver(args.url, key, acknowledge):
            pass
        remaining = spool.remaining()
        if remaining:
            print(f'{remaining} mensajes conservados; reintente con --retry-only.', file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        print('Puente detenido; cola conservada.', file=sys.stderr)
        return 0
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(timeout=7)
        if serial_port:
            serial_port.close()


if __name__ == '__main__':
    raise SystemExit(main())

