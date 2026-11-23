"""Farm-scoped detection and durable receipts for captures awaiting registration."""
from datetime import timezone
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text

from .models import Audit, Device, Farm, utcnow
from .schemas import HARDWARE_ID_PATTERN, DeviceCandidateIn
from .settings import settings


def lock_device_identity(db, hardware_id):
    # The inventory reserves hardware_id globally. Serialize its creation with
    # detections so a concurrent approval cannot leave a new pending row behind.
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:hardware_id, 829009))'),
               {'hardware_id': hardware_id})


def capture_farm(db, farm_id):
    environment = settings().app_env
    if environment == 'simulation':
        raise HTTPException(403, 'Simulación no admite detecciones de hardware físico')
    query = select(Farm.id).where(Farm.environment == environment, Farm.active)
    if farm_id is not None:
        if db.scalar(query.where(Farm.id == farm_id)) is None:
            raise HTTPException(403, 'Predio de captura no disponible en este entorno')
        return farm_id
    farms = db.scalars(query.limit(2)).all()
    if len(farms) != 1:
        raise HTTPException(409, 'Configura el predio físico de captura con X-Farm-ID')
    return farms[0]


def candidate_json(row, suggested_name):
    fields = ('id', 'hardware_id', 'transport', 'dev_eui', 'interval_seconds',
              'firmware_version', 'source', 'seen_count', 'last_payload', 'status')
    return {
        **{key: row[key] for key in fields},
        'first_seen_at': row['first_seen_at'].astimezone(timezone.utc),
        'last_seen_at': row['last_seen_at'].astimezone(timezone.utc),
        'suggested_name': suggested_name,
    }


def suggested_device_name(db, farm_id):
    names = {name.strip().casefold() for name in db.scalars(
        select(Device.name).where(Device.farm_id == farm_id)
    )}
    number = 1
    while (name := f'Collar {number:02d}').casefold() in names:
        number += 1
    return name


def upsert_candidate(db, farm_id, detection, payload, received_at):
    values = detection.model_dump()
    if detection.dev_eui:
        values['dev_eui'] = detection.dev_eui.lower()
    result = db.execute(text("""
        INSERT INTO device_candidates AS candidate (
            id, farm_id, hardware_id, transport, dev_eui, interval_seconds, firmware_version,
            source, first_seen_at, last_seen_at, seen_count, last_payload
        ) VALUES (
            :id, :farm_id, :hardware_id, :transport, :dev_eui, :interval_seconds, :firmware_version,
            :source, :seen_at, :seen_at, 1, CAST(:payload AS jsonb)
        )
        ON CONFLICT (farm_id, hardware_id) WHERE status = 'pending' DO UPDATE SET
            seen_count = candidate.seen_count + 1,
            first_seen_at = least(candidate.first_seen_at, EXCLUDED.first_seen_at),
            last_seen_at = greatest(candidate.last_seen_at, EXCLUDED.last_seen_at),
            (transport, dev_eui, interval_seconds, firmware_version, source, last_payload) = (
                SELECT
                    CASE WHEN latest THEN EXCLUDED.transport ELSE candidate.transport END,
                    CASE
                        WHEN latest AND candidate.transport <> EXCLUDED.transport THEN EXCLUDED.dev_eui
                        WHEN latest THEN coalesce(EXCLUDED.dev_eui, candidate.dev_eui)
                        WHEN candidate.transport = EXCLUDED.transport THEN coalesce(candidate.dev_eui, EXCLUDED.dev_eui)
                        ELSE candidate.dev_eui
                    END,
                    CASE WHEN latest THEN EXCLUDED.interval_seconds ELSE candidate.interval_seconds END,
                    CASE WHEN latest THEN coalesce(EXCLUDED.firmware_version, candidate.firmware_version)
                        ELSE coalesce(candidate.firmware_version, EXCLUDED.firmware_version) END,
                    CASE WHEN latest THEN EXCLUDED.source ELSE candidate.source END,
                    CASE WHEN latest THEN EXCLUDED.last_payload ELSE candidate.last_payload END
                FROM (SELECT EXCLUDED.last_seen_at >= candidate.last_seen_at AS latest) AS ordering
            )
        RETURNING *
    """), dict(values, id=uuid4(), farm_id=farm_id, seen_at=received_at,
               payload=json.dumps(payload, allow_nan=False)))
    return result.mappings().one()


def audit_first_detection(db, farm_id, candidate, actor=None):
    """Audit only the first sighting; repeated packets update the candidate without new entries."""
    if candidate['seen_count'] != 1:
        return
    # domain.py imports this module, so the audit row is added directly.
    db.add(Audit(farm_id=farm_id, actor_id=actor, object_type='device_candidate', object_id=str(candidate['id']),
                 action='detect', actor_kind='user' if actor else 'service', after={
        key: candidate[key] for key in ('hardware_id', 'transport', 'source', 'firmware_version', 'interval_seconds')
    }))


def register_detection(db, farm_id, detection, actor=None):
    lock_device_identity(db, detection.hardware_id)
    if db.scalar(select(Device.id).where(Device.hardware_id == detection.hardware_id)) is not None:
        raise HTTPException(409, 'El identificador ya está registrado')
    candidate = upsert_candidate(db, farm_id, detection, detection.model_dump(exclude_none=True), utcnow())
    audit_first_detection(db, farm_id, candidate, actor)
    return candidate


def capture_identity(farm_id, payload):
    return {'farm_id': farm_id, 'hardware_id': payload.hardware_id,
            'session_id': payload.session_id, 'seq': payload.seq}


def candidate_receipt(db, farm_id, payload):
    ident = db.scalar(text("""
        SELECT candidate_id FROM device_candidate_captures
        WHERE farm_id = :farm_id AND hardware_id = :hardware_id
          AND session_id = :session_id AND seq = :seq
    """), capture_identity(farm_id, payload))
    return radio_receipt(ident, duplicate=True) if ident else None


def radio_receipt(ident, *, duplicate):
    return {'id': str(ident), 'status': 'candidate', 'duplicate': duplicate, 'animal_id': None}


def detect_radio_candidate(db, farm_id, payload, received_at):
    if not re.fullmatch(HARDWARE_ID_PATTERN, payload.hardware_id):
        raise HTTPException(422, 'Formato de identificador de collar inválido')
    receipt = candidate_receipt(db, farm_id, payload)
    if receipt:
        return receipt

    period_ms = payload.quality.get('period_ms')
    # Legacy collars may send more frequently than the supported monitoring interval.
    interval = min(86400, max(30, (period_ms + 999) // 1000)) if type(period_ms) is int and period_ms > 0 else 300
    firmware = payload.quality.get('firmware_version')
    detection = DeviceCandidateIn(
        hardware_id=payload.hardware_id, transport=payload.source, interval_seconds=interval,
        firmware_version=firmware if isinstance(firmware, str) and 1 <= len(firmware) <= 100 else None,
        source='radio',
    )
    try:
        frame = payload.model_dump(mode='json')
        candidate = upsert_candidate(db, farm_id, detection, frame, received_at)
    except ValueError as error:
        raise HTTPException(422, 'Carga de detección inválida') from error
    audit_first_detection(db, farm_id, candidate)
    db.execute(text("""
        INSERT INTO device_candidate_captures (farm_id, hardware_id, session_id, seq, candidate_id)
        VALUES (:farm_id, :hardware_id, :session_id, :seq, :candidate_id)
    """), dict(capture_identity(farm_id, payload), candidate_id=candidate['id']))
    return radio_receipt(candidate['id'], duplicate=False)
