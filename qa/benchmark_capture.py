"""Run synthetic capture and concurrent reads on a disposable loopback QA instance."""
import argparse
import asyncio
from collections import Counter, defaultdict
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psutil
from sqlalchemy import bindparam, func, insert, text
from sqlalchemy.engine import make_url

from adapters.lora_bus import decode_many
from geocattle.db import SessionLocal
from geocattle.models import (
    Animal, AnimalHolding, Assignment, Device, Farm, Geofence,
    GeofenceSector, OwnerAccount, PastureAssignment, RuleSettings, Sector, User,
)
from geocattle.security import hash_password

API = '/api/v1'
READS = ('/dashboard', '/geofences', '/devices', '/events', '/v3/animal-reports/inventario')
INGEST = '/ingest/telemetry'
PERIODS = (300, 180, 45)
FENCE = 'POLYGON((-70.70 -33.48,-70.60 -33.48,-70.60 -33.41,-70.70 -33.41,-70.70 -33.48))'


def fixture(label, nodes, users, password):
    farm, account, owner, sector, fence = (uuid4() for _ in range(5))
    linked_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    usernames = [f'{label}-{index}-{farm.hex[:8]}@example.test' for index in range(users)]
    encoded = hash_password(password)
    with SessionLocal.begin() as db:
        db.execute(insert(User), [
            dict(id=owner if index == 0 else uuid4(), username=username,
                 password_hash=encoded, role='owner' if index == 0 else 'worker')
            for index, username in enumerate(usernames)
        ])
        db.add(OwnerAccount(id=account, owner_user_id=owner, display_name=label))
        db.flush()
        db.add(Farm(id=farm, account_id=account, name=label, environment='development'))
        db.flush()
        db.execute(text('UPDATE users SET farm_id=:f WHERE username IN :names').bindparams(
            bindparam('names', expanding=True)), {'f': farm, 'names': usernames})
        db.execute(text("""INSERT INTO farm_memberships(farm_id,user_id,role_code,granted_by,valid_from)
            SELECT :f,id,'worker',:o,:since FROM users WHERE farm_id=:f AND id<>:o"""),
            {'f': farm, 'o': owner, 'since': linked_at})
        db.add_all([RuleSettings(farm_id=farm), Sector(id=sector, farm_id=farm, name='Potrero QA')])
        db.flush()
        db.add(Geofence(id=fence, farm_id=farm, sector_id=sector, name='Geocerca QA',
                        version=1, geometry=func.ST_GeomFromText(FENCE, 4326), created_at=linked_at))
        db.flush()
        db.add(GeofenceSector(farm_id=farm, sector_id=sector, geofence_id=fence))
        db.execute(text("""INSERT INTO gateways(farm_id,name,node_id,node_linked_at,status)
            VALUES(:f,'Gateway QA 01',1,:at,'installed'),(:f,'Gateway QA 02',2,:at,'installed')"""),
            {'f': farm, 'at': linked_at})
        for index in range(nodes):
            animal, device, holding = (uuid4() for _ in range(3))
            hardware_id = f'QA{farm.hex[:7]}{index:04d}'
            period = PERIODS[index % len(PERIODS)]
            db.add_all([
                Animal(id=animal, farm_id=farm, diio=hardware_id, name=f'Bovino QA {index}',
                       orientation='meat', sector_id=sector),
                Device(id=device, farm_id=farm, hardware_id=hardware_id, name=f'Collar QA {index}',
                       transport='academic', interval_seconds=period, installed_at=linked_at),
            ])
            db.flush()
            db.add(AnimalHolding(id=holding, farm_id=farm, animal_id=animal,
                                 reason='QA', valid_from=linked_at))
            db.flush()
            db.add_all([
                Assignment(farm_id=farm, animal_id=animal, device_id=device,
                           animal_holding_id=holding, valid_from=linked_at, assigned_by=owner),
                PastureAssignment(farm_id=farm, animal_id=animal, geofence_id=fence,
                                  valid_from=linked_at),
            ])
    return farm, usernames


def reading(farm, index, seq, session, millivolts):
    period = PERIODS[index % len(PERIODS)] * 1000
    packet = {'v': 5, 'id': f'QA{farm.hex[:7]}{index:04d}', 's': session, 'q': seq,
              # El campo wire describe el firmware, independiente de esta planificación.
              'u': seq * period, 'p': 45000, 'g': [-33.45, -70.66, 500, 8, 1.2],
              't': 18.25, 'a': [0.1, -0.2, 0.95], 'm': [1, 0.086],
              'b': [millivolts, 30, 1, 0, 0], 'f': 0, 'e': 2, 'd': [6200, 40, 0]}
    at = datetime.now(timezone.utc)
    if index % 4 == 0:
        wire = packet
    else:
        node = 1 + index % 2
        wire = {'gc_bus': 1, 'receiver': 'BASEQA', 'batch': f'{session[:8]}-{seq}',
                'readings': [{'packet': packet, 'radio': {'rssi_dbm': -53, 'snr_db': 7.5},
                              'transport': {'delay_ms': 0, 'origin_gateway': node,
                                            'hops': 1, 'path': 1 << node}}]}
    decoded = decode_many(json.dumps(wire), at, receiver='BASEQA')
    assert not decoded.errors and len(decoded.readings) == 1
    return decoded.readings[0]


def summary(values, elapsed):
    durations, codes = zip(*values) if values else ([], [])
    sorted_ms = sorted(durations)
    percentiles = {
        f'p{p}_ms': round(sorted_ms[math.ceil(len(sorted_ms) * p / 100) - 1], 2)
        for p in (50, 95, 99) if sorted_ms
    }
    errors = sum(not 200 <= code < 300 for code in codes)
    return {'n': len(codes), 'codes': dict(Counter(codes)), 'errors': errors,
            'error_pct': round(100 * errors / len(codes), 3) if codes else None,
            'requests_per_second': round(len(codes) / elapsed, 3), **percentiles}


def database_metrics(farm):
    with SessionLocal() as db:
        measured = db.execute(text("""SELECT
            pg_database_size(current_database()) AS database_bytes,
            (SELECT count(*) FROM telemetry WHERE farm_id=:f) AS telemetry,
            (SELECT count(DISTINCT (device_id,session_id,seq)) FROM telemetry WHERE farm_id=:f) AS unique_telemetry,
            (SELECT count(*) FROM gateway_bus_receipts WHERE farm_id=:f) AS bus_receipts,
            (SELECT count(*) FROM telemetry_receptions WHERE farm_id=:f AND gateway_id IS NOT NULL) AS attributed_receptions
            """), {'f': farm}).mappings().one()
        event_ms = db.scalars(text("""SELECT 1000 * extract(epoch FROM e.opened_at-t.received_at)
            FROM events e JOIN telemetry t ON t.id=e.telemetry_id
            WHERE e.farm_id=:f AND e.type='low_battery'"""), {'f': farm})
        return dict(measured), [(float(ms), 200) for ms in event_ms]


async def sample_resources(stop, pids, samples):
    while not stop.is_set():
        item = {}
        for label, pid in pids.items():
            try:
                process = psutil.Process(pid)
                members = [process, *process.children(recursive=True)]
            except psutil.NoSuchProcess:
                continue
            cpu_seconds = rss = 0
            for member in members:
                try:
                    memory = member.memory_info()
                    times = member.cpu_times()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                cpu_seconds += times.user + times.system
                rss += memory.rss
            item[label] = {'cpu_seconds': round(cpu_seconds, 2), 'rss_bytes': rss,
                           'processes': len(members)}
        samples.append(item)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass


async def scenario(options, label, nodes, clients, duration, burst):
    password = os.environ['QA_BENCH_PASSWORD']
    farm, usernames = fixture(label, nodes, clients, password)
    before, _ = database_metrics(farm)
    session = uuid4().hex[:16].upper()
    requests = defaultdict(list)
    responses = Counter()
    identities = {}
    stop = asyncio.Event()
    resources = []
    pids = {label: pid for label, pid in [('api', options.api_pid), ('worker', options.worker_pid),
                                          ('postgres', options.postgres_pid)] if pid}
    limits = httpx.Limits(max_connections=24, max_keepalive_connections=24)
    async with httpx.AsyncClient(base_url=options.url, timeout=30, limits=limits,
                                 trust_env=False) as ingest:
        async def send(client, method, path, **kwargs):
            started = time.perf_counter()
            try:
                response = await client.request(method, API + path, **kwargs)
                code = response.status_code
            except httpx.HTTPError as error:
                responses[type(error).__name__] += 1
                response, code = None, 0
            requests[path].append(((time.perf_counter() - started) * 1000, code))
            return response

        async def get_loop(client):
            index = 0
            while not stop.is_set():
                await send(client, 'GET', READS[index % len(READS)])
                index += 1
                await asyncio.sleep(options.read_interval)

        headers = {'X-Ingest-Key': os.environ['INGEST_KEY'], 'X-Farm-ID': str(farm)}
        semaphore = asyncio.Semaphore(24)

        async def transmit(payload):
            async with semaphore:
                response = await send(ingest, 'POST', INGEST, json=payload, headers=headers)
            if response is not None and response.status_code == 201:
                result = response.json()
                responses['duplicates' if result['duplicate'] else 'new'] += 1
                key = (payload['hardware_id'], payload['session_id'], payload['seq'])
                previous = identities.setdefault(key, result['id'])
                if previous != result['id']:
                    responses['receipt_id_mismatch'] += 1

        async def periodic(index, start):
            interval = PERIODS[index % len(PERIODS)]
            # Stagger each period's senders while keeping the real time interval.
            offset = (index // len(PERIODS)) / math.ceil(nodes / len(PERIODS)) * interval
            seq = 1
            while offset < duration:
                await asyncio.sleep(max(0, start + offset - time.perf_counter()))
                millivolts = 3100 if seq % 2 else 3900
                payload, _ = reading(farm, index, seq, session, millivolts)
                await transmit(payload)
                offset += interval
                seq += 1

        async def send_burst():
            first, _ = reading(farm, 0, 1, session, 3100)
            await asyncio.gather(*(transmit(first) for _ in range(12)))
            await asyncio.gather(*(transmit(reading(farm, i, 1, session, 3100)[0])
                                   for i in range(1, nodes)))

        async with AsyncExitStack() as stack:
            people = []
            for username in usernames:
                client = await stack.enter_async_context(httpx.AsyncClient(
                    base_url=options.url, timeout=30, trust_env=False))
                login = await client.post(API + '/auth/login', json={'username': username, 'password': password})
                if login.status_code != 200 or not client.cookies.get('geocattle_session'):
                    raise RuntimeError(f'Login QA failed: HTTP {login.status_code}')
                people.append(client)
            start = time.perf_counter()
            readers = [asyncio.create_task(get_loop(client)) for client in people]
            monitor = asyncio.create_task(sample_resources(stop, pids, resources))
            try:
                if burst:
                    await send_burst()
                else:
                    await asyncio.gather(*(periodic(index, start) for index in range(nodes)))
                await asyncio.sleep(max(0, start + duration - time.perf_counter()))
            finally:
                stop.set()
                await asyncio.gather(*readers, monitor)
            elapsed = time.perf_counter() - start
    after, event_ms = database_metrics(farm)
    with SessionLocal.begin() as db:
        db.execute(text('UPDATE devices SET enabled=false WHERE farm_id=:f'), {'f': farm})
    return {'nodes': nodes, 'clients': clients, 'duration_seconds': round(elapsed, 2),
            'target_seconds': duration, 'burst': burst, 'routes': {
                path: summary(values, elapsed) for path, values in sorted(requests.items())},
            'get': summary([value for path in READS for value in requests[path]], elapsed),
            'reception_to_event': summary(event_ms, elapsed), 'receipts': dict(responses),
            'before': before, 'after': after, 'database_growth_bytes': after['database_bytes'] - before['database_bytes'],
            'expected_unique': nodes if burst else sum(
                max(0, math.ceil((duration - (i // len(PERIODS)) / math.ceil(nodes / len(PERIODS)) *
                                  PERIODS[i % len(PERIODS)]) / PERIODS[i % len(PERIODS)]))
                for i in range(nodes)),
            'resources_first': resources[0] if resources else {},
            'resources_last': resources[-1] if resources else {},
            'resources_peak_rss_bytes': {label: max((sample.get(label, {}).get('rss_bytes', 0)
                                                    for sample in resources), default=0) for label in pids}}


async def main(options):
    address = urlsplit(options.url)
    database = make_url(os.environ['DATABASE_URL'])
    if (address.scheme != 'http' or address.hostname != '127.0.0.1' or
            address.port in (None, 8084) or address.path or address.query or address.fragment or
            database.host != '127.0.0.1' or database.port in (None, 55434) or
            not database.database.startswith('geocattle_qa_') or os.environ.get('APP_ENV') != 'development'):
        raise SystemExit('Required: disposable geocattle_qa_* database and a separate development loopback API')
    async with httpx.AsyncClient(trust_env=False) as client:
        health = await client.get(options.url + API + '/health')
        health.raise_for_status()
        if health.json()['environment'] != 'development':
            raise SystemExit('QA API must use the development profile')
    results = {}
    for label, count, users, duration, burst in (
        ('periodic', 70, 5, options.duration, False),
        ('burst_70', 70, 10, options.stress_duration, True),
        ('burst_320', 320, 20, options.stress_duration, True),
    ):
        results[label] = await scenario(options, label, count, users, duration, burst)
        options.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        print(label, results[label]['get'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=600)
    parser.add_argument('--stress-duration', type=float, default=35)
    parser.add_argument('--read-interval', type=float, default=1)
    parser.add_argument('--api-pid', type=int)
    parser.add_argument('--worker-pid', type=int)
    parser.add_argument('--postgres-pid', type=int)
    asyncio.run(main(parser.parse_args()))
