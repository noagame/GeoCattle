"""Replica write queue, field inbox, and mirror status endpoints."""
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .db import get_db
from .mirror_policy import CHANGES, CREATE_OWNER, WRITE_DENIED, kind_enabled, owner_password_cipher, write_kind, write_target
from .mirror_tables import SUBSCRIPTION
from .models import utcnow
from .security import current_user, matches_secret_header
from .settings import settings
from .v3_security import audit, execute, one, rows


router = APIRouter(prefix='/api/v1/mirror', tags=['Modo espejo'])


def blocks_write(request):
    path = request.url.path
    return (settings().mirror_mode == 'replica'
            and (path == '/api' or path.startswith('/api/'))
            and request.method not in ('GET', 'HEAD', 'OPTIONS')
            and write_target(request.method, path) is None)


def previous_change(db, user, path, payload):
    key = payload['idempotency_key']
    execute(db, 'SELECT pg_advisory_xact_lock(hashtextextended(:key,0))',
            key=f'geocattle:mirror-change:{user.id}:{key}')
    previous = one(db, """SELECT id,farm_id,body FROM mirror_outbox
        WHERE actor_id=:u AND method='POST' AND path=:p AND body->>'idempotency_key'=:k
        ORDER BY created_at,id LIMIT 1""", u=user.id, p=path, k=key)
    if previous is not None and (previous['farm_id'] != user.farm_id or previous['body'] != payload):
        raise HTTPException(409, 'La clave de idempotencia ya representa otra operación')
    return previous


def queue_write(request, db, user, body):
    config = settings()
    if config.mirror_mode != 'replica':
        return None
    payload = body if isinstance(body, dict) else body.model_dump(mode='json', exclude_unset=True)
    method, path = request.method, request.url.path
    kind = write_kind(method, path, payload, platform_admin=user.base_role == 'admin',
                      veterinarian=user.role == 'veterinarian' and user.farm_id is not None)
    if kind is None or not kind_enabled(kind):
        raise HTTPException(403, WRITE_DENIED)
    previous = previous_change(db, user, path, payload) if path == CHANGES else None
    if previous is not None:
        return JSONResponse(status_code=202, content={'queued': True, 'outbox_id': str(previous['id']), 'status': 'queued'})
    ident = uuid4()
    if path == CREATE_OWNER:
        # Keep the temporary password out of the durable queue and audit in clear text.
        secret = owner_password_cipher().encrypt(payload['password'].encode()).decode('ascii')
        payload = {**payload, 'password': secret}
    try:
        encoded = json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(422, 'El envío requiere un objeto JSON válido') from None
    farm_id = None if kind == 'support_request' else user.farm_id
    execute(db, """INSERT INTO mirror_outbox(id,kind,actor_id,farm_id,method,path,body,created_at)
        VALUES(:i,:k,:u,:f,:m,:p,CAST(:b AS jsonb),clock_timestamp())""", i=ident, k=kind, u=user.id, f=farm_id,
        m=method, p=path, b=encoded)
    audit(db, SimpleNamespace(id=user.id, farm_id=farm_id), 'mirror_queued', 'mirror_outbox', ident,
          after={'kind': kind, 'method': method, 'path': path})
    return JSONResponse(status_code=202, content={'queued': True, 'outbox_id': str(ident), 'status': 'queued'})


def heartbeat(db):
    return one(db, 'SELECT * FROM mirror_heartbeat WHERE source=:source', source=settings().mirror_source)


def info_body(config, pulse):
    if config.mirror_mode == 'off':
        return {'mode': 'off'}
    at = pulse['at'] if pulse else None
    return {'mode': config.mirror_mode, 'source_environment': config.visible_farm_environment,
            'heartbeat_at': at, 'field_online': at is not None and utcnow() - at < timedelta(seconds=60)}


@router.get('/info')
def info(_user=Depends(current_user), db=Depends(get_db, scope='function')):
    config = settings()
    return info_body(config, heartbeat(db) if config.mirror_mode != 'off' else None)


@router.get('/submissions')
def submissions(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                user=Depends(current_user), db=Depends(get_db, scope='function')):
    if settings().mirror_mode != 'replica':
        return {'items': [], 'total': 0}
    # Una solicitud pendiente del dueño refleja después su decisión replicada desde el PC.
    items = rows(db, """SELECT o.id AS outbox_id,o.kind,o.farm_id,o.method,o.path,o.created_at,o.delivered_at,
        CASE WHEN d.decision='approved' THEN 'applied' WHEN d.decision='rejected' THEN 'rejected'
             ELSE coalesce(r.status,o.status) END AS status,
        r.http_status,
        CASE WHEN d.reason IS NOT NULL THEN coalesce(r.result,'{}'::jsonb) || jsonb_build_object('reason',d.reason)
             ELSE r.result END AS result,
        coalesce(d.created_at,r.applied_at) AS applied_at
        FROM mirror_outbox o LEFT JOIN mirror_inbox_results r ON r.outbox_id=o.id
        LEFT JOIN LATERAL (SELECT CASE WHEN r.kind='draft_revision' THEN r.result->>'request_id'
                                     ELSE r.result->>'id' END AS id) change ON r.status='pending_owner'
        LEFT JOIN change_decisions d ON d.request_id=CASE WHEN change.id ~ '^[0-9a-f-]{36}$' THEN change.id::uuid END
        WHERE o.actor_id=:u
        ORDER BY o.created_at DESC,o.id DESC LIMIT :limit OFFSET :offset""", u=user.id, limit=limit, offset=offset)
    total = one(db, 'SELECT count(*) AS n FROM mirror_outbox WHERE actor_id=:u', u=user.id)['n']
    return {'items': items, 'total': total}


@router.get('/status')
def status(user=Depends(current_user), db=Depends(get_db, scope='function')):
    if user.base_role != 'admin':
        raise HTTPException(403, 'Se requiere administrador de plataforma')
    config = settings()
    pulse = heartbeat(db) if config.mirror_mode != 'off' else None
    subscription = None
    counts = {}
    if config.mirror_mode == 'replica':
        counts = {row['status']: row['n'] for row in rows(db, """SELECT coalesce(r.status,o.status) AS status,count(*) AS n
            FROM mirror_outbox o LEFT JOIN mirror_inbox_results r ON r.outbox_id=o.id GROUP BY 1""")}
        if one(db, "SELECT has_table_privilege('pg_catalog.pg_stat_subscription','SELECT') AS visible")['visible']:
            subscription = one(db, """SELECT received_lsn::text,latest_end_lsn::text,last_msg_receipt_time,latest_end_time,
                CASE WHEN latest_end_time IS NOT NULL THEN greatest(0,extract(epoch FROM now()-latest_end_time)) END AS lag_seconds
                FROM pg_catalog.pg_stat_subscription WHERE subname=:s AND relid IS NULL
                  AND (received_lsn IS NOT NULL OR last_msg_send_time IS NOT NULL) LIMIT 1""", s=SUBSCRIPTION)
    return {**info_body(config, pulse), 'heartbeat': pulse, 'submission_counts': counts,
            'subscription': subscription}


@router.get('/inbox')
def inbox(request: Request, limit: int = Query(50, ge=1, le=100), db=Depends(get_db, scope='function')):
    config = settings()
    if config.mirror_mode != 'replica':
        raise HTTPException(404, 'Bandeja espejo no disponible')
    if not matches_secret_header(request, 'X-Mirror-Key', config.mirror_sync_key):
        raise HTTPException(401, 'Credencial de sincronización inválida')
    items = rows(db, """WITH pending AS (
        SELECT o.id FROM mirror_outbox o
        WHERE NOT EXISTS (SELECT 1 FROM mirror_inbox_results r WHERE r.outbox_id=o.id)
        ORDER BY o.created_at,o.id LIMIT :limit FOR UPDATE OF o SKIP LOCKED
    ), delivered AS (
        UPDATE mirror_outbox o SET status='delivered',delivered_at=coalesce(o.delivered_at,now()),attempts=o.attempts+1
        FROM pending p WHERE o.id=p.id RETURNING o.id,o.kind,o.actor_id,o.farm_id,o.method,o.path,o.body,o.created_at
    ) SELECT * FROM delivered ORDER BY created_at,id""", limit=limit)
    return {'items': items}
