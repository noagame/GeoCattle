#!/usr/bin/env python3
"""Isolated Docker/Linux portability test; never opens USB or the live database.

Run with normal user Docker access: python qa/docker_portability.py
Credentials stay in a private QA env file or process environment, never argv.
Default cleanup stops only this generated QA project, preserving its volumes.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

PROJECT_PREFIX = 'geocattle-portability-qa-'
UNIT_MODULES = ('qa.test_docker_portability_safety', 'qa.test_docker_project', 'qa.test_capture_portability', 'qa.test_capture_startup', 'qa.test_serial_receiver',
    'qa.test_capture_runtime', 'qa.test_lora_json', 'qa.test_lora_usb',
    'qa.test_esp32_contract', 'qa.test_academic_bridge', 'qa.test_hardware_api')
PROTECTED_PORTS = {8080, 8082, 8084, 55432, 55433, 55434}

class PortabilityError(RuntimeError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def json_file(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)

def check_project(project):
    if not re.fullmatch(re.escape(PROJECT_PREFIX) + r'[0-9a-f]{6}', project):
        raise PortabilityError('Guard: el proyecto no tiene el prefijo exclusivo de QA')

def test_counts(output, kind):
    if kind == 'pytest':
        passed = re.search(r'(\d+) passed', output)
        skipped = re.search(r'(\d+) skipped', output)
        if not passed or (skipped and int(skipped[1])):
            raise PortabilityError('La suite backend no terminó completa: faltan aprobadas o hay omitidas')
        return int(passed[1])
    found = re.search(r'Ran (\d+) tests?\s+in', output)
    if not found or not re.search(r'^OK\s*$', output, re.M):
        raise PortabilityError('La suite de adaptadores no terminó completa')
    return int(found[1])

class Runner:
    def __init__(self, root, web_port=18084, db_port=55440, keep_running=False):
        self.root = Path(root).resolve()
        if not (self.root / 'compose.yaml').is_file() or not (self.root / 'backend/Dockerfile').is_file():
            raise PortabilityError('Ejecuta desde una copia completa del repositorio GeoCattle')
        if web_port == db_port or any(p in PROTECTED_PORTS or not 1024 <= p <= 65535 for p in (web_port, db_port)):
            raise PortabilityError('Guard: puertos QA inválidos o reservados a las instancias originales')
        self.project = PROJECT_PREFIX + secrets.token_hex(3)
        check_project(self.project)
        self.folder = self.root / '.runtime/docker-portability' / self.project
        self.folder.mkdir(parents=True, exist_ok=False)
        self.env_file = self.folder / 'qa.env'
        self.keep_running = keep_running
        self.started = False
        secret = lambda: secrets.token_hex(32)
        self.config = dict(COMPOSE_PROJECT_NAME=self.project, APP_ENV='simulation', SIMULATION_ENABLED='true',
            POSTGRES_DB='geocattle_portability_sim', POSTGRES_USER='geocattle_qa',
            POSTGRES_PASSWORD=secret(), APP_DATABASE_PASSWORD=secret(), SESSION_SECRET=secret(),
            MFA_ENCRYPTION_KEY=secret(), INGEST_KEY=secret(), DEMO_PASSWORD=secrets.token_urlsafe(24),
            COOKIE_SECURE='false', WEB_PORT=str(web_port), DB_PORT=str(db_port),
            ALLOWED_ORIGINS=f'http://127.0.0.1:{web_port},http://localhost:{web_port}',
            MQTT_USERNAME='geocattle_qa', MQTT_PASSWORD=secret(), MQTT_PORT='18884',
            MQTT_TOPIC='application/+/device/+/event/up,geocattle/academic/telemetry',
            MQTT_SPOOL_PATH='/data/mqtt-spool.sqlite3', CHIRPSTACK_DB_PASSWORD=secret(),
            CHIRPSTACK_API_SECRET=secret(), CHIRPSTACK_PORT='18085', TLS_PORT='18445',
            CONFIG_DOWNLINK_ENABLED='false', CONFIG_CODEC_VALIDATED='false',
            CHIRPSTACK_APPLICATION_ID='', CONFIG_FPORT='10', NOTIFICATION_WEBHOOK_URL='')
        # Every mapped operational setting belongs to this isolated QA run.
        # Host pilot settings must not change the smoke contract or call providers.
        self.config.update(SESSION_HOURS='12', MQTT_ACK_TOPIC='geocattle/academic/committed',
            MQTT_CLIENT_ID=self.project+'-ingestor', MQTT_TLS='false',
            PREVENTIVE_RULES_VALIDATED='false', WORKER_INTERVAL_SECONDS='15',
            CONFIG_TIMEOUT_SECONDS='3600', NOTIFICATION_WEBHOOK_TOKEN='',
            NOTIFICATION_MAX_ATTEMPTS='3', NOTIFICATION_EXPIRY_HOURS='24',
            ADMIN_PASSWORD='', V3_ADMIN_PASSWORD='')
        descriptor = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write('# Configuracion QA privada; no subir a Git.\n')
            stream.write('\n'.join(f'{key}={value}' for key, value in self.config.items()) + '\n')
        self.env = {**os.environ, **self.config, 'PYTHONUTF8':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
        for key in tuple(self.env):
            if key.startswith('SMOKE_') or key in ('COMPOSE_FILE', 'COMPOSE_PROFILES',
                    'COMPOSE_ENV_FILES', 'DATABASE_URL', 'TEST_DATABASE_URL'):
                self.env.pop(key, None)
        self.secrets = [v for k,v in self.config.items() if any(t in k for t in ('PASSWORD','SECRET','KEY')) and len(v)>7]
        self.base = f'http://127.0.0.1:{web_port}'
        self.report = dict(project=self.project, started_at=now(), status='running', checks=[],
            environment='simulation', url=self.base, ports={'web':web_port,'database':db_port,'mqtt':18884},
            actual_usb='not_checked', real_database='not_accessed', linux_engine=None,
            limits=['No comprueba USB real, GPS, cobertura radio, batería ni capacidad de 70 collares físicos.',
                    'No convierte los datos QA simulados en mediciones reales.'])
        self.phase = 'created'
        self.write_progress('Preparando entorno QA aislado')

    def redact(self, value):
        for secret in self.secrets:
            value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(postgres(?:ql)?(?:\+psycopg)?://[^:/\s]+:)[^@\s]+@', r'\1[REDACTED]@', value)

    def write_progress(self, message):
        json_file(self.folder/'progress.json', dict(project=self.project, phase=self.phase,
            message=message, updated_at=now(), status=self.report['status']))
        json_file(self.folder/'report.json', self.report)
        json_file(self.folder.parent/'latest.json', {'project':self.project,'directory':str(self.folder),'updated_at':now()})

    def check(self, name, condition, detail=None):
        self.report['checks'].append({'check':name,'passed':bool(condition), **({'detail':detail} if detail is not None else {})})
        if not condition:
            raise PortabilityError('Comprobacion fallida: '+name)

    def command(self, name, arguments, *, extra_env=None, timeout=1200, allow_failure=False, stdin=None):
        self.phase = name
        self.write_progress('Ejecutando '+name)
        print(f'[{len(self.report["checks"])+1}] {name}', flush=True)
        path=self.folder/(re.sub(r'[^a-zA-Z0-9_-]','_',name)+'.log')
        lines=queue.Queue()
        with path.open('w',encoding='utf-8',newline='\n') as log:
            process=subprocess.Popen(arguments,cwd=self.root,env={**self.env,**(extra_env or {})},
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
            def read():
                try:
                    for line in process.stdout: lines.put(line)
                finally:
                    process.stdout.close()
                    lines.put(None)
            reader=threading.Thread(target=read,daemon=True);reader.start()
            if stdin is not None:
                process.stdin.write(stdin);process.stdin.close()
            begun=time.monotonic();heartbeat=begun;collected=[];done=False
            try:
                while not done:
                    try: line=lines.get(timeout=1)
                    except queue.Empty: line=''
                    if line is None:done=True
                    elif line:
                        safe=self.redact(line);log.write(safe);log.flush();collected.append(safe)
                        print(safe.rstrip(),flush=True)
                    if time.monotonic()-begun>timeout:
                        process.kill();process.wait()
                        raise PortabilityError('Tiempo agotado en '+name+'; consulta su registro QA')
                    if time.monotonic()-heartbeat>=20:
                        self.write_progress('Continua '+name);print('   Continua '+name+'...',flush=True);heartbeat=time.monotonic()
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                raise
            code=process.wait();output=''.join(collected)
        self.report['checks'].append({'check':name,'passed':code==0,'exit_code':code,'log':path.name})
        if code and not allow_failure:raise PortabilityError(name+' termino con codigo '+str(code)+'; consulta su registro QA')
        return output

    def compose(self, *arguments):
        check_project(self.project)
        if self.env_file.parent!=self.folder or self.folder.parent!=self.root/'.runtime/docker-portability':
            raise PortabilityError('Guard: configuracion fuera de carpeta QA')
        return ['docker','compose','--project-name',self.project,'--env-file',str(self.env_file),
                '-f',str(self.root/'compose.yaml'),'--profile','iot','--profile','lorawan',*arguments]

    def container_python(self, name, code):
        return self.command(name,self.compose('exec','-T','api','python','-'),stdin=code)

    def web(self):
        self.phase='http-static-and-contract';self.write_progress('Verificando Nginx, assets y contrato API')
        opener=build_opener()
        def get(path):
            with opener.open(self.base+path,timeout=20) as response:
                return response.read(),response.headers
        raw,headers=get('/')
        html=raw.decode('utf-8');self.check('Nginx sirve HTML de GeoCattle','GeoCattle' in html)
        assets=set(re.findall(r'(?:src|href)="(/assets/[^\"]+)"',html))
        self.check('HTML referencia assets generados',bool(assets))
        for asset in sorted(assets):
            body,asset_headers=get(asset)
            self.check('Asset real '+asset.split('/')[-1],bool(body) and 'text/html' not in asset_headers.get('Content-Type',''))
        csp=headers.get('Content-Security-Policy','')
        source=next((part.strip().split()[1:] for part in csp.split(';') if part.strip().startswith('img-src ')),[])
        self.check('CSP admite dominio exacto de teselas OSM','https://tile.openstreetmap.org' in source)
        health=json.loads(get('/api/v1/health')[0]);self.check('API y PostgreSQL QA responden',health.get('status')=='ok' and health.get('environment')=='simulation')
        paths=json.loads(get('/api/openapi.json')[0])['paths']
        self.check('Contrato desplegado incluye telemetria USB',all('/api/v1/hardware/'+suffix in paths for suffix in ('overview','telemetry','daily','receiver')))
        self.check('Contrato desplegado incluye asociaciones historicas','/api/v1/animals/{animal_id}/assignments' in paths)

    def hardware_http(self):
        opener=build_opener(HTTPCookieProcessor(CookieJar()))
        def call(path,body=None):
            payload=json.dumps(body).encode() if body is not None else None
            headers={'Content-Type':'application/json'} if body is not None else {}
            with opener.open(Request(self.base+'/api/v1'+path,data=payload,headers=headers),timeout=20) as response:
                return json.load(response) if response.status!=204 else None
        session=call('/auth/login',{'username':'demo@geocattle.local','password':self.config['DEMO_PASSWORD']})
        self.check('HTTP owner con contexto QA',session['user']['role']=='owner')
        samples=call('/hardware/overview');self.check('Vista hardware acepta datos simulados',bool(samples['items']) and any(x['latest'] and x['latest']['source']=='sim' for x in samples['items']))
        daily=call('/hardware/daily?days=2');self.check('Resumen diario responde con zona horaria',daily.get('timezone')=='America/Santiago' and bool(daily['items']))
        receiver=call('/hardware/receiver');self.check('Sin USB se declara no disponible',receiver.get('available') is False and receiver.get('connected') is False)
        request=Request(self.base+'/api/v1/auth/logout',data=b'',method='POST',headers={'X-CSRF-Token':session['csrf_token']})
        with opener.open(request,timeout=20) as response:self.check('Sesion de comprobacion cerrada',response.status==204)

    def count_telemetry(self, phase):
        value=self.container_python(phase,"from sqlalchemy import text\nfrom geocattle.db import engine\nwith engine.connect() as c: print('QA_COUNT='+str(c.scalar(text('SELECT count(*) FROM telemetry'))))\n")
        found=re.search(r'QA_COUNT=(\d+)',value)
        if not found:raise PortabilityError('No se pudo verificar persistencia QA')
        return int(found[1])

    def service_integration(self):
        output=self.command('redis-ping',self.compose('exec','-T','redis','redis-cli','ping'),timeout=30)
        self.check('Redis responde PONG','PONG' in output)
        endpoint='http://127.0.0.1:'+self.config['CHIRPSTACK_PORT']
        opener=build_opener();up=False
        for _ in range(40):
            try:
                with opener.open(endpoint,timeout=3) as response:
                    up=response.status==200 and len(response.read())>100
                    if up:break
            except OSError:pass
            time.sleep(.5)
        self.check('Interfaz local de ChirpStack responde',up)
        schema=self.command('chirpstack-schema',self.compose('exec','-T','chirpstack-database','psql',
            '-U','chirpstack','-d','chirpstack','-v','ON_ERROR_STOP=1','-At','-c',
            "SELECT CASE WHEN (SELECT count(*) FROM pg_extension WHERE extname IN ('pg_trgm','hstore'))=2 "
            "AND to_regclass('public.device') IS NOT NULL AND to_regclass('public.gateway') IS NOT NULL "
            "AND to_regclass('public.multicast_group_queue_item') IS NOT NULL "
            "AND to_regclass('public.fuota_deployment_job') IS NOT NULL "
            "THEN 'CHIRPSTACK_SCHEMA_OK' ELSE 'CHIRPSTACK_SCHEMA_INCOMPLETE' END"),timeout=30)
        self.check('ChirpStack tiene extensiones y tablas migradas','CHIRPSTACK_SCHEMA_OK' in schema)
        code=r"""
import json,os,time,threading,uuid
from datetime import datetime,timezone
from http.cookiejar import CookieJar
from urllib.request import build_opener,HTTPCookieProcessor,Request
import paho.mqtt.client as mqtt
opener=build_opener(HTTPCookieProcessor(CookieJar()));csrf=None
base='http://127.0.0.1:8000/api/v1'
def api(path,body=None):
    headers={'Content-Type':'application/json'} if body is not None else {}
    if csrf and body is not None:headers['X-CSRF-Token']=csrf
    request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with opener.open(request,timeout=15) as response:
        return json.load(response) if response.status!=204 else None
session=api('/auth/login',{'username':'demo@geocattle.local','password':os.environ['DEMO_PASSWORD']});csrf=session['csrf_token']
identifier='qa-mqtt-'+uuid.uuid4().hex[:10]
api('/devices',{'hardware_id':identifier,'name':'Docker MQTT QA','transport':'academic','interval_seconds':300})
session_id='qa-'+uuid.uuid4().hex
body={'schema_version':1,'hardware_id':identifier,'session_id':session_id,'seq':1,'observed_at':datetime.now(timezone.utc).isoformat(),'longitude':None,'latitude':None,'gnss_valid':False,'surface_temperature_c':25.0,'activity_index':.02,'battery_mv':3900,'source':'sim','quality':{'synthetic':True,'test':'docker-portability'}}
ready=threading.Event();committed=threading.Event()
client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='qa-publisher-'+uuid.uuid4().hex[:8])
client.username_pw_set(os.environ['MQTT_USERNAME'],os.environ['MQTT_PASSWORD'])
def connected(client,userdata,flags,reason,properties):
    if not reason.is_failure:client.subscribe('geocattle/academic/committed',qos=1)
def subscribed(client,userdata,mid,reasons,properties):ready.set()
def message(client,userdata,msg):
    data=json.loads(msg.payload)
    if data.get('hardware_id')==identifier and data.get('session_id')==session_id and data.get('seq')==1 and data.get('status')=='committed':committed.set()
client.on_connect=connected;client.on_subscribe=subscribed;client.on_message=message
try:
    for attempt in range(30):
        try:client.connect('broker',1883,60);break
        except OSError:
            if attempt==29:raise
            time.sleep(.5)
    client.loop_start()
    assert ready.wait(20),'MQTT subscription not ready'
    result=client.publish('geocattle/academic/telemetry',json.dumps(body),qos=1)
    result.wait_for_publish(10);assert result.is_published(),'MQTT publish not confirmed'
    assert committed.wait(30),'No application committed receipt received'
    matched=None
    for _ in range(30):
        matched=next((row for row in api('/hardware/overview')['items'] if row['hardware_id']==identifier and row['latest'] and row['latest']['seq']==1),None)
        if matched:break
        time.sleep(.5)
    assert matched is not None,'MQTT sample not visible through API'
    print('MQTT_COMMITTED_AND_VISIBLE=1')
finally:
    client.disconnect();client.loop_stop()
    api('/auth/logout',{})
"""
        output=self.container_python('mqtt-end-to-end',code)
        self.check('MQTT QoS1 llega a ingestor PostgreSQL y API','MQTT_COMMITTED_AND_VISIBLE=1' in output)

    def worker_integration(self):
        """Observe the scheduled worker without invoking the timeout scenario."""
        code = r'''
import json, os, time
from datetime import datetime, timedelta
from http.cookiejar import CookieJar
from urllib.request import build_opener, HTTPCookieProcessor, Request
from uuid import UUID
from sqlalchemy import select, or_
from geocattle.db import SessionLocal
from geocattle.models import Animal, Assignment, Device, Farm, PastureAssignment, Telemetry, utcnow
from geocattle.settings import settings

base = 'http://127.0.0.1:8000/api/v1'
opener = build_opener(HTTPCookieProcessor(CookieJar()))
csrf = None

def api(path, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    if csrf and body is not None:
        headers['X-CSRF-Token'] = csrf
    request = Request(base + path, data=data, headers=headers)
    with opener.open(request, timeout=5) as response:
        return json.load(response) if response.status != 204 else None

# Both the remote API and this container's configuration must prove simulation
# before selecting or changing any row. Credentials are never printed.
health = api('/health')
assert health.get('status') == 'ok' and health.get('environment') == 'simulation', 'Remote API is not QA simulation'
cfg = settings()
assert cfg.app_env == 'simulation' and cfg.simulation_enabled is True, 'Container is not QA simulation'
session = api('/auth/login', {'username': 'demo@geocattle.local', 'password': os.environ['DEMO_PASSWORD']})
csrf = session['csrf_token']
assert session['user']['role'] == 'owner' and session['user'].get('farm_id'), 'Missing QA owner context'
farm_id = UUID(session['user']['farm_id'])
selected = None
baseline_received_at = None
backdated = False
restored = False

try:
    with SessionLocal() as db:
        farm = db.get(Farm, farm_id)
        assert farm and farm.environment == 'simulation', 'Selected farm is not synthetic'
        now = utcnow()
        candidates = db.execute(
            select(Assignment, Animal, Device)
            .join(Animal, Animal.id == Assignment.animal_id)
            .join(Device, Device.id == Assignment.device_id)
            .where(Assignment.farm_id == farm_id, Animal.farm_id == farm_id,
                   Device.farm_id == farm_id, Animal.enabled.is_(True), Device.enabled.is_(True),
                   Animal.diio.like('SIM-%'), Device.hardware_id.like('sim-collar-%'),
                   Assignment.valid_from <= now,
                   or_(Assignment.valid_to.is_(None), Assignment.valid_to > now))
            .order_by(Animal.diio)
        ).all()
        for assignment, animal, device in candidates:
            threshold = 3 * device.interval_seconds + 30
            # A new installation is intentionally protected by its own baseline.
            if assignment.valid_from > now - timedelta(seconds=threshold + 2):
                continue
            seed = db.scalar(select(Telemetry).where(
                Telemetry.device_id == device.id, Telemetry.animal_id == animal.id,
                Telemetry.assignment_id == assignment.id,
                Telemetry.source == 'sim', Telemetry.session_id == 'seed-simulation-v1'
            ).limit(1))
            latest = db.get(Telemetry, device.last_telemetry_id) if device.last_telemetry_id else None
            zone = db.scalar(select(PastureAssignment).where(
                PastureAssignment.farm_id == farm_id, PastureAssignment.animal_id == animal.id,
                PastureAssignment.valid_from <= now,
                or_(PastureAssignment.valid_to.is_(None), PastureAssignment.valid_to > now)
            ).limit(1))
            if (seed is None or seed.quality.get('simulation') is not True or latest is None
                    or latest.source != 'sim' or latest.quality.get('simulation') is not True or zone is None):
                continue
            selected = {'device': device.id, 'animal': animal.id, 'assignment': assignment.id,
                        'threshold': threshold, 'interval': device.interval_seconds}
            break
    assert selected is not None, 'No old synthetic seed assignment is eligible for independent worker QA'
    animal_id, device_id = str(selected['animal']), str(selected['device'])

    def events_for(condition):
        offset, result = 0, []
        while True:
            page = api('/events?condition=' + condition + '&limit=500&offset=' + str(offset))
            rows = page.get('items', [])
            result.extend(row for row in rows if row.get('device_id') == device_id
                          and row.get('animal_id') == animal_id and row.get('type') == 'communication_timeout')
            offset += len(rows)
            if not rows or offset >= page.get('total', offset):
                return result

    # This creates a NEW synthetic observation through ingestion; immutable
    # telemetry and historical assignment timestamps are never rewritten.
    normal = api('/simulation/scenarios', {'scenario': 'normal', 'animal_id': animal_id})
    assert normal.get('source') == 'sim', 'Baseline observation is not synthetic'
    assert not events_for('active'), 'Normal scenario did not clear previous communication timeout'

    with SessionLocal.begin() as db:
        farm = db.get(Farm, farm_id)
        assignment = db.get(Assignment, selected['assignment'])
        device = db.get(Device, selected['device'], with_for_update=True)
        now = utcnow()
        assert farm and farm.environment == 'simulation', 'Farm context changed'
        assert (assignment and assignment.device_id == device.id and assignment.animal_id == selected['animal']
                and assignment.valid_from <= now - timedelta(seconds=selected['threshold'] + 2)
                and (assignment.valid_to is None or assignment.valid_to > now)), 'Assignment context changed'
        assert device.enabled and device.farm_id == farm_id and device.interval_seconds == selected['interval'], 'Device context changed'
        latest = db.get(Telemetry, device.last_telemetry_id)
        assert latest and latest.source == 'sim' and latest.quality.get('simulation') is True, 'Latest observation is not synthetic'
        baseline_received_at = device.last_received_at
        assert baseline_received_at is not None, 'Normal scenario did not set effective communication time'
        armed_at = now
        device.last_received_at = now - timedelta(seconds=3 * device.interval_seconds + 31)
    backdated = True

    # No timeout function, worker command or timeout scenario is called here.
    # Only the separately scheduled Compose worker can create the new event.
    deadline = time.monotonic() + 45
    detected = None
    while True:
        matching = events_for('active')
        if matching:
            assert len(matching) == 1, 'More than one active timeout for the selected synthetic device'
            detected = matching[0]
            break
        if time.monotonic() >= deadline:
            raise AssertionError('Independent worker did not open the timeout within 45 seconds')
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    assert detected['detail'].get('threshold_seconds') == selected['threshold'], 'Timeout did not use 3T+30'
    assert datetime.fromisoformat(detected['opened_at'].replace('Z', '+00:00')) >= armed_at, 'Detected event predates arming'
    animal = api('/animals/' + animal_id)
    assert animal.get('communication_status') == 'absent', 'API did not expose the absent communication state'

    recovered = api('/simulation/scenarios', {'scenario': 'normal', 'animal_id': animal_id})
    assert recovered.get('source') == 'sim', 'Recovery observation is not synthetic'
    assert not events_for('active'), 'New normal observation did not resolve the timeout'
    assert any(row['id'] == detected['id'] for row in events_for('resolved')), 'Timeout history was not preserved as resolved'
    assert api('/animals/' + animal_id).get('communication_status') == 'recent', 'Recovery did not restore recent communication'
    restored = True
    print('WORKER_TIMEOUT_INDEPENDENT=1')
    print('WORKER_TIMEOUT_RESOLVED=1')
finally:
    try:
        if backdated and not restored:
            try:
                api('/simulation/scenarios', {'scenario': 'normal', 'animal_id': str(selected['animal'])})
                assert not events_for('active'), 'Cleanup observation did not resolve the synthetic timeout'
            except Exception:
                # Restore only the mutable device clock if HTTP cleanup fails.
                # A failure still propagates: this fallback is not a QA pass.
                with SessionLocal.begin() as db:
                    farm = db.get(Farm, farm_id)
                    device = db.get(Device, selected['device'], with_for_update=True)
                    assert farm and farm.environment == 'simulation' and device.farm_id == farm_id
                    device.last_received_at = baseline_received_at
                raise
    finally:
        api('/auth/logout', {})
'''
        output = self.container_python('worker-independent-timeout', code)
        self.check('Worker independiente abre ausencia con 3T+30', 'WORKER_TIMEOUT_INDEPENDENT=1' in output)
        self.check('Lectura nueva resuelve ausencia y conserva historia', 'WORKER_TIMEOUT_RESOLVED=1' in output)

    def execute(self):
        for port in (int(self.config['WEB_PORT']),int(self.config['DB_PORT']),int(self.config['MQTT_PORT']),int(self.config['CHIRPSTACK_PORT'])):
            with socket.socket() as probe:
                try:probe.bind(('127.0.0.1',port))
                except OSError:raise PortabilityError('El puerto QA '+str(port)+' esta ocupado; no se toca la instancia existente')
        info=self.command('docker-info',['docker','info','--format','{"OSType":{{json .OSType}},"OperatingSystem":{{json .OperatingSystem}},"ServerVersion":{{json .ServerVersion}},"Architecture":{{json .Architecture}}}'],timeout=30)
        try:engine=json.loads(info)
        except ValueError:raise PortabilityError('Docker no devolvio informacion JSON valida')
        self.check('Docker usa contenedores Linux',engine.get('OSType')=='linux');self.report['linux_engine']=engine.get('OperatingSystem','linux');self.report['engine']=engine
        self.command('compose-config',self.compose('config','-q'),timeout=30)
        self.started=True
        self.command('build-and-start-runtime',self.compose('up','-d','--build','--wait','--wait-timeout','240'),timeout=1800)
        self.command('seed-simulation',self.compose('run','--rm','--no-deps','seed'))
        self.command('reconcile-v3',self.compose('run','--rm','--no-deps','seed','python','-m','geocattle.seed_v3'))
        self.web()
        self.service_integration()
        self.worker_integration()
        self.command('http-functional-smoke',[sys.executable,str(self.root/'qa/smoke_api.py'),'--env-file',str(self.env_file),'--output',str(self.folder/'http-smoke.json')],extra_env={'BASE_URL':self.base},timeout=300)
        smoke=json.loads((self.folder/'http-smoke.json').read_text(encoding='utf-8'))
        self.check('Smoke HTTP completo',not smoke.get('aborted') and smoke.get('failed')==0 and smoke.get('passed',0)>0)
        self.report['http_checks_passed']=smoke['passed']
        self.hardware_http()
        image=self.project+'-test'
        self.command('build-linux-test-image',['docker','build','-f',str(self.root/'backend/Dockerfile'),'--target','test','--tag',image,str(self.root)],timeout=1800)
        test_db='geocattle_portability_tests'
        self.command('create-isolated-test-database',self.compose('exec','-T','database','sh','-c',
            'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE geocattle_portability_tests"'))
        url=f'postgresql+psycopg://{self.config["POSTGRES_USER"]}:{self.config["POSTGRES_PASSWORD"]}@database:5432/{test_db}'
        test_env={'DATABASE_URL':url,'TEST_DATABASE_URL':url,'APP_ENV':'development','SIMULATION_ENABLED':'false','APP_DATABASE_PASSWORD':'','GEOCATTLE_TEST_DATABASE':'1'}
        run=['docker','run','--rm','--network',self.project+'_default','--env-file',str(self.env_file),
            '-e','DATABASE_URL','-e','TEST_DATABASE_URL','-e','APP_ENV','-e','SIMULATION_ENABLED','-e','APP_DATABASE_PASSWORD','-e','GEOCATTLE_TEST_DATABASE',image]
        self.command('migrate-test-database',run+['python','-m','geocattle.migrate'],extra_env=test_env)
        output=self.command('pytest-linux-backend',run+['python','-m','pytest','/app/tests','-q','-p','no:cacheprovider'],extra_env=test_env,timeout=900)
        self.report['backend_tests_passed']=test_counts(output,'pytest')
        output=self.command('unittest-linux-adapters',run+['python','-m','unittest',*UNIT_MODULES],extra_env=test_env,timeout=180)
        self.report['adapter_tests_passed']=test_counts(output,'unittest')
        before=self.count_telemetry('persistence-before')
        self.command('stop-qa-preserving-volumes',self.compose('down'),timeout=120)
        self.command('restart-existing-qa',self.compose('up','-d','--wait','--wait-timeout','240'),timeout=600)
        after=self.count_telemetry('persistence-after')
        self.check('Reinicio conserva telemetria QA',before==after and before>0,{'before':before,'after':after})
        self.web()

    def finish(self, error=None):
        self.report['status']='failed' if error else 'passed'
        if error:self.report['error']=self.redact(str(error))
        if error and self.started:
            try:self.command('failure-service-logs',self.compose('logs','--no-color','--tail','80'),timeout=30,allow_failure=True)
            except Exception:pass
        if self.started and not self.keep_running:
            try:self.command('final-stop-qa',self.compose('down'),timeout=120);self.report['containers']='stopped; volumes preserved'
            except Exception as cleanup:
                self.report['cleanup_error']=self.redact(str(cleanup));self.report['status']='failed'
                self.report['containers']='cleanup failed; inspect this QA project only'
        elif self.started:self.report['containers']='left running by --keep-running'
        self.report['finished_at']=now();self.phase='finished';self.write_progress('Prueba terminada: '+self.report['status'])
        print('Informe QA: '+str(self.folder/'report.json'),flush=True)
        if error:print('No se confirma portabilidad completa; consulta error y registros QA.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--web-port',type=int,default=18084)
    parser.add_argument('--db-port',type=int,default=55440)
    parser.add_argument('--keep-running',action='store_true')
    args=parser.parse_args();runner=None;error=None
    try:
        runner=Runner(args.project_dir,args.web_port,args.db_port,args.keep_running)
        runner.execute()
    except KeyboardInterrupt:error=PortabilityError('Interrumpido por el usuario; resultados parciales')
    except Exception as exception:error=exception
    finally:
        if runner:runner.finish(error)
    if error:
        print(runner.redact(str(error)) if runner else 'No se pudo preparar la prueba: '+str(error),file=sys.stderr)
        return 1
    return 0 if runner and runner.report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
