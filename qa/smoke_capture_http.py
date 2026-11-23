"""Exercise the four GeoCattle roles through a disposable development QA API."""
import argparse
from contextlib import ExitStack
import csv
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import ssl
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.engine import make_url

from geocattle.db import SessionLocal
from geocattle.models import Farm, FarmMembership, OwnerAccount, RuleSettings, User
from geocattle.security import hash_password, token_hash
from geocattle.v3_security import totp

API = '/api/v1'
COLLARS = '/v3/device-candidates'
GATEWAYS = '/v3/gateway-candidates'
REPORT = '/v3/animal-reports/inventario'
SESSION = 'geocattle_session'
PASSWORD = os.environ.get('QA_SMOKE_PASSWORD')


def seed_roles():
    encoded = hash_password(PASSWORD)
    roles = {'owner': 'owner', 'other': 'owner', 'worker': 'worker',
             'vet': 'veterinarian', 'admin': 'admin'}
    users = {key: User(id=uuid4(), username=f'{key}-{uuid4().hex[:8]}@example.test',
                       password_hash=encoded, full_name=f'QA {key}', role=role)
             for key, role in roles.items()}
    farms = {key: uuid4() for key in ('owner', 'other')}
    with SessionLocal.begin() as db:
        db.add_all(users.values())
        db.flush()
        for key, farm in farms.items():
            account = OwnerAccount(owner_user_id=users[key].id, display_name=f'QA {key}')
            db.add(account)
            db.flush()
            db.add(Farm(id=farm, account_id=account.id, name=f'Predio QA {key}',
                        environment='development'))
            db.flush()
            users[key].farm_id = farm
            db.add(RuleSettings(farm_id=farm))
        for key in ('worker', 'vet'):
            users[key].farm_id = farms['owner']
            db.add(FarmMembership(farm_id=farms['owner'], user_id=users[key].id,
                                  role_code=roles[key], granted_by=users['owner'].id,
                                  valid_from=datetime.now(timezone.utc) - timedelta(seconds=2)))
    return {key: user.username for key, user in users.items()}, farms


class Smoke:
    def __init__(self):
        self.checks = []

    def request(self, client, method, path, status, **kwargs):
        response = client.request(method, API + path, **kwargs)
        assert response.status_code == status, (method, path, status, response.status_code)
        self.checks.append([method, path.split('?')[0], status])
        return response

    def login(self, client, username, mfa=False):
        response = self.request(client, 'POST', '/auth/login', 200,
                                json={'username': username, 'password': PASSWORD})
        payload = response.json()
        if mfa:
            assert payload['mfa_required'] and payload['setup_required'] and SESSION not in client.cookies
            response = self.request(client, 'POST', '/auth/mfa/verify', 200, json={
                'challenge_token': payload['challenge_token'], 'code': totp(payload['secret']),
            })
            payload = response.json()
        cookie = response.headers['Set-Cookie'].lower()
        assert all(flag in cookie for flag in ('httponly', 'samesite=lax', 'secure'))
        client.headers['X-CSRF-Token'] = payload['csrf_token']
        return payload['user']

    def workflows(self, clients, farms):
        owner, other, worker, vet, admin, visitor = (
            clients[key] for key in ('owner', 'other', 'worker', 'vet', 'admin', 'visitor'))
        capture = {'X-Ingest-Key': os.environ['INGEST_KEY'], 'X-Farm-ID': str(farms['owner'])}
        self.request(admin, 'GET', '/v3/admin/kpis', 200)
        self.request(admin, 'GET', '/dashboard', 409)
        self.request(admin, 'POST', '/auth/context', 200, json={'farm_id': str(farms['owner'])})
        for client in (owner, worker, vet, admin):
            for path in ('/dashboard', '/geofences', '/devices', '/events', REPORT):
                self.request(client, 'GET', path, 200)
        for client in (owner, worker, vet):
            self.request(client, 'POST', '/auth/context', 403, json={'farm_id': str(farms['other'])})
            self.request(client, 'GET', '/v3/admin/kpis', 403)

        animal = self.request(owner, 'POST', '/animals', 201, json={
            'diio': 'QA-' + uuid4().hex[:10], 'name': '=QA <b>Bovino</b>', 'orientation': 'meat',
        }).json()
        hardware = 'QA' + uuid4().hex[:12]
        descriptor = {'hardware_id': hardware, 'transport': 'academic', 'interval_seconds': 45, 'source': 'usb'}
        collar = self.request(owner, 'POST', COLLARS, 201, json=descriptor).json()
        eui = uuid4().hex[:16]
        gateway_usb = {'gateway_eui': eui, 'firmware': 'QA-USB'}
        gateway_candidate = self.request(owner, 'POST', GATEWAYS, 201, json=gateway_usb).json()
        collar_path, gateway_path = f"{COLLARS}/{collar['id']}", f"{GATEWAYS}/{gateway_candidate['id']}"
        device = self.request(admin, 'POST', collar_path + '/approve', 200, json={'name': 'Collar QA'}).json()['device']
        device_path = f"/devices/{device['id']}"
        assignment = self.request(owner, 'POST', '/assignments', 201,
                                  json={'animal_id': animal['id'], 'device_id': device['id']}).json()
        close = f"/assignments/{assignment['id']}/close"
        writes = [('POST', COLLARS, descriptor), ('POST', GATEWAYS, gateway_usb),
                  ('POST', collar_path + '/approve', {}), ('POST', collar_path + '/dismiss', {}),
                  ('POST', gateway_path + '/reserve', {}), ('POST', gateway_path + '/approve', {}),
                  ('POST', gateway_path + '/dismiss', {}), ('POST', close, {}), ('DELETE', device_path, None)]
        for method, path, body in writes:
            self.request(visitor, method, path, 401, json=body)
            for client in (worker, vet):
                self.request(client, method, path, 403, json=body)
            self.request(owner, method, path, 403, json=body, headers={'X-CSRF-Token': 'invalid'})
            if path not in (COLLARS, GATEWAYS):
                self.request(other, method, path, 403, json=body)

        for path in (COLLARS, GATEWAYS, REPORT, '/reports/telemetry.xlsx', '/reports/telemetry.csv'):
            self.request(visitor, 'GET', path, 401)
        assert self.request(other, 'GET', COLLARS + '?status=approved', 200).json()['items'] == []
        assert self.request(other, 'GET', GATEWAYS, 200).json()['items'] == []
        for client in (worker, vet):
            self.request(client, 'GET', COLLARS, 200)
            self.request(client, 'GET', GATEWAYS, 403)
        farms_path = COLLARS + '/capture-farms'
        self.request(owner, 'GET', farms_path, 401)
        self.request(visitor, 'GET', farms_path, 401, headers={'X-Ingest-Key': 'invalid'})
        listed = self.request(visitor, 'GET', farms_path, 200, headers=capture).json()['items']
        assert {str(farm) for farm in farms.values()} <= {farm['id'] for farm in listed}
        self.request(visitor, 'POST', COLLARS, 403, json=descriptor,
                     headers={**capture, 'X-Farm-ID': str(uuid4())})
        self.request(visitor, 'POST', COLLARS, 409, json=descriptor,
                     headers={'X-Ingest-Key': capture['X-Ingest-Key']})
        self.request(visitor, 'GET', farms_path, 401, headers={b'X-Ingest-Key': 'inválido'.encode()})
        self.request(owner, 'POST', close, 403, headers={b'X-CSRF-Token': 'inválido'.encode()})

        preflight = {'Access-Control-Request-Method': 'POST',
                     'Access-Control-Request-Headers': 'content-type,x-csrf-token'}
        origin = str(owner.base_url).rstrip('/')
        allowed = self.request(visitor, 'OPTIONS', COLLARS, 200, headers={**preflight, 'Origin': origin})
        assert allowed.headers['Access-Control-Allow-Origin'] == origin
        self.request(visitor, 'OPTIONS', COLLARS, 400, headers={**preflight, 'Origin': 'https://other.example.test'})
        self.request(owner, 'POST', close, 403, json={}, headers={'Origin': 'https://other.example.test'})

        reservation = self.request(admin, 'POST', gateway_path + '/reserve', 200, json={}).json()
        assert reservation['reserved_node_id'] == 1
        installed = self.request(owner, 'POST', gateway_path + '/approve', 200, json={
            'confirmed_node_id': 1, 'confirmed_eui': eui, 'name': 'Gateway QA',
        }).json()['gateway']
        assert installed['node_id'] == 1
        payload = {'source': 'academic', 'hardware_id': hardware, 'session_id': 'QA-SMOKE', 'seq': 1,
                   'observed_at': datetime.now(timezone.utc).isoformat(), 'gnss_valid': False,
                   'quality': {'radio': {'rssi_dbm': -75.0, 'snr_db': 7.0},
                               'transport': {'bus_version': 1, 'origin_gateway': 1, 'path': 2,
                                             'hops': 1, 'radio_scope': 'collar_to_first_receiver'}}}
        self.request(visitor, 'POST', '/ingest/telemetry', 422, headers=capture, json={**payload, 'seq': -1})
        self.request(visitor, 'POST', '/ingest/telemetry', 422, headers=capture, json={**payload, 'hardware_id': 'Q' * 101})
        self.request(visitor, 'POST', '/ingest/telemetry', 422, headers=capture, json={**payload, 'observed_at': 'today'})
        self.request(visitor, 'POST', '/ingest/telemetry', 422, headers=capture,
                     json={**payload, 'quality': {'note': 'x' * 16384}})
        self.request(visitor, 'POST', '/ingest/telemetry', 422,
                     headers={**capture, 'Content-Type': 'application/json'}, content='{')
        receipt = self.request(visitor, 'POST', '/ingest/telemetry', 201, headers=capture, json=payload).json()
        assert receipt['animal_id'] == animal['id']
        reception, = self.request(owner, 'GET', f"/v3/gateways/{installed['id']}/receptions", 200).json()['items']
        assert reception['telemetry_id'] == receipt['id']
        self.request(other, 'GET', f"/v3/gateways/{installed['id']}/receptions", 403)

        for path in (REPORT + '?format=xlsx', REPORT + '?format=csv', '/reports/telemetry.xlsx', '/reports/telemetry.csv'):
            separator = '&' if '?' in path else '?'
            query = f"{path}{separator}animal_id={animal['id']}"
            self.request(other, 'GET', query, 403)
            for client in (owner, admin, worker, vet):
                downloaded = self.request(client, 'GET', query, 200)
                if 'xlsx' in path:
                    with BytesIO(downloaded.content) as data:
                        workbook = load_workbook(data, read_only=True)
                        assert 'Metadatos' in workbook.sheetnames
                        assert any(cell.value == animal['name'] and cell.data_type == 's'
                                   for row in workbook.worksheets[0].iter_rows() for cell in row)
                        workbook.close()
                else:
                    table = csv.reader(StringIO(downloaded.content.decode('utf-8-sig')))
                    if path.startswith(REPORT):
                        assert any("'" + animal['name'] in row for row in table)
                    else:
                        assert len(list(table)) == 2

        self.request(owner, 'PATCH', device_path, 409, json={'enabled': False})
        self.request(owner, 'POST', close, 200)
        self.request(admin, 'PATCH', device_path, 200, json={'enabled': False})
        self.request(owner, 'DELETE', device_path, 409)
        unused = self.request(owner, 'POST', '/devices', 201, json={
            'hardware_id': 'QA' + uuid4().hex[:12], 'name': 'Collar QA sin uso', 'transport': 'academic',
        }).json()
        self.request(owner, 'DELETE', f"/devices/{unused['id']}", 204)

    def invitation(self, owner, visitor, smtp_required):
        setup = self.request(owner, 'POST', '/auth/mfa/setup', 200, json={'password': PASSWORD}).json()
        challenge = {'challenge_token': setup['challenge_token'], 'code': totp(setup['secret'])}
        self.request(owner, 'POST', '/auth/mfa/verify', 200, json=challenge)
        self.request(owner, 'POST', '/auth/mfa/verify', 401, json=challenge)
        path = '/v3/invitations'
        body = {'role_code': 'worker', 'email': f'invited-{uuid4().hex[:8]}@example.test'}
        self.request(owner, 'POST', path, 403, json=body)
        # El verificador acepta el siguiente paso de tiempo TOTP dentro de su ventana de sesgo de reloj.
        code = totp(setup['secret'], int(time.time() // 30) + 1)
        authorization = self.request(owner, 'POST', '/auth/operation', 200, json={
            'method': 'POST', 'path': API + path, 'payload': body, 'password': PASSWORD, 'code': code,
        }).json()
        headers = {'X-Operation-Token': authorization['operation_token']}
        invite = self.request(owner, 'POST', path, 201, json=body, headers=headers).json()
        self.request(owner, 'POST', path, 403, json=body, headers=headers)
        token = {'token': invite['invitation_token']}

        def await_mail(kind):
            for _ in range(40):
                with SessionLocal() as db:
                    status, encrypted = db.execute(text("""SELECT status,encrypted_token FROM invitation_mail
                        WHERE invitation_id=:id AND kind=:kind"""), {'id': invite['id'], 'kind': kind}).one()
                if status == 'sent':
                    assert encrypted is None
                    return
                time.sleep(.25)
            raise AssertionError(f'SMTP delivery not confirmed for {kind}')

        if smtp_required:
            assert invite['delivery'] == 'queued'
            await_mail('invitation')
        assert self.request(visitor, 'POST', '/v3/enrol/preview', 200, json=token).json()['role_code'] == 'worker'
        creds = {'password': PASSWORD, 'full_name': 'Invited QA'}
        self.request(visitor, 'POST', '/v3/enrol', 201, json={**token, **creds})
        self.request(visitor, 'POST', '/v3/enrol', 401, json={**token, **creds})
        assert self.login(visitor, body['email'])['role'] == 'worker'
        if smtp_required:
            await_mail('accepted')

    def sessions(self, clients):
        worker, vet = clients['worker'], clients['vet']
        original = worker.cookies.get(SESSION)
        self.request(worker, 'POST', '/auth/logout', 204)
        worker.cookies.set(SESSION, original)
        self.request(worker, 'GET', '/auth/me', 401)
        with SessionLocal.begin() as db:
            db.execute(text("UPDATE login_sessions SET last_seen_at=now()-interval '31 minutes' WHERE token_hash=:h"),
                       {'h': token_hash(vet.cookies.get(SESSION))})
        self.request(vet, 'GET', '/auth/me', 401)


def main(options):
    address = urlsplit(options.url)
    database = make_url(os.environ['DATABASE_URL'])
    if (address.scheme != 'https' or address.hostname != '127.0.0.1' or not address.port or
            address.port == 8084 or address.path or address.query or address.fragment or
            database.host != '127.0.0.1' or database.port in (None, 55434) or
            not database.database.startswith('geocattle_qa_') or not PASSWORD):
        raise SystemExit('Required: disposable QA database, password and separate loopback HTTPS API')
    context = ssl.create_default_context(cafile=str(options.ca))
    with ExitStack() as stack:
        clients = {key: stack.enter_context(httpx.Client(base_url=options.url, verify=context, trust_env=False))
                   for key in ('owner', 'other', 'worker', 'vet', 'admin', 'visitor')}
        smoke = Smoke()
        health = smoke.request(clients['visitor'], 'GET', '/health', 200)
        assert health.json()['environment'] == 'development'
        assert health.headers['X-Content-Type-Options'] == 'nosniff'
        home = clients['visitor'].get('/')
        home.raise_for_status()
        assert home.headers['X-Frame-Options'] == 'DENY'
        assert home.headers['Referrer-Policy'] == 'same-origin'
        assert "frame-ancestors 'none'" in home.headers['Content-Security-Policy']
        users, farms = seed_roles()
        for key, username in users.items():
            if key == 'worker':
                clients[key].cookies.set(SESSION, 'unverified-qa-cookie', domain='127.0.0.1', path='/')
            smoke.login(clients[key], username, mfa=key == 'admin')
            if key == 'worker':
                assert 'unverified-qa-cookie' not in [cookie.value for cookie in clients[key].cookies.jar]
        smoke.workflows(clients, farms)
        smoke.invitation(clients['owner'], clients['visitor'], options.smtp)
        smoke.sessions(clients)
    options.output.write_text(json.dumps({'asserted_http_responses': len(smoke.checks),
                                         'smtp_verified': options.smtp}, indent=2) + '\n', encoding='utf-8')
    print(f'{len(smoke.checks)} HTTP responses verified', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--ca', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--smtp', action='store_true')
    main(parser.parse_args())
