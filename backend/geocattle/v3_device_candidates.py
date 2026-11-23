"""Review and register physical collar detections in the active farm."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select

from .db import get_db
from .device_candidates import (
    candidate_json, capture_farm, lock_device_identity, register_detection, suggested_device_name,
)
from .device_inventory import create_inventory_device, device_json
from .domain import append_audit
from .models import Device, Farm
from .schemas import DeviceCandidateApproval, DeviceCandidateIn, DeviceIn
from .security import current_user, owner, service_auth
from .settings import settings
from .v3_api import farm_scope
from .v3_security import one, rows

router = APIRouter(prefix='/api/v1/v3/device-candidates', tags=['Device candidates'])


@router.get('')
def list_candidates(status: Literal['pending', 'approved', 'dismissed'] = 'pending',
                    user=Depends(current_user), db=Depends(get_db, scope='function')):
    farm_id = farm_scope(user)
    detections = rows(db, """
        SELECT * FROM device_candidates
        WHERE farm_id = :farm AND status = :status ORDER BY last_seen_at DESC, id
    """, farm=farm_id, status=status)
    name = suggested_device_name(db, farm_id) if detections else None
    return {'items': [candidate_json(row, name) for row in detections]}


@router.get('/capture-farms')
def capture_farms(request: Request, db=Depends(get_db, scope='function')):
    """Physical farms the capture credential may target, so the USB assistant can offer a choice."""
    service_auth(request)
    environment = settings().app_env
    if environment == 'simulation':
        raise HTTPException(403, 'Simulación no admite detecciones de hardware físico')
    farms = db.execute(select(Farm.id, Farm.name).where(Farm.environment == environment, Farm.active)
                       .order_by(Farm.name, Farm.id)).all()
    return {'items': [{'id': str(farm.id), 'name': farm.name.strip()} for farm in farms]}


@router.post('', status_code=201)
def register_candidate(body: DeviceCandidateIn, request: Request,
                       farm_id: UUID | None = Header(default=None, alias='X-Farm-ID'),
                       db=Depends(get_db, scope='function')):
    actor = None
    if 'X-Ingest-Key' in request.headers:
        service_auth(request)
    else:
        # Browser writes use the active farm, CSRF and the inventory's session policy.
        user = owner(current_user(request, db))
        farm_id, actor = farm_scope(user), user.id
    farm_id = capture_farm(db, farm_id)
    candidate = register_detection(db, farm_id, body, actor)
    return candidate_json(candidate, suggested_device_name(db, farm_id))


def lock_candidate(db, ident, farm_id):
    params = {'ident': ident, 'farm': farm_id}
    where = ' WHERE id = :ident AND farm_id = :farm'
    candidate = one(db, 'SELECT hardware_id FROM device_candidates' + where, **params)
    if not candidate:
        raise HTTPException(403, 'Recurso no autorizado en este predio')
    lock_device_identity(db, candidate['hardware_id'])
    return one(db, 'SELECT * FROM device_candidates' + where + ' FOR UPDATE', **params)


def resolve_candidate(db, candidate, user, status, device_id=None):
    resolved = one(db, """
        UPDATE device_candidates
        SET status = :status, resolved_at = now(), resolved_by = :actor, device_id = :device
        WHERE id = :ident AND farm_id = :farm RETURNING *
    """, status=status, actor=user.id, device=device_id, ident=candidate['id'], farm=user.farm_id)
    append_audit(db, user.farm_id, user.id, 'device_candidate', candidate['id'], {'approved': 'approve', 'dismissed': 'dismiss'}[status],
                 before={'status': candidate['status'], 'hardware_id': candidate['hardware_id']},
                 after={'status': status, 'device_id': str(device_id) if device_id else None})
    return resolved


@router.post('/{ident}/approve')
def approve_candidate(ident: UUID, body: DeviceCandidateApproval,
                      user=Depends(owner), db=Depends(get_db, scope='function')):
    farm_id = farm_scope(user)
    candidate = lock_candidate(db, ident, farm_id)
    hardware_id = candidate['hardware_id']
    if db.scalar(select(Device.id).where(Device.hardware_id == hardware_id)) is not None:
        raise HTTPException(409, 'El identificador ya está registrado')
    if candidate['status'] != 'pending':
        raise HTTPException(409, 'La detección ya fue resuelta')

    # Serialize automatic naming within the farm when two collars are approved together.
    if body.name is None:
        db.scalar(select(Farm.id).where(Farm.id == farm_id).with_for_update(key_share=True))
    name = body.name if body.name is not None else suggested_device_name(db, farm_id)
    device_input = DeviceIn(
        name=name, hardware_id=hardware_id, transport=candidate['transport'],
        interval_seconds=body.interval_seconds or candidate['interval_seconds'],
        dev_eui=body.dev_eui if 'dev_eui' in body.model_fields_set else candidate['dev_eui'],
    )
    device = create_inventory_device(
        db, user, device_input, installed_at=body.installed_at, enabled=body.enabled,
        firmware_version=candidate['firmware_version'],
        origin={'source': candidate['source'], 'candidate_id': str(candidate['id'])},
    )
    candidate = resolve_candidate(db, candidate, user, 'approved', device.id)
    return {
        'device': device_json(db, device),
        'candidate': candidate_json(candidate, suggested_device_name(db, farm_id)),
    }


@router.post('/{ident}/dismiss')
def dismiss_candidate(ident: UUID, user=Depends(owner), db=Depends(get_db, scope='function')):
    farm_id = farm_scope(user)
    candidate = lock_candidate(db, ident, farm_id)
    if candidate['status'] == 'approved':
        raise HTTPException(409, 'La detección ya fue aprobada')
    if candidate['status'] == 'pending':
        candidate = resolve_candidate(db, candidate, user, 'dismissed')
    return candidate_json(candidate, suggested_device_name(db, farm_id))
