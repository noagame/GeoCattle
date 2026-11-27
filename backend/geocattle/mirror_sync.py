"""Field worker that replays mirror submissions and publishes their outcomes."""
import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

import httpx
from cryptography.fernet import InvalidToken
from pydantic import BaseModel, Field, ValidationError

from .db import SessionLocal
from .mirror_policy import CREATE_OWNER, DRAFTS, WRITE_DENIED, kind_enabled, owner_password_cipher, write_kind
from .mirror_replay import Replay, replay_transport
from .models import utcnow
from .settings import settings
from .v3_security import audit, execute, one


log = logging.getLogger('geocattle.mirror')
_RESULT_FIELDS = frozenset({'id', 'status', 'detail', 'request_id', 'request_status', 'decision',
                            'entity_id', 'entity_type', 'draft_id', 'conflict_id', 'version'})


class Submission(BaseModel):
    id: UUID
    kind: Literal['admin_order', 'remote_change', 'draft_revision', 'support_request']
    actor_id: UUID
    farm_id: UUID | None
    method: Literal['POST', 'PUT', 'PATCH', 'DELETE']
    path: str = Field(max_length=250)
    body: dict


class ReplayFailure(Exception):
    def __init__(self, status):
        self.status = status


async def send_replay(app, replay, host, item, body):
    transport = httpx.ASGITransport(app=replay_transport(app, replay))
    async with httpx.AsyncClient(transport=transport, base_url=f'https://{host}') as client:
        return await client.request(item.method, item.path, json=body)


def replay_request(db, item):
    expected = write_kind(item.method, item.path, item.body, platform_admin=item.kind == 'admin_order',
                          veterinarian=item.kind in ('remote_change', 'draft_revision'))
    if (expected != item.kind or not kind_enabled(item.kind)
            or (item.kind == 'support_request' and item.farm_id is not None)):
        return 403, {'detail': WRITE_DENIED}
    body = item.body.copy()
    if item.kind == 'draft_revision':
        after = body.pop('after_outbox_id', None)
        if after is not None:
            try:
                previous_id = UUID(after)
                draft_id = UUID(item.path[len(DRAFTS) + 1:].split('/')[0])
                if previous_id == item.id:
                    raise ValueError
            except (AttributeError, TypeError, ValueError):
                return 422, {'detail': 'Dependencia de borrador inválida'}
            previous = one(db, 'SELECT status,kind,actor_id,result FROM mirror_inbox_results WHERE outbox_id=:i',
                           i=previous_id)
            if previous is None:
                return None
            if (previous['status'] != 'applied' or previous['kind'] != 'draft_revision'
                    or previous['actor_id'] != item.actor_id or previous['result'].get('id') != str(draft_id)):
                return 409, {'detail': 'La revisión anterior del borrador no se aplicó', 'draft_id': str(draft_id)}
    if item.path == CREATE_OWNER:
        try:
            password = owner_password_cipher().decrypt(body['password'].encode('ascii')).decode()
        except (InvalidToken, KeyError, AttributeError, UnicodeError):
            return 422, {'detail': 'Contraseña de la orden de alta inválida'}
        body = {**body, 'password': password}

    from .main import app

    # Use a Host accepted by the field deployment's normal middleware.
    host = next((host.strip() for host in settings().allowed_hosts.split(',') if host.strip()), '*')
    host = host.replace('*', 'mirror-worker')
    replay = Replay(db, item.id, item.actor_id, item.farm_id, item.kind)
    response = asyncio.run(send_replay(app, replay, host, item, body))
    code = response.status_code
    if not (200 <= code < 300 or 400 <= code < 500):
        raise ReplayFailure(code)
    return code, response.json()


def result_status(code, body, kind):
    if code == 409 and 'draft_id' in body:
        return 'conflict'
    if 400 <= code < 500:
        return 'rejected'
    if not 200 <= code < 300:
        return 'failed'
    if kind != 'support_request' and (body.get('status') == 'pending' or body.get('request_status') == 'pending'):
        return 'pending_owner'
    return 'applied'


def apply_submission(item):
    with SessionLocal.begin() as db:
        # The lock, the API transaction and the immutable result share one PostgreSQL transaction.
        execute(db, 'SELECT pg_advisory_xact_lock(hashtextextended(:key,0))', key=f'geocattle:mirror-inbox:{item.id}')
        previous = one(db, 'SELECT status FROM mirror_inbox_results WHERE outbox_id=:i', i=item.id)
        if previous:
            return previous['status']

        try:
            with db.begin_nested():
                outcome = replay_request(db, item)
                if outcome is None:
                    return None
                code, body = outcome
                status = result_status(code, body, item.kind)
                if status == 'failed':
                    raise ReplayFailure(code)
                if item.kind == 'admin_order' and status == 'applied':
                    actor = SimpleNamespace(id=item.actor_id, farm_id=item.farm_id)
                    audit(db, actor, 'remote_admin', 'mirror_outbox', item.id,
                          after={'method': item.method, 'path': item.path})
        except Exception as exc:
            log.warning('Falló la reproducción del envío %s (%s)', item.id, type(exc).__name__)
            code = exc.status if isinstance(exc, ReplayFailure) else 500
            status, body = 'failed', {'detail': 'No se pudo aplicar el envío en el PC del campo'}

        result = {key: value[:1000] if isinstance(value, str) else value
                  for key, value in body.items() if key in _RESULT_FIELDS}
        execute(db, """INSERT INTO mirror_inbox_results(outbox_id,kind,actor_id,status,http_status,result)
            VALUES(:i,:k,:u,:s,:code,CAST(:r AS jsonb))""", i=item.id, k=item.kind, u=item.actor_id,
            s=status, code=code, r=json.dumps(result))
        return status


def publish_heartbeat(db, checked_at=None, details=None):
    execute(db, """INSERT INTO mirror_heartbeat(source,at,schema_version,inbox_checked_at,details)
        VALUES(:s,clock_timestamp(),coalesce((SELECT max(version) FROM schema_migrations),'unknown'),:c,
               coalesce(CAST(:d AS jsonb),'{}'::jsonb))
        ON CONFLICT (source) DO UPDATE SET at=excluded.at,schema_version=excluded.schema_version,
            inbox_checked_at=coalesce(excluded.inbox_checked_at,mirror_heartbeat.inbox_checked_at),
            details=coalesce(CAST(:d AS jsonb),mirror_heartbeat.details)""", s=settings().mirror_source,
        c=checked_at, d=json.dumps(details) if details is not None else None)


def fetch_inbox(config):
    headers = {'X-Mirror-Key': config.mirror_sync_key.encode()}
    if config.mirror_access_id:
        headers.update({'CF-Access-Client-Id': config.mirror_access_id.encode(),
                        'CF-Access-Client-Secret': config.mirror_access_secret.encode()})
    response = httpx.get(config.mirror_server_url + '/api/v1/mirror/inbox', headers=headers,
                         params={'limit': 50}, timeout=8, follow_redirects=False)
    response.raise_for_status()
    items = response.json()['items']
    if not isinstance(items, list) or len(items) > 50:
        raise ValueError('Bandeja de espejo inválida')
    return items


def run_mirror_cycle():
    config = settings()
    try:
        with SessionLocal.begin() as db:
            publish_heartbeat(db)
        with SessionLocal.begin() as drain_lock:
            # Preserve inbox ordering even when two field workers are running.
            if not one(drain_lock, 'SELECT pg_try_advisory_xact_lock(804193813) AS acquired')['acquired']:
                return
            checked_at = utcnow()
            details = {'inbox': 'unavailable'}
            try:
                items = fetch_inbox(config)
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                log.warning('No se pudo consultar la bandeja espejo (%s)', type(exc).__name__)
            else:
                details = {'inbox': 'checked', 'received': len(items), 'deferred': 0, 'results': {}}
                for raw in items:
                    try:
                        status = apply_submission(Submission.model_validate(raw))
                    except ValidationError:
                        log.warning('La bandeja espejo devolvió un envío inválido')
                        continue
                    if status is None:
                        details['deferred'] += 1
                        continue
                    counts = details['results']
                    counts[status] = counts.get(status, 0) + 1
            with SessionLocal.begin() as db:
                publish_heartbeat(db, checked_at, details)
    except Exception as exc:
        log.warning('Ciclo espejo interrumpido, se reintentará (%s)', type(exc).__name__)
