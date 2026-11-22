"""Inventory creation and serialization shared by manual and detected collars."""
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from .device_candidates import lock_device_identity
from .domain import append_audit, at_time
from .models import Assignment, Device, DeviceConfig, utcnow
from .schemas import DeviceIn


def device_json(db, device):
    assignment = db.scalar(select(Assignment).where(
        Assignment.device_id == device.id, at_time(Assignment, utcnow())
    ))
    pending = db.scalar(select(DeviceConfig).where(
        DeviceConfig.device_id == device.id, DeviceConfig.status.in_(['requested', 'sent'])
    ).order_by(DeviceConfig.version.desc()))
    return {
        'id': device.id, 'hardware_id': device.hardware_id, 'dev_eui': device.dev_eui,
        'name': device.name, 'transport': device.transport, 'enabled': device.enabled,
        'interval_seconds': device.interval_seconds, 'config_version': device.config_version,
        'pending_config': {'version': pending.version, 'interval_seconds': pending.interval_seconds,
                           'status': pending.status} if pending else None,
        'animal_id': assignment.animal_id if assignment else None,
        'last_received_at': device.last_received_at,
    }


def create_inventory_device(db, user, body: DeviceIn, *, installed_at: datetime | None = None,
                            enabled: bool | None = None, firmware_version: str | None = None):
    data = body.model_dump()
    if body.dev_eui:
        data['dev_eui'] = body.dev_eui.lower()
    if body.transport == 'lorawan' and not body.dev_eui:
        raise HTTPException(422, 'LoRaWAN requiere DevEUI')
    if installed_at is not None:
        data['installed_at'] = installed_at
    if enabled is not None:
        data['enabled'] = enabled
    if firmware_version is not None:
        data['firmware_version'] = firmware_version

    lock_device_identity(db, body.hardware_id)
    device = Device(id=uuid4(), farm_id=user.farm_id, **data)
    db.add(device)
    db.flush()
    audit_data = dict(data, installed_at=installed_at.isoformat()) if installed_at is not None else data
    append_audit(db, user.farm_id, user.id, 'device', device.id, 'create', after=audit_data)
    return device
