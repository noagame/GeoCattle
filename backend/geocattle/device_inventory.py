"""Inventory creation and serialization shared by manual and detected collars."""
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import column, exists, or_, select, table, text, true

from .device_candidates import lock_device_identity
from .domain import append_audit, at_time
from .models import Assignment, Device, DeviceConfig, Event, Maintenance, Telemetry, utcnow
from .schemas import DeviceIn


CHANGE_REQUESTS = table('change_requests', column('device_id'))


def device_history_exists(device_id):
    return or_(*(exists().where(relation == device_id).correlate(Device) for relation in (
        Telemetry.device_id, Assignment.device_id, Maintenance.device_id,
        Event.device_id, DeviceConfig.device_id, CHANGE_REQUESTS.c.device_id,
    )))


def delete_inventory_device(db, user, device):
    if db.scalar(select(device_history_exists(device.id))):
        raise HTTPException(409, 'El collar tiene historial y no se puede eliminar. Desvincúlalo si corresponde y retíralo del servicio')
    candidates = db.execute(text('''UPDATE device_candidates
        SET status = 'dismissed', resolved_at = now(), resolved_by = :actor, device_id = NULL
        WHERE device_id = :device AND farm_id = :farm RETURNING id'''),
        {'actor': user.id, 'device': device.id, 'farm': user.farm_id}).scalars()
    for candidate_id in candidates:
        append_audit(db, user.farm_id, user.id, 'device_candidate', candidate_id, 'dismiss',
                     before={'status': 'approved', 'device_id': str(device.id)},
                     after={'status': 'dismissed', 'reason': 'inventory_deleted'})
    append_audit(db, user.farm_id, user.id, 'device', device.id, 'delete',
                 before={'hardware_id': device.hardware_id, 'name': device.name, 'enabled': device.enabled})
    db.delete(device)
    db.flush()


def inventory_query():
    pending = (
        select(DeviceConfig.version, DeviceConfig.interval_seconds, DeviceConfig.status)
        .where(DeviceConfig.device_id == Device.id, DeviceConfig.status.in_(['requested', 'sent']))
        .order_by(DeviceConfig.version.desc()).limit(1).lateral()
    )
    return (
        select(Device, Assignment, pending.c.version, pending.c.interval_seconds, pending.c.status,
               device_history_exists(Device.id).label('has_history'))
        .select_from(Device)
        .outerjoin(Assignment, (Assignment.device_id == Device.id) & at_time(Assignment, utcnow()))
        .outerjoin(pending, true())
    )


def inventory_item(device, assignment, pending_version, pending_interval, pending_status, has_history):
    return {
        'id': device.id, 'hardware_id': device.hardware_id, 'dev_eui': device.dev_eui,
        'name': device.name, 'transport': device.transport, 'enabled': device.enabled,
        'interval_seconds': device.interval_seconds, 'config_version': device.config_version,
        'pending_config': {'version': pending_version, 'interval_seconds': pending_interval,
                           'status': pending_status} if pending_version is not None else None,
        'animal_id': assignment.animal_id if assignment else None,
        'assignment_id': assignment.id if assignment else None,
        'can_delete': not has_history,
        'last_received_at': device.last_received_at,
    }


def device_json(db, device):
    return inventory_item(*db.execute(inventory_query().where(Device.id == device.id)).one())


def devices_json(db, farm_id):
    rows = db.execute(inventory_query().where(Device.farm_id == farm_id).order_by(Device.name))
    return [inventory_item(*row) for row in rows]


def create_inventory_device(db, user, body: DeviceIn, *, installed_at: datetime | None = None,
                            enabled: bool | None = None, firmware_version: str | None = None,
                            origin: dict | None = None):
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
    audit_data = dict(data, installed_at=installed_at.isoformat()) if installed_at is not None else dict(data)
    audit_data['origin'] = origin or {'source': 'manual'}
    append_audit(db, user.farm_id, user.id, 'device', device.id, 'create', after=audit_data)
    return device
