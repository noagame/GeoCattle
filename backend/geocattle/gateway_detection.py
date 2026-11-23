"""Discovery and first-hop reception attribution for the academic radio bus."""
import json

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .v3_security import execute, one, rows

RADIO_NODES = (1, 2)


class BusRadio(BaseModel):
    model_config = ConfigDict(strict=True)
    rssi_dbm: float = Field(ge=-200, le=20, allow_inf_nan=False)
    snr_db: float = Field(ge=-100, le=100, allow_inf_nan=False)


def lock_gateway_farm(db, farm_id):
    execute(db, 'SELECT pg_advisory_xact_lock(hashtextextended(:farm_key, 829011))', farm_key=str(farm_id))


def check_gateway_eui(db, gateway_eui):
    if gateway_eui is not None and one(db, 'SELECT id FROM gateways WHERE gateway_eui=:eui', eui=gateway_eui):
        raise HTTPException(409, 'Gateway EUI ya registrado; revisa el inventario, incluidos los archivados')


def current_gateway(db, farm_id, node_id):
    return one(db, 'SELECT id,node_linked_at FROM gateways WHERE farm_id=:farm AND node_id=:node AND archived_at IS NULL',
               farm=farm_id, node=node_id)


def ensure_node_available(db, farm_id, node_id, *, gateway_id=None, candidate_id=None):
    gateway = current_gateway(db, farm_id, node_id)
    reservation = one(db, 'SELECT id FROM gateway_candidates WHERE farm_id=:farm AND reserved_node_id=:node',
                      farm=farm_id, node=node_id)
    if (gateway and gateway['id'] != gateway_id) or (reservation and reservation['id'] != candidate_id):
        raise HTTPException(409, f'El nodo de radio {node_id:02d} está ocupado o reservado en este predio')


def allocate_node(db, farm_id, candidate):
    if candidate['reserved_node_id'] is not None:
        return candidate['reserved_node_id']
    if candidate['node_id'] is not None:
        ensure_node_available(db, farm_id, candidate['node_id'], candidate_id=candidate['id'])
        return candidate['node_id']
    unavailable = rows(db, """SELECT node_id FROM gateways WHERE farm_id=:farm AND archived_at IS NULL
        UNION SELECT COALESCE(reserved_node_id,node_id) FROM gateway_candidates
        WHERE farm_id=:farm AND status='pending'""", farm=farm_id)
    occupied = {row['node_id'] for row in unavailable}
    for node_id in RADIO_NODES:
        if node_id not in occupied:
            return node_id
    raise HTTPException(409, 'No hay nodos libres: bus_v1 admite dos gateways (01 y 02) por predio')


def candidate_json(candidate):
    node_id = candidate['reserved_node_id'] or candidate['node_id']
    return {**candidate, 'suggested_name': f'Gateway {node_id:02d}' if node_id else None}


def audit_detection(db, farm_id, candidate, actor=None):
    execute(db, """INSERT INTO audit_log(id,farm_id,account_id,actor_id,actor_kind,object_type,object_id,action,at,after)
        SELECT gen_random_uuid(),id,account_id,:actor,:kind,'gateway_candidate',:candidate,'detect',now(),CAST(:details AS jsonb)
        FROM farms WHERE id=:farm""", farm=farm_id, actor=actor, kind='user' if actor else 'service',
        candidate=str(candidate['id']), details=json.dumps(candidate_json(candidate), default=str))


def register_usb_gateway(db, farm_id, body, now, actor=None):
    lock_gateway_farm(db, farm_id)
    check_gateway_eui(db, body.gateway_eui)
    params = dict(farm=farm_id, node=body.node_id, eui=body.gateway_eui, firmware=body.firmware, seen=now)
    candidate = one(db, 'SELECT * FROM gateway_candidates WHERE farm_id=:farm AND gateway_eui=:eui AND status=\'pending\'', **params)
    if body.node_id is not None:
        ensure_node_available(db, farm_id, body.node_id, candidate_id=candidate['id'] if candidate else None)
    if candidate:
        if candidate['reserved_node_id'] and body.node_id not in (None, candidate['reserved_node_id']):
            raise HTTPException(409, 'La placa informa un nodo distinto del reservado para esta detección')
        return one(db, """UPDATE gateway_candidates SET node_id=:node, firmware=:firmware,
            last_seen_at=greatest(last_seen_at,:seen), seen_count=seen_count+1 WHERE id=:id RETURNING *""",
            **params, id=candidate['id'])
    candidate = one(db, """UPDATE gateway_candidates SET gateway_eui=:eui, source='usb', firmware=:firmware,
        last_seen_at=greatest(last_seen_at,:seen), seen_count=seen_count+1
        WHERE farm_id=:farm AND node_id=:node AND source='radio' AND status='pending' RETURNING *""", **params)
    if not candidate:
        candidate = one(db, """INSERT INTO gateway_candidates(farm_id,node_id,gateway_eui,source,firmware,first_seen_at,last_seen_at)
            VALUES(:farm,:node,:eui,'usb',:firmware,:seen,:seen) RETURNING *""", **params)
    audit_detection(db, farm_id, candidate, actor)
    return candidate


def observe_bus_gateway(db, farm_id, payload, now, telemetry=None):
    transport = payload.quality.get('transport')
    if not isinstance(transport, dict) or type(transport.get('bus_version')) is not int or transport['bus_version'] != 1:
        return
    node_id = transport.get('origin_gateway')
    path = transport.get('path')
    hops = transport.get('hops')
    if (type(node_id) is not int or node_id not in RADIO_NODES or type(path) is not int or path not in (2, 4, 6)
            or not path & (1 << node_id) or type(hops) is not int or hops != path.bit_count()
            or transport.get('radio_scope') != 'collar_to_first_receiver'):
        return
    try:
        radio = BusRadio.model_validate(payload.quality.get('radio'))
    except ValidationError:
        return

    lock_gateway_farm(db, farm_id)
    receipt = one(db, """INSERT INTO gateway_bus_receipts(farm_id,hardware_id,session_id,seq,node_id)
        VALUES(:farm,:hardware,:session,:seq,:node) ON CONFLICT DO NOTHING RETURNING node_id""",
        farm=farm_id, hardware=payload.hardware_id, session=payload.session_id, seq=payload.seq, node=node_id)
    if not receipt:
        return
    gateway = current_gateway(db, farm_id, node_id)
    if gateway:
        if telemetry is not None and payload.observed_at >= gateway['node_linked_at']:
            execute(db, """WITH inserted AS (
                INSERT INTO telemetry_receptions(telemetry_id,farm_id,gateway_id,received_at,rssi_dbm,snr_db)
                VALUES(:telemetry,:farm,:gateway,:received,:rssi,:snr) ON CONFLICT DO NOTHING RETURNING gateway_id
            ) UPDATE gateways SET last_seen_at=greatest(last_seen_at,:server_time)
                FROM inserted WHERE gateways.id=inserted.gateway_id""",
                telemetry=telemetry.id, farm=farm_id, gateway=gateway['id'], received=payload.observed_at, server_time=now,
                rssi=radio.rssi_dbm, snr=radio.snr_db)
        return

    if one(db, """SELECT id FROM gateway_candidates WHERE farm_id=:farm AND
            ((source='radio' AND status='dismissed' AND node_id=:node) OR
             (source='usb' AND status='pending' AND COALESCE(reserved_node_id,node_id)=:node)) LIMIT 1""",
            farm=farm_id, node=node_id):
        return
    candidate = one(db, """UPDATE gateway_candidates SET last_seen_at=greatest(last_seen_at,:seen), seen_count=seen_count+1
        WHERE farm_id=:farm AND node_id=:node AND source='radio' AND status='pending' RETURNING id""",
        farm=farm_id, node=node_id, seen=now)
    if not candidate:
        candidate = one(db, """INSERT INTO gateway_candidates(farm_id,node_id,source,first_seen_at,last_seen_at)
            VALUES(:farm,:node,'radio',:seen,:seen) RETURNING *""", farm=farm_id, node=node_id, seen=now)
        audit_detection(db, farm_id, candidate)
