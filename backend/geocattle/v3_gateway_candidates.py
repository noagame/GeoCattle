"""Farm-scoped inventory enrollment for USB and radio gateways."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import Field, field_validator, model_validator

from .db import get_db
from .device_candidates import capture_farm
from .gateway_detection import allocate_node, candidate_json, check_gateway_eui, lock_gateway_farm, register_usb_gateway
from .models import utcnow
from .security import current_user, owner, service_auth
from .v3_api import Strict, farm_scope, gateway_record, insert_gateway
from .v3_security import audit, one, rows

router = APIRouter(prefix='/api/v1/v3/gateway-candidates', tags=['Gateway candidates'])


class GatewayUsbIn(Strict):
    gateway_eui: str = Field(pattern=r'^[0-9a-fA-F]{16}$')
    node_id: int | None = Field(default=None, strict=True, ge=1, le=2)
    firmware: str = Field(min_length=1, max_length=100)

    @field_validator('gateway_eui')
    @classmethod
    def normalize_eui(cls, value):
        return value.lower()


class GatewayApproval(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    longitude: float | None = Field(default=None, strict=True, ge=-180, le=180, allow_inf_nan=False)
    latitude: float | None = Field(default=None, strict=True, ge=-90, le=90, allow_inf_nan=False)
    confirmed_node_id: int | None = Field(default=None, strict=True, ge=1, le=2)
    confirmed_eui: str | None = Field(default=None, pattern=r'^[0-9a-f]{16}$')

    @model_validator(mode='after')
    def valid_fields(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Latitud y longitud se registran juntas')
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError('Nombre requerido')
        return self


@router.get('')
def list_candidates(status: Literal['pending', 'approved', 'dismissed'] = 'pending',
                    user=Depends(owner), db=Depends(get_db, scope='function')):
    candidates = rows(db, """SELECT * FROM gateway_candidates WHERE farm_id=:farm AND status=:status
        ORDER BY last_seen_at DESC,id""", farm=farm_scope(user), status=status)
    return {'items': [candidate_json(candidate) for candidate in candidates]}


@router.post('', status_code=201)
def detect_candidate(body: GatewayUsbIn, request: Request,
                     farm_id: UUID | None = Header(default=None, alias='X-Farm-ID'),
                     db=Depends(get_db, scope='function')):
    actor = None
    if 'X-Ingest-Key' in request.headers:
        service_auth(request)
    else:
        actor = owner(current_user(request, db))
        farm_id = farm_scope(actor)
    return candidate_json(register_usb_gateway(db, capture_farm(db, farm_id), body, utcnow(), actor.id if actor else None))


def scoped_candidate(db, ident, user):
    farm_id = farm_scope(user)
    lock_gateway_farm(db, farm_id)
    candidate = one(db, 'SELECT * FROM gateway_candidates WHERE id=:id AND farm_id=:farm', id=ident, farm=farm_id)
    if not candidate:
        raise HTTPException(403, 'Detección no autorizada en este predio')
    return candidate


@router.post('/{ident}/reserve')
def reserve_node(ident: UUID, user=Depends(owner), db=Depends(get_db, scope='function')):
    candidate = scoped_candidate(db, ident, user)
    if candidate['status'] != 'pending' or candidate['source'] != 'usb':
        raise HTTPException(409, 'Solo se puede reservar un nodo para una detección USB pendiente')
    check_gateway_eui(db, candidate['gateway_eui'])
    if candidate['reserved_node_id'] is not None:
        return candidate_json(candidate)
    node_id = allocate_node(db, user.farm_id, candidate)
    reserved = one(db, 'UPDATE gateway_candidates SET reserved_node_id=:node WHERE id=:id RETURNING *',
                   node=node_id, id=ident)
    audit(db, user, 'reserve', 'gateway_candidate', ident, before=candidate, after=reserved)
    return candidate_json(reserved)


@router.post('/{ident}/approve')
def approve_candidate(ident: UUID, body: GatewayApproval, user=Depends(owner), db=Depends(get_db, scope='function')):
    candidate = scoped_candidate(db, ident, user)
    if candidate['status'] == 'approved':
        return {'gateway': gateway_record(db, candidate['gateway_id'], user), 'candidate': candidate_json(candidate)}
    if candidate['status'] != 'pending':
        raise HTTPException(409, 'La detección ya fue descartada')
    node_id = candidate['node_id']
    if candidate['source'] == 'usb':
        node_id = candidate['reserved_node_id']
        if node_id is None or body.confirmed_node_id != node_id or body.confirmed_eui != candidate['gateway_eui']:
            raise HTTPException(409, 'Confirma por USB el EUI y el nodo reservado antes de completar el alta')
    elif body.confirmed_node_id is not None or body.confirmed_eui is not None:
        raise HTTPException(422, 'Una detección por radio no admite confirmación USB')
    gateway = insert_gateway(db, user, candidate['gateway_eui'], body.name or f'Gateway {node_id:02d}',
                             body.longitude, body.latitude, node_id=node_id, candidate_id=ident)
    result = one(db, """UPDATE gateway_candidates SET status='approved', gateway_id=:gateway, node_id=:node,
        reserved_node_id=NULL, resolved_at=now(), resolved_by=:actor WHERE id=:id RETURNING *""",
        gateway=gateway['id'], node=node_id, actor=user.id, id=ident)
    audit(db, user, 'approve', 'gateway_candidate', ident, before=candidate, after=result)
    return {'gateway': gateway, 'candidate': candidate_json(result)}


@router.post('/{ident}/dismiss')
def dismiss_candidate(ident: UUID, user=Depends(owner), db=Depends(get_db, scope='function')):
    candidate = scoped_candidate(db, ident, user)
    if candidate['status'] == 'approved':
        raise HTTPException(409, 'La detección ya fue aprobada')
    if candidate['status'] == 'dismissed':
        return candidate_json(candidate)
    result = one(db, """UPDATE gateway_candidates SET status='dismissed', reserved_node_id=NULL,
        resolved_at=now(), resolved_by=:actor WHERE id=:id RETURNING *""", actor=user.id, id=ident)
    audit(db, user, 'dismiss', 'gateway_candidate', ident, before=candidate, after=result)
    return candidate_json(result)
