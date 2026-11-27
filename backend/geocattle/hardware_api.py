"""Telemetria de collares, incluso antes de asignarlos a bovinos."""
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select, func, and_, text
from sqlalchemy.orm import aliased
from .db import get_db
from .device_candidates import capture_farm
from .domain import freshness
from .models import Animal, Device, Farm, Telemetry
from .security import current_user, service_auth
from .settings import settings

router = APIRouter(prefix='/api/v1/hardware', tags=['Hardware'])
capture_router = APIRouter(prefix='/api/v1/ingest', tags=['Hardware'])


class ReceiverStatus(BaseModel):
    connected: bool
    wifi_ssid: str | None = Field(default=None, max_length=32)
    wifi_rssi_dbm: int | None = Field(default=None, ge=-127, le=0)
    firmware: str = Field(min_length=1, max_length=32)
    buffer_capacity: int = Field(ge=0, le=4096)
    dropped: int = Field(ge=0, le=2**63 - 1)
    captured: int = Field(ge=0, le=2**63 - 1)
    pending: int = Field(ge=0, le=2**63 - 1)
    delivered: int = Field(ge=0, le=2**63 - 1)
    error: str | None = Field(default=None, max_length=512)
    last_capture: AwareDatetime | None = None
    updated_at: AwareDatetime


def _save_receiver_snapshot(db, farm_id, snapshot, *, received_at=None):
    # USB freshness belongs to the file, and duplicate polls must not refresh it.
    usb_updated_at = snapshot['updated_at'] if received_at is not None else None
    db.execute(text("""
        INSERT INTO receiver_status (farm_id, snapshot, received_at)
        SELECT :farm, CAST(:snapshot AS jsonb), COALESCE(CAST(:received_at AS timestamptz), clock_timestamp())
        WHERE NOT EXISTS (
            SELECT 1 FROM receiver_status
            WHERE farm_id = :farm
              AND (received_at > :received_at OR snapshot ->> 'updated_at' = :usb_updated_at)
        )
        ON CONFLICT (farm_id) DO UPDATE
        SET snapshot = EXCLUDED.snapshot, received_at = EXCLUDED.received_at
        WHERE receiver_status.received_at <= EXCLUDED.received_at
          AND (CAST(:usb_updated_at AS text) IS NULL
               OR receiver_status.snapshot ->> 'updated_at' IS DISTINCT FROM :usb_updated_at)
    """), {'farm': farm_id, 'snapshot': json.dumps(snapshot, allow_nan=False),
           'received_at': received_at, 'usb_updated_at': usb_updated_at})


def save_receiver_status(db, farm_id, status):
    snapshot = status.model_dump(mode='json')
    snapshot.update(receiver_mode='gateways', bus_version=1)
    _save_receiver_snapshot(db, farm_id, snapshot)


def read_usb_receiver_status(path):
    snapshot = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get('connected'), bool)
            or not isinstance(snapshot.get('updated_at'), str)):
        raise ValueError('Estado USB inválido')
    updated_at = datetime.fromisoformat(snapshot['updated_at'])
    if updated_at.tzinfo is None:
        raise ValueError('El estado USB requiere zona horaria')
    return snapshot, updated_at.astimezone(timezone.utc)


def publish_usb_receiver_status(db):
    path = os.environ.get('USB_STATUS_PATH')
    if not path:
        return
    try:
        snapshot, updated_at = read_usb_receiver_status(path)
        configured_farm = os.environ.get('INGEST_FARM_ID', '').strip()
        farm_id = capture_farm(db, UUID(configured_farm) if configured_farm else None)
        _save_receiver_snapshot(db, farm_id, snapshot, received_at=min(updated_at, datetime.now(timezone.utc)))
    except (OSError, ValueError, OverflowError, HTTPException):
        return


class ReceiverLine(BaseModel):
    ref: int = Field(gt=0, le=2**63 - 1)
    line: str = Field(min_length=1, max_length=8192)
    received_at: AwareDatetime
    clock: Literal['synced', 'reconstructed', 'recovery']


class ReceiverBatch(BaseModel):
    version: Literal[1]
    status: ReceiverStatus
    records: list[ReceiverLine] = Field(max_length=8)


def receiver_payloads(record):
    from adapters.lora_bus import decode_many
    from .schemas import TelemetryIn

    # Igual que la base USB: origin_gateway 0 es un collar oído directo por la receptora.
    decoded = decode_many(record.line, record.received_at, receiver='T3-WiFi', reception='base')
    if not decoded.is_bus or decoded.errors or not decoded.readings:
        raise ValueError('Se requiere un lote bus_v1 válido')
    payloads = []
    for reading, _ in decoded.readings:
        reading['quality'].update(capture_method='gateways', base_clock=record.clock, observed_at_estimated=True)
        payloads.append(TelemetryIn.model_validate(reading))
    return payloads


@capture_router.post('/receiver-batch', dependencies=[Depends(service_auth)])
def report_receiver_batch(body: ReceiverBatch, farm_id: UUID = Header(alias='X-Farm-ID'),
                          db=Depends(get_db, scope='function')):
    from .domain import ingest

    if settings().app_env != 'production':
        raise HTTPException(403, 'La ingesta remota de la T3 requiere producción')
    if len({record.ref for record in body.records}) != len(body.records):
        raise HTTPException(422, 'Referencias repetidas en el lote')
    farm_id = capture_farm(db, farm_id)
    now = datetime.now(timezone.utc)
    receipts = []
    for record in body.records:
        try:
            payloads = receiver_payloads(record)
            with db.begin_nested():
                results = [ingest(db, payload, received_at=now, detect_candidates=True, capture_farm_id=farm_id)
                           for payload in payloads]
                db.flush()
            receipts.append({'ref': record.ref, 'ids': [item['id'] for item in results]})
        except (ValueError, OverflowError):
            receipts.append({'ref': record.ref, 'error': 422})
        except HTTPException as error:
            if error.status_code not in (403, 409, 422):
                raise
            receipts.append({'ref': record.ref, 'error': error.status_code})
    save_receiver_status(db, farm_id, body.status)
    return {'records': receipts}


def period(day, timezone_name):
    zone = ZoneInfo(timezone_name)
    return (datetime.combine(day, time.min, zone).astimezone(timezone.utc),
            datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc))


def sample_dict(sample, collar, animal_name=None):
    keys = ('id', 'device_id', 'animal_id', 'session_id', 'seq', 'observed_at',
            'received_at', 'longitude', 'latitude', 'gnss_valid',
            'surface_temperature_c', 'activity_index', 'battery_mv', 'source', 'quality')
    return {**{key: getattr(sample, key) for key in keys},
            'hardware_id': collar, 'animal_name': animal_name}


@router.get('/overview')
def overview(user=Depends(current_user), db=Depends(get_db, scope='function')):
    if not user.farm_id or not db.get(Farm, user.farm_id):
        raise HTTPException(403, 'Seleccione un predio autorizado')
    # An indexed lookup per device avoids loading its complete history on refresh.
    latest_id = (select(Telemetry.id).where(Telemetry.device_id == Device.id,
        Telemetry.farm_id == user.farm_id).order_by(Telemetry.observed_at.desc(),
        Telemetry.id.desc()).limit(1).correlate(Device).scalar_subquery())
    position = aliased(Telemetry)
    position_id = (select(position.id).where(position.device_id == Device.id,
        position.farm_id == user.farm_id, position.gnss_valid.is_(True),
        position.latitude.is_not(None), position.longitude.is_not(None))
        .order_by(position.observed_at.desc(), position.id.desc()).limit(1)
        .correlate(Device).scalar_subquery())
    rows = db.execute(select(Device, Telemetry, Animal.name, position)
        .outerjoin(Telemetry, Telemetry.id == latest_id)
        .outerjoin(Animal, Animal.id == Telemetry.animal_id)
        .outerjoin(position, position.id == position_id)
        .where(Device.farm_id == user.farm_id).order_by(Device.hardware_id)).all()
    now = datetime.now(timezone.utc)
    items = []
    for device, sample, animal_name, fix in rows:
        _, communication = freshness(fix.observed_at if fix else None,
                                     device.last_received_at, device.interval_seconds, now)
        age = max(0, (now - sample.observed_at).total_seconds()) if sample else None
        position_age = max(0, (now - fix.observed_at).total_seconds()) if fix else None
        items.append({'hardware_id': device.hardware_id, 'name': device.name,
            'enabled': device.enabled, 'latest': sample_dict(sample, device.hardware_id, animal_name) if sample else None,
            'last_position': sample_dict(fix, device.hardware_id) if fix else None,
            'age_seconds': age, 'position_age_seconds': position_age,
            'freshness_seconds': 2 * device.interval_seconds + 30,
            'communication_status': 'stale' if communication == 'absent' else communication})
    return {'items': items, 'server_time': now}


@router.get('/telemetry')
def telemetry(day: date | None = None, hardware_id: str | None = None,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              user=Depends(current_user), db=Depends(get_db, scope='function')):
    farm = db.get(Farm, user.farm_id) if user.farm_id else None
    if not farm:
        raise HTTPException(403, 'Seleccione un predio autorizado')
    day = day or datetime.now(ZoneInfo(farm.timezone)).date()
    start, end = period(day, farm.timezone)
    filters = [Telemetry.farm_id == farm.id, Telemetry.observed_at >= start,
               Telemetry.observed_at < end]
    if hardware_id:
        filters.append(Device.hardware_id == hardware_id)
    base = select(Telemetry).join(Device, Telemetry.device_id == Device.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(select(Telemetry, Device.hardware_id, Animal.name)
        .join(Device, Telemetry.device_id == Device.id)
        .outerjoin(Animal, Telemetry.animal_id == Animal.id).where(*filters)
        .order_by(Telemetry.observed_at.desc(), Telemetry.id.desc()).limit(limit).offset(offset)).all()
    items = [sample_dict(sample, collar, animal_name) for sample, collar, animal_name in rows]
    devices = db.scalars(select(Device).where(Device.farm_id == farm.id).order_by(Device.hardware_id)).all()
    return {'items': items, 'total': total, 'day': day, 'timezone': farm.timezone,
            'devices': [{'hardware_id': d.hardware_id, 'name': d.name} for d in devices]}


@router.get('/daily')
def daily(hardware_id: str | None = None, days: int = Query(30, ge=1, le=366),
          user=Depends(current_user), db=Depends(get_db, scope='function')):
    farm = db.get(Farm, user.farm_id) if user.farm_id else None
    if not farm:
        raise HTTPException(403, 'Seleccione un predio autorizado')
    first_day = datetime.now(ZoneInfo(farm.timezone)).date() - timedelta(days=days - 1)
    start, _ = period(first_day, farm.timezone)
    filters = [Telemetry.farm_id == farm.id, Telemetry.observed_at >= start]
    if hardware_id:
        filters.append(Device.hardware_id == hardware_id)
    local_day = func.date(func.timezone(farm.timezone, Telemetry.observed_at))
    rows = db.execute(select(local_day.label('day'), Device.hardware_id,
        func.count().label('samples'), func.count().filter(and_(Telemetry.gnss_valid.is_(True), Telemetry.latitude.is_not(None), Telemetry.longitude.is_not(None))).label('positions'),
        func.count(Telemetry.surface_temperature_c).label('temperatures'),
        func.count().filter(Telemetry.quality['movement_state'].astext == 'moving').label('moving_samples'),
        func.count().filter(Telemetry.quality['movement_state'].astext == 'rest').label('rest_samples'),
        func.min(Telemetry.surface_temperature_c).label('temperature_min'),
        func.max(Telemetry.surface_temperature_c).label('temperature_max'),
        func.min(Telemetry.observed_at).label('first_at'), func.max(Telemetry.observed_at).label('last_at'))
        .join(Device, Telemetry.device_id == Device.id).where(*filters)
        .group_by(local_day, Device.hardware_id).order_by(local_day.desc(), Device.hardware_id).limit(2500)).mappings().all()
    return {'items': [dict(row) for row in rows], 'timezone': farm.timezone}


@router.get('/receiver')
def receiver(user=Depends(current_user), db=Depends(get_db, scope='function')):
    # Solo operadores del predio pueden consultar el estado del USB local.
    farm = db.get(Farm, user.farm_id) if user.farm_id else None
    if not farm or user.role not in ('owner', 'admin'):
        raise HTTPException(403, 'Se requiere propietario y predio activo')
    if farm.environment == 'simulation':
        return {'available': False, 'connected': False, 'error': 'Predio con datos simulados'}
    config = settings()
    replica = getattr(config, 'mirror_mode', 'off') == 'replica'
    environment = config.mirror_source_environment if replica else config.app_env
    if farm.environment != environment:
        raise HTTPException(403, 'Predio de otro entorno')
    path = os.environ.get('USB_STATUS_PATH')
    has_local_status = not replica and path and Path(path).is_file()
    if replica or (not has_local_status and config.app_env == 'production'):
        remote = db.execute(text('SELECT snapshot, received_at FROM receiver_status WHERE farm_id = :farm'),
                            {'farm': farm.id}).one_or_none()
        if remote is None:
            return {'available': False, 'connected': False, 'error': 'Receptora T3 sin estado disponible'}
        recent = 0 <= (datetime.now(timezone.utc) - remote.received_at).total_seconds() < 90
        return {**remote.snapshot, 'available': recent,
                'connected': recent and remote.snapshot['connected']}
    if not has_local_status:
        return {'available': False, 'connected': False, 'error': 'Puente USB sin estado disponible'}
    try:
        status, updated = read_usb_receiver_status(path)
        status['available'] = 0 <= (datetime.now(timezone.utc) - updated).total_seconds() < 30
        if not status['available']:
            status['connected'] = False
        return status
    except (OSError, ValueError, OverflowError):
        return {'available': False, 'connected': False, 'error': 'Estado USB no legible'}
