"""Read-only reports over the selected farm and its animals."""
from datetime import date
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from .db import get_db
from .hardware_api import period
from .models import Farm, utcnow
from .report_exports import CsvDelimiter, EXPORT_LIMIT, display_value, export_response
from .security import current_user
from .v3_api import farm_scope, scoped
from .v3_farm_indicators import ALERT_LABELS, INDICATORS, MIN_SAMPLES, Report


router = APIRouter(prefix='/api/v1/v3/animal-reports', tags=['Animal reports'])
ReportKind = Literal['inventario', 'sanidad', 'agenda', 'mediciones', 'observaciones', 'asignaciones', 'alertas', 'actividad',
                     'totales', 'serie-alertas', 'ranking-movimiento', 'ranking-salidas']
AlertType = Literal['all', 'escape', 'communication_timeout', 'low_battery', 'high_surface_temperature',
                    'low_activity', 'proximity', 'config_timeout']
Grain = Literal['day', 'week', 'month']
GRAINS = {'day': '1 day', 'week': '1 week', 'month': '1 month'}
PREVIEW_ROWS = 25
# Los reportes son para personas: los códigos internos se muestran con su etiqueta en español.
EVENT_TYPES = {'examination': 'Examen', 'vaccination': 'Vacunación', 'antibiotic': 'Antibiótico', 'pathology': 'Patología',
               'diagnosis': 'Diagnóstico', 'procedure': 'Procedimiento', 'injury': 'Lesión', 'death': 'Muerte',
               'observation': 'Observación'}
VALUE_LABELS = {
    'inventario': {'Estado vital': {'active': 'Activo', 'missing': 'Extraviado', 'dead': 'Muerto', 'slaughtered': 'Faenado',
                                    'retired': 'Retirado'},
                   'Orientación': {'meat': 'Carne', 'milk': 'Leche'},
                   'Sexo': {'female': 'Hembra', 'male': 'Macho', 'unknown': 'Sin registrar'}},
    'sanidad': {'Tipo': EVENT_TYPES, 'Operación': {'record': 'Registro', 'correct': 'Corrección', 'void': 'Anulación'}},
    'agenda': {'Tipo': {'vaccination': 'Vacunación', 'antibiotic': 'Antibiótico', 'checkup': 'Control'}},
    'alertas': {'Tipo': {key: label for key, label in ALERT_LABELS.items() if key != 'all'},
                'Severidad': {'warning': 'Precaución', 'critical': 'Crítica'},
                'Condición': {'active': 'Activa', 'resolved': 'Resuelta'},
                'Atención': {'pending': 'Pendiente', 'acknowledged': 'Reconocida', 'in_review': 'En revisión',
                             'concluded': 'Concluida'}},
    'actividad': {'Origen': {'academic': 'Collar del prototipo', 'lorawan': 'LoRaWAN', 'sim': 'Simulado'}},
}


def labelled(kind, columns, row):
    labels = VALUE_LABELS.get(kind)
    if not labels:
        return row
    return [labels.get(column, {}).get(value, value) if isinstance(value, str) else value
            for column, value in zip(columns, row)]
REPORT_TITLES = {
    'inventario': 'Inventario actual', 'sanidad': 'Ficha sanitaria', 'agenda': 'Agenda sanitaria',
    'mediciones': 'Mediciones', 'observaciones': 'Observaciones del rebaño',
    'asignaciones': 'Asignaciones de collares', 'alertas': 'Alertas por bovino', 'actividad': 'Actividad diaria',
    'totales': 'Totales del predio', 'serie-alertas': 'Alertas por período',
    'ranking-movimiento': 'Ranking de movimiento', 'ranking-salidas': 'Ranking de salidas de geocerca',
}


REPORTS: dict[ReportKind, Report] = {
    'inventario': Report(
        ('DIIO', 'Bovino', 'Estado vital', 'Habilitado', 'Orientación', 'Raza', 'Sexo',
         'Nacimiento', 'Sector', 'Collar vigente', 'Alta del bovino'),
        """SELECT a.diio,a.name,a.status,a.enabled,a.orientation,a.breed,a.sex,a.birth_date,
                  s.name AS sector, collar.hardware_id,a.created_at
           FROM selected a LEFT JOIN sectors s ON s.id=a.sector_id AND s.farm_id=a.farm_id
           LEFT JOIN LATERAL (
               SELECT d.hardware_id FROM assignments x
               JOIN devices d ON d.id=x.device_id AND d.farm_id=x.farm_id
               WHERE x.animal_id=a.id AND x.farm_id=a.farm_id
                 AND x.valid_from<=:as_of AND (x.valid_to IS NULL OR x.valid_to>:as_of)
               ORDER BY x.valid_from DESC LIMIT 1
           ) collar ON true""", 'diio'),
    'sanidad': Report(
        ('DIIO', 'Bovino', 'Evento ID', 'Fecha del evento', 'Tipo', 'Operación', 'Autor', 'Descripción',
         'Diagnóstico', 'Producto ID', 'Producto', 'Registro del producto', 'Lote', 'Dosis', 'Unidad',
         'Vía', 'Fecha de administración', 'Resguardo carne hasta', 'Resguardo leche hasta', 'Fundamento del resguardo'),
        """SELECT a.diio,a.name,e.id,e.occurred_at,e.event_type,e.operation,u.full_name,
                  e.description,e.diagnosis,t.id AS product_id,t.product_name,t.product_registration,
                  t.batch_number,t.dose_value,t.dose_unit,t.route,t.administered_at,
                  t.withdrawal_meat_until,t.withdrawal_milk_until,t.withdrawal_basis
           FROM effective_health_events e
           JOIN animal_holdings h ON h.id=e.animal_holding_id AND h.farm_id=e.farm_id
           JOIN selected a ON a.id=h.animal_id AND a.farm_id=h.farm_id
           JOIN users u ON u.id=e.recorded_by
           LEFT JOIN health_treatments t ON t.health_event_id=e.id AND t.farm_id=e.farm_id
           WHERE e.occurred_at>=:start_at AND e.occurred_at<:end_at""",
        'occurred_at DESC, id, product_id'),
    'agenda': Report(
        ('DIIO', 'Bovino', 'Atención ID', 'Fecha planificada', 'Tipo', 'Estado', 'Descripción', 'Responsable', 'Evento de respaldo ID'),
        """SELECT a.diio,a.name,s.id,s.due_at,s.kind,
             CASE WHEN s.operation='complete' THEN 'Completada' WHEN s.operation='cancel' THEN 'Cancelada'
                  WHEN s.due_at<:as_of THEN 'Vencida' ELSE 'Pendiente' END AS state,
             s.description,u.full_name,s.completed_event_id
           FROM health_schedules s
           JOIN animal_holdings h ON h.id=s.animal_holding_id AND h.farm_id=s.farm_id
           JOIN selected a ON a.id=h.animal_id AND a.farm_id=h.farm_id
           JOIN users u ON u.id=s.created_by
           WHERE s.due_at>=:start_at AND s.due_at<:end_at
             AND NOT EXISTS (SELECT 1 FROM health_schedules n WHERE n.target_schedule_id=s.id)""", 'due_at DESC, id'),
    'mediciones': Report(
        ('DIIO', 'Bovino', 'Medición ID', 'Fecha de medición', 'Peso (kg)', 'Altura (cm)', 'Autor'),
        """SELECT a.diio,a.name,m.id,m.measured_at,m.weight_kg,m.height_cm,u.full_name
           FROM animal_measurements m JOIN selected a ON a.id=m.animal_id AND a.farm_id=m.farm_id
           JOIN change_requests r ON r.id=m.request_id AND r.farm_id=m.farm_id
           JOIN users u ON u.id=r.requested_by
           WHERE m.measured_at>=:start_at AND m.measured_at<:end_at""", 'measured_at DESC, id'),
    'observaciones': Report(
        ('DIIO', 'Bovino', 'Observación ID', 'Fecha del reporte', 'Descripción', 'Autor'),
        """SELECT a.diio,a.name,o.id,o.occurred_at,o.description,u.full_name
           FROM animal_reports o
           JOIN animal_holdings h ON h.id=o.animal_holding_id AND h.farm_id=o.farm_id
           JOIN selected a ON a.id=h.animal_id AND a.farm_id=h.farm_id
           JOIN change_requests r ON r.id=o.request_id AND r.farm_id=o.farm_id
           JOIN users u ON u.id=r.requested_by
           WHERE o.occurred_at>=:start_at AND o.occurred_at<:end_at""", 'occurred_at DESC, id'),
    'asignaciones': Report(
        ('DIIO', 'Bovino', 'Asignación ID', 'Identificador del collar', 'Collar', 'Desde', 'Hasta', 'Responsable'),
        """SELECT a.diio,a.name,x.id,d.hardware_id,d.name AS collar_name,x.valid_from,x.valid_to,u.full_name
           FROM assignments x JOIN selected a ON a.id=x.animal_id AND a.farm_id=x.farm_id
           JOIN devices d ON d.id=x.device_id AND d.farm_id=x.farm_id
           LEFT JOIN users u ON u.id=x.assigned_by
           WHERE x.valid_from<:end_at AND (x.valid_to IS NULL OR x.valid_to>:start_at)""", 'valid_from DESC, id'),
    'alertas': Report(
        ('DIIO', 'Bovino', 'Alerta ID', 'Tipo', 'Severidad', 'Condición', 'Atención',
         'Fecha de apertura', 'Fecha de resolución', 'Geocerca', 'Versión de geocerca', 'Identificador del collar'),
        """SELECT a.diio,a.name,e.id,e.type,e.severity,e.condition,e.attention,e.opened_at,
                  e.resolved_at,g.name AS geofence_name,g.version,d.hardware_id
           FROM events e JOIN selected a ON a.id=e.animal_id AND a.farm_id=e.farm_id
           JOIN devices d ON d.id=e.device_id AND d.farm_id=e.farm_id
           LEFT JOIN geofences g ON g.id=e.geofence_id AND g.farm_id=e.farm_id
           WHERE e.opened_at>=:start_at AND e.opened_at<:end_at""", 'opened_at DESC, id'),
    'actividad': Report(
        ('DIIO', 'Bovino', 'Día del predio', 'Origen', 'Lecturas', 'Posiciones válidas',
         'Muestras en movimiento', 'Muestras en reposo', 'Muestras sin clasificación',
         'Temperatura mínima (°C)', 'Temperatura máxima (°C)'),
        """SELECT a.diio,a.name,timezone(:zone,t.observed_at)::date AS day,t.source,count(*) AS samples,
                  count(*) FILTER (WHERE t.gnss_valid) AS fixes,
                  count(*) FILTER (WHERE t.quality->>'movement_state'='moving') AS moving,
                  count(*) FILTER (WHERE t.quality->>'movement_state'='rest') AS resting,
                  count(*) FILTER (WHERE coalesce(t.quality->>'movement_state','') NOT IN ('moving','rest')) AS unknown,
                  min(t.surface_temperature_c),max(t.surface_temperature_c)
           FROM telemetry t JOIN selected a ON a.id=t.animal_id AND a.farm_id=t.farm_id
           WHERE t.observed_at>=:start_at AND t.observed_at<:end_at
           GROUP BY a.diio,a.name,day,t.source""", 'day DESC, diio, source'),
    **INDICATORS,
}


@router.get('/{kind}')
def animal_report(kind: ReportKind, animal_id: UUID | None = None, start: date | None = None,
        end: date | None = None, format: Literal['json', 'csv', 'xlsx'] = 'json', delimiter: CsvDelimiter = 'comma',
        grain: Grain = 'day', alert_type: AlertType = 'all',
        user=Depends(current_user), db=Depends(get_db, scope='function')):
    if user.role not in ('owner', 'admin', 'worker', 'veterinarian'):
        raise HTTPException(403, 'Tu perfil no tiene acceso a los reportes del rebaño')
    if kind in INDICATORS and user.role not in ('owner', 'admin'):
        raise HTTPException(403, 'Los indicadores del predio requieren perfil propietario')
    farm = db.get(Farm, farm_scope(user))
    if animal_id is not None:
        if kind in INDICATORS:
            raise HTTPException(422, 'Los indicadores abarcan todo el predio seleccionado')
        scoped(db, 'animals', animal_id, user)
    zone = ZoneInfo(farm.timezone)
    as_of = utcnow()
    end = end or start or as_of.astimezone(zone).date()
    start = start or end
    if end < start or (end - start).days >= 366 or end == date.max:
        raise HTTPException(422, 'Selecciona un período válido de hasta 366 días')
    start_at, _ = period(start, farm.timezone)
    _, end_at = period(end, farm.timezone)
    report = REPORTS[kind]
    preview = format == 'json'
    projection = 'report.*, count(*) OVER ()' if preview else 'report.*'
    statement = text(f"""
        WITH selected AS (
            SELECT * FROM animals WHERE farm_id=:farm AND (CAST(:animal AS uuid) IS NULL OR id=CAST(:animal AS uuid))
        ), report AS ({report.select})
        SELECT {projection} FROM report ORDER BY {report.order} LIMIT :limit
    """)
    params = {'farm': farm.id, 'animal': animal_id, 'start_at': start_at, 'end_at': end_at,
           'zone': farm.timezone, 'as_of': as_of, 'limit': PREVIEW_ROWS if preview else EXPORT_LIMIT + 1,
           'start_day': start, 'end_day': end, 'grain': grain, 'step': GRAINS[grain], 'alert_type': alert_type,
           'alert_label': ALERT_LABELS[alert_type],
           'simulation': farm.environment == 'simulation', 'minimum': MIN_SAMPLES}
    current = kind in ('inventario', 'totales')
    if preview:
        results = db.execute(statement, params).all()
        return {'columns': report.columns,
                'items': [[display_value(value, zone) for value in labelled(kind, report.columns, row[:-1])] for row in results],
                'total': results[0][-1] if results else 0, 'timezone': farm.timezone,
                'start': None if current else start, 'end': None if current else end}
    metadata = [('Predio', farm.name), ('ID del predio', farm.id), ('Zona horaria', farm.timezone),
                ('Generado', as_of), ('Período', 'Corte actual' if current else 'Fechas inclusivas'),
                ('Bovino (ID)', animal_id or 'Todos')]
    if not current:
        metadata.extend([('Desde', start), ('Hasta', end)])
    if kind == 'serie-alertas':
        metadata.extend([('Agrupación', {'day': 'Día', 'week': 'Semana', 'month': 'Mes'}[grain]),
                         ('Tipo de alerta', ALERT_LABELS[alert_type])])

    def limited_rows(results):
        for row_index, row in enumerate(results):
            if row_index == EXPORT_LIMIT:
                raise HTTPException(422, 'El reporte supera las 50.000 filas. Acorta el período o selecciona un bovino.')
            yield labelled(kind, report.columns, row)

    suffix = 'actual' if current else f'{start}_{end}'
    with db.execute(statement.execution_options(yield_per=1000), params) as results:
        return export_response(report.columns, limited_rows(results), format=format,
                               filename=f'geocattle-{kind}-{suffix}', title=REPORT_TITLES[kind],
                               zone=zone, metadata=metadata, delimiter=delimiter)
