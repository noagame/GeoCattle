"""Farm-scoped change drafts and the replica's projection of queued revisions."""
import json
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from .db import get_db
from .mirror_api import queue_write
from .mirror_policy import DRAFTS, WRITE_DENIED
from .mirror_replay import replay_for
from .security import current_user
from .settings import settings
from .v3_api import ChangeIn, Strict, farm_scope, lock_change, scoped, submit
from .v3_security import execute, one, rows


router = APIRouter(prefix=DRAFTS, tags=['Borradores V3'])


class DraftIn(Strict):
    id: UUID
    action: Literal['animal_profile', 'health_record', 'health_schedule']
    animal_id: UUID
    payload: dict
    expected_version: int | None = Field(default=None, ge=1)


class RevisionIn(Strict):
    base_version: int = Field(ge=1)
    payload: dict


class FinishDraftIn(Strict):
    base_version: int | None = Field(default=None, ge=1)


def draft_actor(user):
    if user.role not in ('admin', 'owner', 'veterinarian'):
        raise HTTPException(403, 'Sin permiso para gestionar borradores')
    return farm_scope(user)


def replica_draft_actor(user):
    if settings().mirror_mode == 'replica' and (user.role != 'veterinarian' or not user.farm_id):
        raise HTTPException(403, WRITE_DENIED)


def queue_draft_item(request, db, user, ident, body):
    if settings().mirror_mode != 'replica':
        return None
    replica_draft_actor(user)
    lock_change(db, f'geocattle:mirror-draft:{user.id}:{ident}')
    draft = one(db, 'SELECT version FROM change_drafts WHERE id=:i AND farm_id=:f AND author_id=:u',
                i=ident, f=user.farm_id, u=user.id)
    previous = one(db, """SELECT o.id,o.path,o.body FROM mirror_outbox o
        WHERE o.kind='draft_revision' AND o.farm_id=:f AND o.actor_id=:u
          AND (o.path=:p AND o.body->>'id'=:draft OR nullif(split_part(o.path,'/',6),'')::uuid=:i)
          AND NOT EXISTS (SELECT 1 FROM mirror_inbox_results r WHERE r.outbox_id=o.id)
        ORDER BY o.created_at DESC,o.id DESC LIMIT 1""",
        i=ident, f=user.farm_id, u=user.id, p=DRAFTS, draft=str(ident))
    if not draft and not previous:
        raise HTTPException(404, 'Borrador no encontrado')
    payload = body.model_dump(mode='json', exclude_none=True)
    if 'base_version' not in payload:
        if previous:
            payload['base_version'] = 1 if previous['path'] == DRAFTS else previous['body']['base_version'] + 1
        else:
            payload['base_version'] = draft['version']
    payload['after_outbox_id'] = str(previous['id']) if previous else None
    return queue_write(request, db, user, payload)


def draft_for_update(db, user, ident):
    draft = one(db, 'SELECT * FROM change_drafts WHERE id=:i AND farm_id=:f AND author_id=:u FOR UPDATE',
                i=ident, f=draft_actor(user), u=user.id)
    if not draft:
        raise HTTPException(404, 'Borrador no encontrado')
    return draft


def draft_payload(payload):
    try:
        return json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(422, 'El borrador requiere un objeto JSON válido') from None


def insert_draft(db, *, ident, farm, author, action, animal, expected_version, payload, conflict_of=None):
    return one(db, """INSERT INTO change_drafts(id,farm_id,author_id,action,animal_id,expected_version,payload,conflict_of)
        VALUES(:i,:f,:u,:a,:animal,:v,CAST(:p AS jsonb),:conflict) RETURNING *""", i=ident, f=farm, u=author,
        a=action, animal=animal, v=expected_version, p=draft_payload(payload), conflict=conflict_of)


def apply_pending_revisions(db, user, drafts):
    by_id = {draft['id']: draft for draft in drafts}
    pending = rows(db, """SELECT o.method,o.path,o.body,o.created_at FROM mirror_outbox o
        WHERE o.kind='draft_revision' AND o.actor_id=:u AND o.farm_id=:f
          AND NOT EXISTS (SELECT 1 FROM mirror_inbox_results r WHERE r.outbox_id=o.id)
        ORDER BY o.created_at,o.id""", u=user.id, f=user.farm_id)
    for revision in pending:
        body = revision['body']
        if revision['path'] == DRAFTS:
            ident = UUID(body['id'])
            by_id.setdefault(ident, {'id': ident, 'farm_id': user.farm_id, 'author_id': user.id,
                'action': body['action'], 'animal_id': body['animal_id'], 'payload': body['payload'],
                'expected_version': body.get('expected_version'), 'version': 1, 'conflict_of': None,
                'request_id': None, 'status': 'draft', 'created_at': revision['created_at']})
        else:
            ident = UUID(revision['path'][len(DRAFTS) + 1:].split('/')[0])
        draft = by_id.get(ident)
        if draft is None:
            continue
        operation = 'save'
        if revision['method'] == 'PUT':
            draft.update(payload=body['payload'], version=body['base_version'] + 1)
        elif revision['path'] != DRAFTS:
            operation = 'discard' if revision['method'] == 'DELETE' else 'submit'
            draft.update(version=body['base_version'] + 1)
        draft.update(status='pending_sync', pending_sync=True, pending_operation=operation,
                     updated_at=revision['created_at'])
    return sorted(by_id.values(), key=lambda item: (item['updated_at'], item['id']), reverse=True)


@router.get('')
def list_drafts(user=Depends(current_user), db=Depends(get_db, scope='function')):
    drafts = rows(db, """SELECT * FROM change_drafts WHERE farm_id=:f AND author_id=:u
        ORDER BY updated_at DESC,id DESC""", f=draft_actor(user), u=user.id)
    if settings().mirror_mode == 'replica':
        drafts = apply_pending_revisions(db, user, drafts)
    return {'items': drafts, 'total': len(drafts)}


@router.post('', status_code=201)
def create_draft(body: DraftIn, request: Request, user=Depends(current_user), db=Depends(get_db, scope='function')):
    replica_draft_actor(user)
    farm_id = draft_actor(user)
    if settings().mirror_mode == 'replica':
        lock_change(db, f'geocattle:mirror-draft:{user.id}:{body.id}')
    else:
        lock_change(db, f'geocattle:draft-create:{body.id}')
        old = one(db, 'SELECT * FROM change_drafts WHERE id=:i', i=body.id)
        if old:
            if (old['farm_id'] == farm_id and old['author_id'] == user.id and old['action'] == body.action
                    and old['animal_id'] == body.animal_id and old['payload'] == body.payload
                    and (body.expected_version is None or old['expected_version'] == body.expected_version)):
                return old
            raise HTTPException(409, 'El identificador del borrador ya está en uso')
    animal = scoped(db, 'animals', body.animal_id, user)
    expected_version = body.expected_version or animal['version']
    queued = queue_write(request, db, user, body.model_copy(update={'expected_version': expected_version}))
    if queued is not None:
        return queued
    return insert_draft(db, ident=body.id, farm=farm_id, author=user.id, action=body.action,
                        animal=animal['id'], expected_version=expected_version, payload=body.payload)


@router.put('/{ident}')
def revise_draft(ident: UUID, body: RevisionIn, request: Request, user=Depends(current_user), db=Depends(get_db, scope='function')):
    queued = queue_draft_item(request, db, user, ident, body)
    if queued is not None:
        return queued
    draft = draft_for_update(db, user, ident)
    if body.base_version != draft['version']:
        sibling = insert_draft(db, ident=uuid4(), farm=draft['farm_id'], author=user.id, action=draft['action'],
                               animal=draft['animal_id'], expected_version=draft['expected_version'],
                               payload=body.payload, conflict_of=ident)
        return JSONResponse(status_code=409, content={'detail': 'La revisión se guardó en un borrador separado',
                                        'draft_id': str(ident), 'conflict_id': str(sibling['id'])})
    if draft['status'] != 'draft':
        raise HTTPException(409, 'El borrador ya está cerrado')
    return one(db, """UPDATE change_drafts SET payload=CAST(:p AS jsonb),version=version+1,updated_at=now()
        WHERE id=:i RETURNING *""", i=ident, p=draft_payload(body.payload))


@router.post('/{ident}/submit')
def submit_draft(ident: UUID, request: Request, body: FinishDraftIn | None = None,
                 user=Depends(current_user), db=Depends(get_db, scope='function')):
    queued = queue_draft_item(request, db, user, ident, body or FinishDraftIn())
    if queued is not None:
        return queued
    draft = draft_for_update(db, user, ident)
    conflict = finish_version_conflict(draft, body)
    if conflict is not None:
        return conflict
    if draft['status'] == 'submitted':
        decision = one(db, 'SELECT decision FROM change_decisions WHERE request_id=:i', i=draft['request_id'])
        state = 'pending' if not decision else 'rejected' if decision['decision'] == 'rejected' else 'applied'
        return {**draft, 'request_status': state}
    if draft['status'] != 'draft':
        raise HTTPException(409, 'El borrador ya está cerrado')
    change = ChangeIn(action=draft['action'], animal_id=draft['animal_id'], expected_version=draft['expected_version'],
                      payload=draft['payload'], idempotency_key=ident)
    replay = replay_for(request)
    result = submit(change, user, db, remote=replay is not None and replay.kind == 'draft_revision')
    updated = one(db, """UPDATE change_drafts SET status='submitted',request_id=:r,version=version+1,updated_at=now()
        WHERE id=:i RETURNING *""", i=ident, r=result['id'])
    return {**updated, 'request_status': result['status']}


@router.delete('/{ident}')
def discard_draft(ident: UUID, request: Request, body: FinishDraftIn | None = None,
                  user=Depends(current_user), db=Depends(get_db, scope='function')):
    queued = queue_draft_item(request, db, user, ident, body or FinishDraftIn())
    if queued is not None:
        return queued
    draft = draft_for_update(db, user, ident)
    conflict = finish_version_conflict(draft, body)
    if conflict is not None:
        return conflict
    if draft['status'] == 'discarded':
        return draft
    if draft['status'] != 'draft':
        raise HTTPException(409, 'El borrador ya está cerrado')
    return one(db, """UPDATE change_drafts SET status='discarded',version=version+1,updated_at=now()
        WHERE id=:i RETURNING *""", i=ident)


def finish_version_conflict(draft, body):
    if body and body.base_version is not None and body.base_version != draft['version']:
        return JSONResponse(status_code=409, content={'detail': 'El borrador cambió en el PC del campo',
                            'draft_id': str(draft['id']), 'version': draft['version']})
    return None
