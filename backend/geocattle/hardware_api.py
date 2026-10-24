"""Telemetria de collares, incluso antes de asignarlos a bovinos."""
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.orm import aliased
from .db import get_db
from .models import Animal, Device, Farm, Telemetry
from .security import current_user

router = APIRouter(prefix='/api/v1/hardware', tags=['Hardware'])


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
        quality = sample.quality or {} if sample else {}
        interval = quality.get('period_ms')
        interval = interval / 1000 if isinstance(interval, (int, float)) and interval > 0 else device.interval_seconds
        threshold = max(120, interval * 3)
        age = max(0, (now - sample.observed_at).total_seconds()) if sample else None
        position_age = max(0, (now - fix.observed_at).total_seconds()) if fix else None
        items.append({'hardware_id': device.hardware_id, 'name': device.name,
            'enabled': device.enabled, 'latest': sample_dict(sample, device.hardware_id, animal_name) if sample else None,
            'last_position': sample_dict(fix, device.hardware_id) if fix else None,
            'age_seconds': age, 'position_age_seconds': position_age,
            'freshness_seconds': threshold, 'communication_status': 'unknown' if age is None else 'recent' if age <= threshold else 'stale'})
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
def receiver(user=Depends(current_user)):
    # Solo operadores del predio pueden consultar el estado del USB local.
    if not user.farm_id or user.role not in ('owner', 'admin'):
        raise HTTPException(403, 'Se requiere propietario y predio activo')
    path = os.environ.get('USB_STATUS_PATH')
    if not path or not Path(path).exists():
        return {'available': False, 'connected': False, 'error': 'Puente USB sin estado disponible'}
    try:
        status = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        updated = datetime.fromisoformat(status['updated_at'])
        status['available'] = 0 <= (datetime.now(timezone.utc) - updated).total_seconds() < 30
        if not status['available']:
            status['connected'] = False
        return status
    except (OSError, ValueError, KeyError):
        return {'available': False, 'connected': False, 'error': 'Estado USB no legible'}
