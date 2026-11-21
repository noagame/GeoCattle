"""Queries for the owner's farm reports, using the same rows for preview and CSV."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Report:
    columns: tuple[str, ...]
    select: str
    order: str


MIN_SAMPLES = 10
ALERT_LABELS = {
    'all': 'Todas',
    'escape': 'Fuera de geocerca',
    'communication_timeout': 'Sin comunicación',
    'low_battery': 'Batería baja',
    'high_surface_temperature': 'Temperatura superficial elevada',
    'low_activity': 'Actividad reducida',
    'proximity': 'Cerca del límite de geocerca',
    'config_timeout': 'Configuración sin confirmar',
}

# Telemetry is linked at ingestion to the assignment in force at observation time.
ASSIGNED_SAMPLES = """
    SELECT t.animal_id,t.observed_at,timezone(:zone,t.observed_at)::date AS day,
           t.gnss_valid,t.quality->>'movement_state' AS movement
    FROM telemetry t
    JOIN assignments x ON x.id=t.assignment_id AND x.farm_id=t.farm_id
         AND x.animal_id=t.animal_id AND x.device_id=t.device_id
         AND t.observed_at>=x.valid_from AND (x.valid_to IS NULL OR t.observed_at<x.valid_to)
    WHERE t.farm_id=:farm AND t.observed_at>=:start_at AND t.observed_at<:end_at
          AND t.observed_at<=:as_of AND (t.source='sim')=:simulation
"""

RANKED_ANIMALS = """
    SELECT a.id,a.diio,a.name FROM animals a
    WHERE a.farm_id=:farm AND a.species='bovine' AND EXISTS (
        SELECT 1 FROM animal_holdings h WHERE h.farm_id=a.farm_id AND h.animal_id=a.id
          AND h.valid_from<:end_at AND h.valid_from<=:as_of
          AND (h.valid_to IS NULL OR h.valid_to>:start_at)
    )
"""

PERIOD_DAYS = "greatest(0,least(:end_day,timezone(:zone,:as_of)::date)-:start_day+1)"


INDICATORS = {
    'totales': Report(
        ('Indicador', 'Cantidad', 'Fecha de corte'),
        """SELECT item,quantity,:as_of AS cutoff FROM (
             SELECT 'Bovinos activos' AS item,count(*) AS quantity FROM animals a
             WHERE a.farm_id=:farm AND a.species='bovine' AND a.enabled AND a.status='active' AND EXISTS (
                 SELECT 1 FROM animal_holdings h WHERE h.farm_id=a.farm_id AND h.animal_id=a.id
                   AND h.valid_from<=:as_of AND (h.valid_to IS NULL OR h.valid_to>:as_of)
             )
             UNION ALL
             SELECT 'Collares inventariados',count(*) FROM devices WHERE farm_id=:farm
             UNION ALL
             SELECT 'Collares con asignación vigente',count(DISTINCT device_id) FROM assignments
             WHERE farm_id=:farm AND valid_from<=:as_of AND (valid_to IS NULL OR valid_to>:as_of)
             UNION ALL
             SELECT 'Módulos de software habilitados',count(*) FROM farm_features WHERE farm_id=:farm AND enabled
             UNION ALL
             SELECT f.name,1 FROM farm_features x JOIN features f ON f.code=x.feature_code
             WHERE x.farm_id=:farm AND x.enabled
           ) t""", "CASE item WHEN 'Bovinos activos' THEN 1 WHEN 'Collares inventariados' THEN 2 "
                       "WHEN 'Collares con asignación vigente' THEN 3 WHEN 'Módulos de software habilitados' THEN 4 ELSE 5 END,item"),
    'serie-alertas': Report(
        ('Desde', 'Hasta', 'Tipo de alerta', 'Alertas abiertas en el período', 'Días con lecturas asignadas', 'Días del período'),
        f"""WITH buckets AS (
             SELECT b::date AS bucket,greatest(b::date,:start_day) AS first_day,
                    least((b+CAST(:step AS interval))::date-1,:end_day) AS last_day
             FROM generate_series(date_trunc(:grain,CAST(:start_day AS timestamp)),
                         date_trunc(:grain,CAST(:end_day AS timestamp)),CAST(:step AS interval)) b
           ), alerts AS (
             SELECT date_trunc(:grain,timezone(:zone,e.opened_at))::date AS bucket,count(*) AS total
             FROM events e WHERE e.farm_id=:farm AND e.opened_at>=:start_at AND e.opened_at<:end_at
               AND e.opened_at<=:as_of AND (:alert_type='all' OR e.type=:alert_type)
             GROUP BY 1
           ), observed AS (
             SELECT date_trunc(:grain,s.day::timestamp)::date AS bucket,count(DISTINCT s.day) AS days
             FROM ({ASSIGNED_SAMPLES}) s GROUP BY 1
           )
           SELECT b.first_day,b.last_day,:alert_label,coalesce(a.total,0),coalesce(o.days,0),b.last_day-b.first_day+1
           FROM buckets b LEFT JOIN alerts a USING (bucket) LEFT JOIN observed o USING (bucket)""", 'first_day'),
    'ranking-movimiento': Report(
        ('Puesto', 'DIIO', 'Bovino', 'Movimiento (%)', 'Muestras en movimiento', 'Muestras clasificadas',
         'Días con clasificación', 'Días de referencia', 'Cobertura'),
        f"""WITH samples AS (
             SELECT animal_id,count(*) FILTER (WHERE movement='moving') AS moving,count(*) AS classified,
                    count(DISTINCT day) AS days
             FROM ({ASSIGNED_SAMPLES}) t WHERE movement IN ('moving','rest') GROUP BY animal_id
           ), scores AS (
             SELECT a.diio,a.name,coalesce(s.moving,0) AS moving,coalesce(s.classified,0) AS classified,
                    coalesce(s.days,0) AS days,{PERIOD_DAYS} AS period_days,
                    100.0*s.moving/nullif(s.classified,0) AS percent
             FROM ({RANKED_ANIMALS}) a LEFT JOIN samples s ON s.animal_id=a.id
           ), eligibility AS (
             SELECT *,classified>=:minimum AND days*2>=period_days AS eligible FROM scores
           )
           SELECT CASE WHEN eligible THEN rank() OVER (ORDER BY eligible DESC,percent DESC NULLS LAST) END AS rank,
                  diio,name,round(percent,2),moving,classified,days,period_days,
                  CASE WHEN eligible THEN 'Suficiente' ELSE 'Insuficiente' END
           FROM eligibility""", 'rank NULLS LAST,diio'),
    'ranking-salidas': Report(
        ('Puesto', 'DIIO', 'Bovino', 'Alertas de salida', 'Geocercas de las alertas', 'Posiciones válidas en seguimiento',
         'Días con posición en seguimiento', 'Días de referencia', 'Cobertura'),
        f"""WITH samples AS (
             SELECT t.animal_id,count(*) AS fixes,count(DISTINCT t.day) AS days FROM ({ASSIGNED_SAMPLES}) t
             WHERE t.gnss_valid AND EXISTS (
                 SELECT 1 FROM pasture_assignments p WHERE p.farm_id=:farm AND p.animal_id=t.animal_id
                   AND p.valid_from<=t.observed_at AND (p.valid_to IS NULL OR p.valid_to>t.observed_at)
             ) GROUP BY t.animal_id
           ), escape_events AS (
             SELECT e.animal_id,CASE WHEN g.id IS NOT NULL THEN
                 g.name || ' (v' || coalesce(e.detail->>'geofence_version',g.version::text) || ')'
                 ELSE 'Sin geocerca registrada' END AS fence
             FROM events e LEFT JOIN geofences g ON g.id=e.geofence_id AND g.farm_id=e.farm_id
             WHERE e.farm_id=:farm AND e.type='escape' AND e.opened_at>=:start_at AND e.opened_at<:end_at AND e.opened_at<=:as_of
           ), escapes AS (
             SELECT animal_id,count(*) AS escapes,string_agg(DISTINCT fence, ', ' ORDER BY fence) AS fences
             FROM escape_events GROUP BY animal_id
           ), scores AS (
             SELECT a.diio,a.name,coalesce(e.escapes,0) AS escapes,e.fences,coalesce(s.fixes,0) AS fixes,
                    coalesce(s.days,0) AS days,{PERIOD_DAYS} AS period_days
             FROM ({RANKED_ANIMALS}) a LEFT JOIN samples s ON s.animal_id=a.id LEFT JOIN escapes e ON e.animal_id=a.id
           ), eligibility AS (
             SELECT *,fixes>=:minimum AND days*2>=period_days AS eligible FROM scores
           )
           SELECT CASE WHEN eligible AND escapes>0 THEN rank() OVER (ORDER BY eligible DESC,escapes DESC) END AS rank,
                  diio,name,escapes,fences,fixes,days,period_days,
                  CASE WHEN eligible THEN 'Suficiente' ELSE 'Insuficiente' END
           FROM eligibility""", 'rank NULLS LAST,escapes DESC,diio'),
}
