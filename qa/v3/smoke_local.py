"""Read-only local deployment checks; passwords/tokens never enter the report."""
import hashlib
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[2]
config=dotenv_values(ROOT/'.env')
report={'checked_at':datetime.now(timezone.utc).isoformat(),'origin':'http://localhost:8080','checks':{}}
with httpx.Client(base_url=report['origin'],timeout=20) as client:
    home=client.get('/');assert home.status_code==200
    report['checks']['web']=home.status_code
    health=client.get('/api/v1/health');assert health.status_code==200
    report['checks']['health']=health.status_code
    assert client.get('/api/v1/v3/admin/kpis').status_code==401
    report['checks']['anonymous_admin_denied']=True
    response=client.post('/api/v1/auth/login',json={'username':'demo@geocattle.local','password':config['DEMO_PASSWORD']})
    assert response.status_code==200
    session=response.json();assert session['user']['role']=='owner'
    client.headers['X-CSRF-Token']=session['csrf_token']
    counts={}
    for route in ('dashboard','v3/profile','v3/farms','animals?limit=1','devices?limit=1','v3/notifications'):
        result=client.get('/api/v1/'+route);assert result.status_code==200,(route,result.status_code)
        report['checks'][route]=result.status_code
        if route.startswith('animals?'):counts['animals']=result.json()['total']
        if route.startswith('devices?'):counts['devices']=result.json()['total']
    report['owner_list_counts']=counts
    assert client.get('/api/v1/v3/admin/users').status_code==403
    report['checks']['owner_global_admin_denied']=True
    denied=client.post('/api/v1/v3/invitations',json={'email':'no-se-crea@qa.invalid','role_code':'worker'})
    assert denied.status_code==403
    report['checks']['sensitive_write_without_operation_token_denied']=True
    assert client.post('/api/v1/auth/logout').status_code==204
    assert client.get('/api/v1/v3/profile').status_code==401
    report['checks']['logout_revoked']=True

source_script="""import hashlib,json,pathlib
p=pathlib.Path('/app/geocattle')
print(json.dumps({x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in p.glob('*.py')}))"""
process=subprocess.run(['docker','exec','geocattle-simulation-api-1','python','-c',source_script],check=True,capture_output=True,text=True)
actual=json.loads(process.stdout)
expected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'backend/geocattle').glob('*.py')}
assert actual==expected,'La imagen API no coincide con el código fuente final'
report['checks']['deployed_source_matches']=len(actual)

sql_script="""import json
from sqlalchemy import text
from geocattle.db import engine
with engine.connect() as c:
 print(json.dumps({'animals':c.scalar(text('SELECT count(*) FROM animals')),'devices':c.scalar(text('SELECT count(*) FROM devices')),'telemetry':c.scalar(text('SELECT count(*) FROM telemetry')),'application_tables':c.scalar(text(\"SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name NOT IN ('schema_migrations','spatial_ref_sys')\"))}))
"""
result=subprocess.run(['docker','exec','geocattle-simulation-api-1','python','-c',sql_script],check=True,capture_output=True,text=True)
report['database_counts']=json.loads(result.stdout)
assert report['database_counts']=={'animals':70,'devices':70,'telemetry':569,'application_tables':48}
(ROOT/'qa/v3/live_smoke.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(report,indent=2,ensure_ascii=False))
