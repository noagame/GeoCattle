"""Verificaciones SQL V3 en una base temporal migrada. Todo se revierte.
V3_TEST_DATABASE_URL='postgresql://...' python database/tests/verify_v3_integrity.py
El URL es obligatorio y se usa exclusivamente para conexiones de prueba.
"""
import os
from uuid import uuid4
import psycopg


def main():
    dsn = os.environ.get("V3_TEST_DATABASE_URL")
    if not dsn:
        raise SystemExit("Defina V3_TEST_DATABASE_URL apuntando a una base de prueba migrada")
    passed = 0
    with psycopg.connect(dsn) as c:
        c.execute("BEGIN")
        def fail(sql, params=()):
            nonlocal passed
            try:
                with c.transaction():
                    c.execute(sql, params)
            except psycopg.Error:
                passed += 1
                return
            raise AssertionError("La base aceptó una operación inválida")
        def ok(sql, params=()):
            nonlocal passed
            row = c.execute(sql, params).fetchone()
            assert row[0], sql
            passed += 1
        owner, worker, vet, viewer, admin = [uuid4() for _ in range(5)]
        for user_id, role in [(owner,"owner"),(worker,"worker"),(vet,"veterinarian"),(viewer,"viewer"),(admin,"admin")]:
            c.execute("INSERT INTO users(id,username,password_hash,role) VALUES(%s,%s,'test-hash',%s)", (user_id,str(user_id)+"@v3.test",role))
        account = c.execute("INSERT INTO owner_accounts(owner_user_id,display_name,max_farms) VALUES(%s,'QA',2) RETURNING id", (owner,)).fetchone()[0]
        farm = c.execute("INSERT INTO farms(id,account_id,name,environment) VALUES(%s,%s,'V3 QA','simulation') RETURNING id", (uuid4(),account)).fetchone()[0]
        second = c.execute("INSERT INTO farms(id,account_id,name,environment) VALUES(%s,%s,'V3 QA 2','simulation') RETURNING id", (uuid4(),account)).fetchone()[0]
        fail("INSERT INTO farms(id,account_id,name,environment) VALUES(%s,%s,'Fuera de cupo','simulation')", (uuid4(),account))
        member = {}
        for user_id,role in [(worker,"worker"),(vet,"veterinarian"),(viewer,"viewer")]:
            member[user_id] = c.execute("INSERT INTO farm_memberships(farm_id,user_id,role_code,granted_by) VALUES(%s,%s,%s,%s) RETURNING id",(farm,user_id,role,owner)).fetchone()[0]
        fail("INSERT INTO farm_memberships(farm_id,user_id,role_code,granted_by) VALUES(%s,%s,'worker',%s)",(farm,worker,owner))
        animal=c.execute("INSERT INTO animals(id,farm_id,diio,name,orientation) VALUES(%s,%s,%s,'QA animal','milk') RETURNING id",(uuid4(),farm,'QA-'+str(uuid4()))).fetchone()[0]
        holding=c.execute("INSERT INTO animal_holdings(farm_id,animal_id,reason,valid_from) VALUES(%s,%s,'QA',now()-interval '30 days') RETURNING id",(farm,animal)).fetchone()[0]
        fail("INSERT INTO animal_holdings(farm_id,animal_id,reason) VALUES(%s,%s,'Superposición')",(second,animal))
        def request(actor,action="health_record",membership=None):
            return c.execute("""INSERT INTO change_requests(farm_id,requested_by,membership_id,action,animal_holding_id,animal_id,payload,idempotency_key,expected_version)
              VALUES(%s,%s,%s,%s,%s,%s,'{}',%s,1) RETURNING id""",(farm,actor,membership,action,holding,animal,uuid4())).fetchone()[0]
        req=request(worker,membership=member[worker])
        ok("SELECT NOT EXISTS(SELECT 1 FROM change_decisions WHERE request_id=%s)",(req,))
        fail("UPDATE change_requests SET payload='{}' WHERE id=%s",(req,))
        fail("INSERT INTO change_decisions(request_id,decided_by,decision) VALUES(%s,%s,'direct')",(req,worker))
        fail("INSERT INTO change_decisions(request_id,decided_by,decision) VALUES(%s,%s,'rejected')",(req,owner))
        fail("""INSERT INTO health_events(farm_id,animal_holding_id,request_id,event_type,operation,recorded_by,description)
          VALUES(%s,%s,%s,'vaccination','record',%s,'No aprobada')""",(farm,holding,req,worker))
        c.execute("INSERT INTO change_decisions(request_id,decided_by,decision) VALUES(%s,%s,'approved')",(req,owner))
        event=c.execute("""INSERT INTO health_events(farm_id,animal_holding_id,request_id,event_type,operation,recorded_by,description)
          VALUES(%s,%s,%s,'vaccination','record',%s,'Vacuna QA') RETURNING id""",(farm,holding,req,worker)).fetchone()[0]
        c.execute("INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES(%s,'health_events',%s)",(req,event))
        c.execute("SET CONSTRAINTS decision_application IMMEDIATE")
        c.execute("SET CONSTRAINTS decision_application DEFERRED")
        passed+=1
        fail("UPDATE health_events SET description='Sobrescrito' WHERE id=%s",(event,))
        fail("DELETE FROM health_events WHERE id=%s",(event,))
        fail("INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES(%s,'health_events',%s)",(req,event))
        fail("INSERT INTO change_decisions(request_id,decided_by,decision,reason) VALUES(%s,%s,'rejected','Duplicada')",(req,owner))
        vetreq=request(vet,membership=member[vet])
        c.execute("INSERT INTO change_decisions(request_id,decided_by,decision) VALUES(%s,%s,'direct')",(vetreq,vet))
        successor=c.execute("""INSERT INTO health_events(farm_id,animal_holding_id,request_id,event_type,operation,target_event_id,recorded_by,description)
          VALUES(%s,%s,%s,'vaccination','correct',%s,%s,'Corrección veterinario') RETURNING id""",(farm,holding,vetreq,event,vet)).fetchone()[0]
        c.execute("INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES(%s,'health_events',%s)",(vetreq,successor))
        ok("SELECT count(*)=1 FROM effective_health_events WHERE animal_holding_id=%s",(holding,))
        fail("""INSERT INTO change_requests(farm_id,requested_by,membership_id,action,animal_holding_id,animal_id,payload,idempotency_key)
          VALUES(%s,%s,%s,'health_record',%s,%s,'{}',%s)""",(farm,viewer,member[viewer],holding,animal,uuid4()))
        grant=c.execute("INSERT INTO trust_grants(farm_id,membership_id,action,granted_by) VALUES(%s,%s,'animal_report',%s) RETURNING id",(farm,member[worker],owner)).fetchone()[0]
        reportreq=request(worker,"animal_report",member[worker])
        c.execute("INSERT INTO change_decisions(request_id,decided_by,decision,trust_grant_id) VALUES(%s,%s,'direct',%s)",(reportreq,worker,grant))
        report=c.execute("INSERT INTO animal_reports(farm_id,animal_holding_id,request_id,description) VALUES(%s,%s,%s,'Reporte QA') RETURNING id",(farm,holding,reportreq)).fetchone()[0]
        c.execute("INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES(%s,'animal_reports',%s)",(reportreq,report))
        passed+=1
        fail("INSERT INTO trust_grants(farm_id,membership_id,action,granted_by) VALUES(%s,%s,'health_record',%s)",(farm,member[vet],owner))
        fail("INSERT INTO trust_grants(farm_id,membership_id,action,granted_by) VALUES(%s,%s,'animal_status',%s)",(farm,member[worker],worker))
        rejected=request(worker,"animal_status",member[worker])
        c.execute("INSERT INTO change_decisions(request_id,decided_by,decision,reason) VALUES(%s,%s,'rejected','Se solicita aclaración')",(rejected,owner))
        fail("INSERT INTO change_applications(request_id,entity_type,entity_id) VALUES(%s,'animals',%s)",(rejected,animal))
        # Comprueba la restricción diferida sin confirmar ninguna escritura de QA.
        unfulfilled=request(owner,"animal_status")
        try:
            with c.transaction():
                c.execute("INSERT INTO change_decisions(request_id,decided_by,decision) VALUES(%s,%s,'direct')",(unfulfilled,owner))
                c.execute("SET CONSTRAINTS decision_application IMMEDIATE")
        except psycopg.Error:
            passed+=1
        else:
            raise AssertionError("Una decisión sin aplicación superó la restricción diferida")
        fail("INSERT INTO change_requests(farm_id,requested_by,action,animal_holding_id,animal_id,payload,idempotency_key) VALUES(%s,%s,'health_record',%s,%s,'{}',%s)",(second,owner,holding,animal,uuid4()))
        sector=c.execute("INSERT INTO sectors(id,farm_id,name) VALUES(%s,%s,'QA sector') RETURNING id",(uuid4(),farm)).fetchone()[0]
        fail("INSERT INTO geofences(id,farm_id,sector_id,name,version,geometry,created_at) VALUES(%s,%s,%s,'Triángulo',1,ST_GeomFromText('POLYGON((0 0,1 0,1 1,0 0))',4326),now())",(uuid4(),farm,sector))
        fail("INSERT INTO auth_challenges(user_id,token_hash,purpose,expires_at,attempts) VALUES(%s,%s,'login',now()+interval '5 minutes',6)",(admin,str(uuid4())))
        c.rollback()
    print(f"{passed} comprobaciones SQL V3 correctas; todos los datos de prueba revertidos.")

if __name__ == "__main__":
    main()
