"""Server-side filters, KPI denominators and request correlation."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from geocattle.v3_security import totp
from test_v3_api import PASSWORD, v3

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Requiere PostgreSQL/PostGIS V3 de prueba')


def admin_client(v3):
    client=v3.client('admin',login=False)
    challenge=client.post('/api/v1/auth/login',json={'username':v3.users['admin'].username,'password':PASSWORD}).json()
    response=client.post('/api/v1/auth/mfa/verify',json={'challenge_token':challenge['challenge_token'],'code':totp(challenge['secret'])})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf_token']
    return client


def test_kpi_period_account_farm_and_current_holding(v3):
    client=admin_client(v3)
    first=v3.farms['owner'];other=v3.farms['other_owner']
    for farm,code,duration in [(first,200,100),(first,503,900),(other,200,1)]:
        v3.db.execute(text("INSERT INTO request_metrics(id,account_id,farm_id,actor_id,request_id,method,route_template,status_code,duration_ms,request_bytes,response_bytes,occurred_at) VALUES(:i,(SELECT account_id FROM farms WHERE id=:f),:f,:u,:r,'GET','/test',:s,:d,40,80,'2026-10-15T10:00:00Z')"),{'i':uuid4(),'f':farm.id,'u':v3.users['owner'].id,'r':str(uuid4()),'s':code,'d':duration})
    response=client.get('/api/v1/v3/admin/kpis',params={'account_id':str(first.account_id),'farm_id':str(first.id),'start':'2026-10-15T00:00:00Z','end':'2026-10-16T00:00:00Z'})
    assert response.status_code==200,response.text
    data=response.json()
    assert data['users']==4 and data['animals']==1 and data['farms']==1
    assert data['requests']==2 and data['error_requests']==1
    assert data['usage_24h']['request_bytes']==80 and data['usage_24h']['response_bytes']==160
    assert data['usage_24h']['p95_ms']==860
    assert data['generated_at'] and data['period']['start'].startswith('2026-10-15')
    assert str(first.id) in {item['id'] for item in data['farm_options']}
    mismatch=client.get('/api/v1/v3/admin/kpis',params={'account_id':str(first.account_id),'farm_id':str(other.id)})
    assert mismatch.status_code==422
    assert client.get('/api/v1/v3/admin/kpis?start=2026-10-15T00:00:00&end=2026-10-16T00:00:00Z').status_code==422
    assert client.get('/api/v1/v3/admin/kpis?start=2026-10-17T00:00:00Z&end=2026-10-16T00:00:00Z').status_code==422


def test_audit_filters_are_server_side_and_preserve_owner_scope(v3):
    client=admin_client(v3);owner=v3.client('owner')
    for name in ('owner','other_owner'):
        v3.db.execute(text("INSERT INTO audit_log(id,farm_id,actor_id,object_type,object_id,action,at) VALUES(gen_random_uuid(),:f,:u,'qa_entity','1','lookup_target','2026-10-15T10:00:00Z')"),{'f':v3.farms[name].id,'u':v3.users[name].id})
    # More than one page is present, but the date/actor/action/entity search is global.
    v3.db.execute(text("INSERT INTO audit_log(id,farm_id,actor_id,object_type,object_id,action,at) SELECT gen_random_uuid(),:f,:u,'qa_other',n::text,'lookupXtarget','2026-10-15T10:00:00Z' FROM generate_series(1,105) n"),{'f':v3.farms['owner'].id,'u':v3.users['owner'].id})
    params={'q':'lookup_target','actor_id':str(v3.users['owner'].id),'entity':'qa_entity','action':'lookup_target','start':'2026-10-15T00:00:00Z','end':'2026-10-16T00:00:00Z','limit':1}
    response=client.get('/api/v1/v3/audit',params=params)
    assert response.status_code==200,response.text
    assert response.json()['total']==1 and len(response.json()['items'])==1
    assert response.json()['items'][0]['action']=='lookup_target'
    limited=owner.get('/api/v1/v3/audit',params={'q':'lookup_target'})
    assert limited.status_code==200 and limited.json()['total']==1,limited.text
    assert owner.get('/api/v1/v3/audit',params={'farm_id':str(v3.farms['other_owner'].id)}).status_code==403
    assert client.get('/api/v1/v3/audit?limit=101').status_code==422


def test_audit_export_reuses_filters_scope_and_is_audited(v3):
    from io import BytesIO
    from openpyxl import load_workbook
    client=admin_client(v3);owner=v3.client('owner');worker=v3.client('worker')
    for name in ('owner','other_owner'):
        v3.db.execute(text("INSERT INTO audit_log(id,farm_id,actor_id,object_type,object_id,action,at,after) VALUES(gen_random_uuid(),:f,:u,'qa_export','=1+1','export_target','2026-10-15T10:00:00Z',CAST(:a AS jsonb))"),
                      {'f':v3.farms[name].id,'u':v3.users[name].id,'a':'{"note": "ñandú"}'})
    v3.db.commit()
    params={'entity':'qa_export','start':'2026-10-15T00:00:00Z','end':'2026-10-16T00:00:00Z'}
    route='/api/v1/v3/audit/export'
    assert worker.get(route,params=params).status_code==403
    assert owner.get(route,params={**params,'farm_id':str(v3.farms['other_owner'].id)}).status_code==403
    response=owner.get(route,params={**params,'format':'xlsx'})
    assert response.status_code==200,response.text
    assert 'geocattle-auditoria.xlsx' in response.headers['content-disposition']
    sheet=load_workbook(BytesIO(response.content))['Auditoría']
    values=list(sheet.values)
    assert values[0][:6]==('Fecha','Actor','Usuario','Entidad','Identificador','Acción')
    assert len(values)==2 and values[1][3]=='qa_export' and values[1][4]=='=1+1'
    assert values[1][6]==v3.farms['owner'].name and 'ñandú' in values[1][8]
    csv=owner.get(route,params={**params,'format':'csv','delimiter':'semicolon'})
    assert csv.status_code==200 and csv.headers['content-type'].startswith('text/csv')
    lines=csv.content.decode('utf-8-sig').splitlines()
    assert lines[0].startswith('Fecha;Actor;') and len(lines)==2 and ";'=1+1;" in lines[1]
    platform=client.get(route,params={**params,'format':'csv'})
    assert platform.status_code==200 and len(platform.content.decode('utf-8-sig').splitlines())==3
    logged=v3.db.execute(text("SELECT after FROM audit_log WHERE action='export_audit' AND actor_id=:u"),{'u':v3.users['owner'].id}).scalars().all()
    assert sorted(logged,key=lambda item:item['format'])==[{'scope':'farm','format':'csv','rows':1},{'scope':'farm','format':'xlsx','rows':1}]


def test_response_request_id_matches_persisted_metric(v3):
    client=v3.client('owner')
    response=client.get('/api/v1/v3/profile')
    assert response.status_code==200
    request_id=response.headers['X-Request-ID']
    saved=v3.db.execute(text('SELECT route_template,status_code,actor_id FROM request_metrics WHERE request_id=:r'),{'r':request_id}).one()
    assert saved.route_template=='/api/v1/v3/profile' and saved.status_code==200
    assert saved.actor_id==v3.users['owner'].id
