"""Exportación de métricas e inventario del predio activo."""
import re
from dataclasses import asdict, fields
from datetime import date, timedelta
from typing import Literal
from unicodedata import normalize
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response

from .db import get_db
from .hardware_api import period
from .kpi_metrics import Evidence, Metric, calculate_metrics
from .models import Farm, utcnow
from .owner_export_queries import COLLARS, GATEWAYS, METRIC_EVIDENCE
from .report_exports import CsvDelimiter, EXPORT_LIMIT, export_response
from .security import owner
from .v3_api import farm_scope
from .v3_security import one, rows


router = APIRouter(prefix='/api/v1/v3/owner-exports', tags=['Exportación del dueño'])
ReportKind = Literal['metricas', 'dispositivos', 'general']
PREVIEW_LIMIT = 5
NO_CACHE = {'Cache-Control': 'no-store'}
METRIC_COLUMNS = ('Código', 'Nombre', 'Valor', 'Unidad', 'Meta', 'Cumple', 'Numerador', 'Denominador',
                  'Ventana', 'Método / fuente', 'Observación', 'Valor complementario', 'Medida complementaria')
COLLAR_FIELDS = {
    'hardware_id': 'ID de hardware', 'dev_eui': 'DevEUI', 'name': 'Nombre', 'transport': 'Transporte',
    'status': 'Estado', 'firmware_version': 'Firmware', 'interval_seconds': 'Intervalo (s)',
    'installed_at': 'Instalación', 'last_observed_at': 'Última observación', 'last_received_at': 'Última recepción',
    'battery_mv': 'Última batería (mV)', 'period_readings': 'Lecturas en el período', 'diio': 'DIIO vigente',
    'animal_name': 'Bovino vigente', 'assigned_from': 'Asignado desde', 'historical_assignments': 'Asignaciones cerradas',
    'withdrawn_at': 'Fecha de baja', 'withdrawal_reason': 'Motivo registrado',
}
GATEWAY_FIELDS = {
    'gateway_eui': 'EUI de gateway', 'name': 'Nombre', 'status': 'Estado', 'longitude': 'Longitud',
    'latitude': 'Latitud', 'installed_at': 'Instalación', 'last_seen_at': 'Última comunicación',
    'node_id': 'Nodo local', 'period_receptions': 'Recepciones en el período',
    'withdrawn_at': 'Fecha de baja', 'withdrawal_reason': 'Motivo registrado',
}
INVENTORY_SUMMARY = """
    SELECT (SELECT count(*) FROM devices WHERE farm_id=:farm) AS collars,
           (SELECT count(*) FROM devices WHERE farm_id=:farm AND NOT enabled) AS withdrawn_collars,
           (SELECT count(*) FROM gateways WHERE farm_id=:farm) AS gateways,
           (SELECT count(*) FROM gateways WHERE farm_id=:farm
            AND (archived_at IS NOT NULL OR status='retired')) AS withdrawn_gateways
"""


def date_window(start, end, as_of, timezone):
    zone = ZoneInfo(timezone)
    end = end or start or as_of.astimezone(zone).date()
    start = start or end
    if end < start or (end - start).days >= 366 or end == date.max:
        raise HTTPException(422, 'Selecciona un período válido de hasta 366 días')
    start_at, _ = period(start, timezone)
    _, end_at = period(end, timezone)
    return start, end, start_at, min(end_at, as_of)


def evidence_for(db, params):
    result = one(db, METRIC_EVIDENCE, **params)
    for key in ('packets', 'expected_packets', 'unique_packets'):
        result[key] = int(result[key])
    return Evidence(**result)


def asset_values(records, field_names):
    return (tuple(record.get(field) for field in field_names) for record in records)


@router.get('/{kind}')
def owner_report(kind: ReportKind, response: Response, start: date | None = None, end: date | None = None,
                 days: Literal['7', '30'] | None = None,
                 format: Literal['json', 'csv', 'xlsx'] = 'json', delimiter: CsvDelimiter = 'semicolon',
                 user=Depends(owner), db=Depends(get_db, scope='function')):
    farm = db.get(Farm, farm_scope(user))
    if kind == 'general' and format != 'xlsx':
        raise HTTPException(422, 'El informe combinado solo está disponible en Excel')
    as_of = utcnow()
    zone = ZoneInfo(farm.timezone)
    if days is not None:
        if start is not None or end is not None:
            raise HTTPException(422, 'Selecciona un período predefinido o un rango, no ambos')
        end = as_of.astimezone(zone).date()
        start = end - timedelta(days=int(days) - 1)
    start, end, start_at, stop_at = date_window(start, end, as_of, farm.timezone)
    simulation = farm.environment == 'simulation'
    origin = 'Simulado' if simulation else 'Físico'
    params = dict(farm=farm.id, account=farm.account_id, simulation=simulation, as_of=as_of,
                  start_at=start_at, stop_at=stop_at)
    preview = format == 'json'
    response.headers.update(NO_CACHE)
    context = dict(farm_id=farm.id, farm_name=farm.name, environment=farm.environment, origin=origin,
                   timezone=farm.timezone, start=start, end=end, generated_at=as_of)
    metadata = [('Predio', farm.name), ('ID del predio', str(farm.id)), ('Desde', start), ('Hasta', end),
                ('Zona horaria', farm.timezone), ('Entorno', farm.environment), ('Origen', origin),
                ('Generado', as_of), ('Corte de datos del período (exclusivo)', max(start_at, stop_at))]
    slug = re.sub(r'[^a-z0-9]+', '-', normalize('NFKD', farm.name).lower()).strip('-')[:60] or str(farm.id)
    filename = f'geocattle-{kind}-{slug}-{start}-{end}'
    if kind != 'dispositivos':
        evidence = evidence_for(db, params)
        metrics = calculate_metrics(evidence, f'{start} a {end} ({farm.timezone})')
        if preview:
            return {**context, 'metrics': [asdict(metric) for metric in metrics]}
        metric_names = tuple(field.name for field in fields(Metric))
        metric_rows = [tuple(getattr(metric, field) for field in metric_names) for metric in metrics]
        metadata.append(('Alcance KPI', 'Excluye collares retirados y gateways retirados o archivados al generar.'))
        if kind == 'metricas':
            columns = METRIC_COLUMNS if format == 'xlsx' else (*METRIC_COLUMNS, 'Origen')
            if format == 'csv':
                metric_rows = [(*row, origin) for row in metric_rows]
            return export_response(columns, metric_rows, format=format, filename=filename, title='Métricas',
                                   zone=zone, metadata=metadata, delimiter=delimiter, headers=NO_CACHE)

    summary = one(db, INVENTORY_SUMMARY, farm=farm.id)
    if not preview and summary['collars'] + summary['gateways'] > EXPORT_LIMIT:
        raise HTTPException(422, f'El inventario supera el límite de {EXPORT_LIMIT} filas')
    params['limit'] = PREVIEW_LIMIT if preview else EXPORT_LIMIT + 1
    collars = rows(db, COLLARS, **params)
    gateways = rows(db, GATEWAYS, **params)
    if preview:
        return {**context, 'summary': summary, 'collars': collars, 'gateways': gateways}
    if len(collars) + len(gateways) > EXPORT_LIMIT:
        raise HTTPException(422, f'El inventario supera el límite de {EXPORT_LIMIT} filas')

    metadata.extend((('Estado del inventario', 'Inventario, asignaciones y últimas lecturas vigentes al generar.'),
                     ('Collares retirados', summary['withdrawn_collars']),
                     ('Gateways retirados o archivados', summary['withdrawn_gateways'])))
    collar_table = ('Collares', tuple(COLLAR_FIELDS.values()), asset_values(collars, COLLAR_FIELDS))
    gateway_table = ('Gateways', tuple(GATEWAY_FIELDS.values()), asset_values(gateways, GATEWAY_FIELDS))
    if format == 'csv':
        inventory_fields = COLLAR_FIELDS | GATEWAY_FIELDS
        title, columns = 'Dispositivos', ('Tipo', 'Origen', *inventory_fields.values())
        values = ((asset_type, origin, *line) for asset_type, records in (('Collar', collars), ('Gateway', gateways))
                  for line in asset_values(records, inventory_fields))
        sheets = ()
    elif kind == 'general':
        title, columns, values = 'Métricas', METRIC_COLUMNS, metric_rows
        sheets = (collar_table, gateway_table)
    else:
        title, columns, values = collar_table
        sheets = (gateway_table,)
    return export_response(columns, values, format=format, filename=filename, title=title, zone=zone,
                           metadata=metadata, delimiter=delimiter, headers=NO_CACHE, sheets=sheets)
