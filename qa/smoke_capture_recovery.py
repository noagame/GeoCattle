"""Measure durable capture through a real API stop and restart on loopback QA."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url

from adapters.lora_usb import Archive
from geocattle.db import SessionLocal
from qa.benchmark_capture import API, INGEST, fixture, reading


@contextmanager
def api_process(url, directory, label):
    address = urlsplit(url)
    command = [sys.executable, '-m', 'uvicorn', 'geocattle.main:app',
               '--host', address.hostname, '--port', str(address.port)]
    with (directory / f'{label}.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError(f'QA server exited with {process.returncode}')
            try:
                response = httpx.get(url + API + '/health', trust_env=False, timeout=1)
                if response.status_code == 200 and response.json()['environment'] == 'development':
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.25)
        else:
            raise RuntimeError('QA API did not start')
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def run(options, url):
    password = os.environ['QA_BENCH_PASSWORD']
    farm, _ = fixture('recovery-qa', 1, 1, password)
    session = uuid4().hex[:16].upper()
    endpoint = url + API + INGEST
    key = os.environ['INGEST_KEY']
    with api_process(url, options.directory, 'queue-before'):
        # Sondea la misma API y base de datos que recibirá el backlog.
        assert httpx.get(url + API + '/health', trust_env=False).is_success
    stopped_at = time.monotonic()
    original = Archive(options.directory / 'queue')
    first, wire = reading(farm, 0, 1, session, 3900)
    assert original.enqueue(first, wire)
    original.deliver(endpoint, key, str(farm))
    with original.connection() as db:
        attempt = db.execute('SELECT status,attempts,last_error FROM captures').fetchone()
        assert tuple(attempt) == ('pending', 1, 'URLError')
    for seq in range(2, options.messages + 1):
        payload, wire = reading(farm, 0, seq, session, 3900)
        assert original.enqueue(payload, wire)
    assert not original.enqueue(payload, wire)
    del original
    reopened = Archive(options.directory / 'queue')
    assert reopened.stats()['pending'] == options.messages
    print(f'QA API stopped. {options.messages} readings retained after reopening SQLite.', flush=True)
    deadline = stopped_at + options.outage
    while (remaining := deadline - time.monotonic()) > 0:
        time.sleep(min(remaining, 30))
    outage = time.monotonic() - stopped_at

    start = time.monotonic()
    with api_process(url, options.directory, 'queue-after'):
        while reopened.stats()['pending'] and time.monotonic() - start < 180:
            reopened.deliver(endpoint, key, str(farm))
        stats = reopened.stats()
        assert stats['pending'] == 0 and stats['delivered'] == options.messages
        with reopened.connection() as db:
            confirmations = dict(db.execute('SELECT seq,backend_id FROM captures'))
        headers = {'X-Ingest-Key': key, 'X-Farm-ID': str(farm)}
        with httpx.Client(trust_env=False) as client:
            retry = client.post(endpoint, headers=headers, json=first)
        assert retry.status_code == 201 and retry.json()['duplicate']
        assert retry.json()['id'] == confirmations[1]
    with SessionLocal() as db:
        persisted_rows = db.execute(text("""SELECT seq,id::text FROM telemetry
            WHERE farm_id=:farm AND session_id=:session"""), {'farm': farm, 'session': session}).all()
        last_received = db.execute(text('SELECT last_received_at FROM devices WHERE farm_id=:farm'),
                                   {'farm': farm}).scalar_one()
    persisted = dict(persisted_rows)
    assert len(persisted_rows) == len(persisted) == options.messages
    assert persisted == confirmations and set(persisted) == set(range(1, options.messages + 1))
    if options.outage > 630:
        assert last_received is None
    results = {'sent_unique': options.messages, 'persisted_unique': len(persisted),
               'pending': stats['pending'], 'matching_receipts': len(confirmations),
               'duplicate_retry': True, 'outage_seconds': round(outage, 2),
               'recovery_seconds': round(time.monotonic() - start, 2),
               'historical_readings_preserved_freshness': last_received is None}
    (options.directory / 'recovery.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(results, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--outage', type=float, default=1800)
    parser.add_argument('--messages', type=int, default=1000)
    options = parser.parse_args()
    database = make_url(os.environ['DATABASE_URL'])
    if (database.host != '127.0.0.1' or database.port in (None, 55434) or
            not database.database.startswith('geocattle_qa_') or os.environ.get('APP_ENV') != 'development'):
        raise SystemExit('Required: disposable geocattle_qa_* development database on loopback')
    if options.messages < 2 or options.outage < 5:
        parser.error('At least two readings and five seconds down are required')
    options.directory.mkdir()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    assert port != 8084
    run(options, f'http://127.0.0.1:{port}')
