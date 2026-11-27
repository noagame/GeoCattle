"""Consultas de exportación, acotadas al predio activo y su origen de datos."""


METRIC_EVIDENCE = """
WITH active_devices AS (
    SELECT id,interval_seconds FROM devices WHERE farm_id=:farm AND enabled
), samples AS (
    SELECT t.id,t.farm_id,t.device_id,t.animal_id,t.assignment_id,t.session_id,t.seq,t.gnss_valid,
           t.battery_mv,t.observed_at,t.received_at,extract(epoch FROM t.received_at-t.observed_at) AS age_seconds,
           CASE WHEN jsonb_typeof(t.quality->'period_ms')='number' THEN
               CASE WHEN (t.quality->>'period_ms')::numeric BETWEEN 1 AND 86400000
                    THEN (t.quality->>'period_ms')::numeric / 1000 END
           END AS reported_interval, coalesce(c.interval_seconds,d.interval_seconds) AS interval_seconds
    FROM telemetry t JOIN active_devices d ON d.id=t.device_id
    LEFT JOIN device_configs c ON c.device_id=t.device_id AND c.version=t.config_version AND c.status='applied'
    WHERE t.farm_id=:farm AND (t.source='sim')=:simulation AND t.received_at<=:as_of
      AND t.observed_at>=:start_at AND t.observed_at<:stop_at
), sequence_ranges AS (
    SELECT count(*) AS packets,count(DISTINCT seq) AS unique_packets,
           max(seq)::numeric-min(seq)+1 AS expected_packets
    FROM samples GROUP BY device_id,session_id
), position_counts AS (
    SELECT count(*) AS position_samples, count(*) FILTER (
        WHERE t.gnss_valid AND t.age_seconds BETWEEN 0 AND 2*coalesce(t.reported_interval,t.interval_seconds)+30
    ) AS fresh_positions
    FROM samples t
    JOIN assignments x ON x.id=t.assignment_id AND x.farm_id=t.farm_id AND x.device_id=t.device_id
         AND x.animal_id=t.animal_id AND t.observed_at>=x.valid_from
         AND (x.valid_to IS NULL OR t.observed_at<x.valid_to)
    JOIN animals a ON a.id=x.animal_id AND a.farm_id=x.farm_id AND a.species='bovine'
), opening_samples AS (
    SELECT e.type,e.animal_id,t.assignment_id,e.opened_at,t.observed_at,
           extract(epoch FROM e.opened_at-t.received_at) AS lag_seconds
    FROM events e JOIN telemetry t ON t.id=e.telemetry_id AND t.farm_id=e.farm_id AND t.device_id=e.device_id
    JOIN active_devices d ON d.id=e.device_id
    WHERE e.farm_id=:farm AND (t.source='sim')=:simulation
      AND e.opened_at>=:start_at AND e.opened_at<:stop_at
      AND e.type NOT IN ('communication_timeout','config_timeout')
), tracked AS (
    SELECT x.id,x.animal_id,greatest(x.valid_from,h.valid_from,:start_at) AS tracked_from,
           least(x.valid_to,h.valid_to,:stop_at) AS tracked_to
    FROM assignments x JOIN active_devices d ON d.id=x.device_id
    JOIN animals a ON a.id=x.animal_id AND a.farm_id=x.farm_id AND a.species='bovine'
    JOIN animal_holdings h ON h.id=x.animal_holding_id AND h.farm_id=x.farm_id AND h.animal_id=x.animal_id
    WHERE x.farm_id=:farm AND x.valid_from<:stop_at AND (x.valid_to IS NULL OR x.valid_to>:start_at)
), battery_pairs AS (
    SELECT DISTINCT device_id,
           last_value(battery_mv) OVER window_by_device - first_value(battery_mv) OVER window_by_device AS delta
    FROM (SELECT s.*,count(*) OVER (PARTITION BY device_id) AS battery_samples
          FROM samples s WHERE battery_mv IS NOT NULL) battery
    WHERE battery_samples>=2
    WINDOW window_by_device AS (PARTITION BY device_id ORDER BY observed_at,received_at,id
                                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
SELECT
    coalesce((SELECT sum(packets) FROM sequence_ranges),0) AS packets,
    coalesce((SELECT sum(unique_packets) FROM sequence_ranges),0) AS unique_packets,
    coalesce((SELECT sum(expected_packets) FROM sequence_ranges),0) AS expected_packets,
    p.position_samples,p.fresh_positions,
    lag.event_samples,lag.processing_p50,lag.processing_p95,
    (SELECT count(*)-count(DISTINCT r.telemetry_id)
     FROM telemetry_receptions r JOIN samples t ON t.id=r.telemetry_id AND t.farm_id=r.farm_id
     JOIN gateways g ON g.id=r.gateway_id AND g.farm_id=r.farm_id
     WHERE r.farm_id=:farm AND r.received_at<=:as_of AND g.archived_at IS NULL AND g.status<>'retired'
    ) AS extra_gateway_receptions,
    req.requests,req.errors,req.request_p95_ms,
    (SELECT count(*) FROM battery_pairs) AS battery_devices,
    (SELECT avg(delta) FROM battery_pairs) AS battery_delta_mv,
    (SELECT count(*) FROM opening_samples e JOIN tracked x ON x.id=e.assignment_id AND x.animal_id=e.animal_id
     WHERE e.type='escape' AND e.observed_at>=x.tracked_from AND e.observed_at<x.tracked_to) AS exits,
    coalesce((SELECT sum(extract(epoch FROM tracked_to-tracked_from))/3600 FROM tracked
              WHERE tracked_to>tracked_from),0) AS animal_hours
FROM position_counts p
CROSS JOIN (
    SELECT count(*) AS event_samples,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY lag_seconds) AS processing_p50,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY lag_seconds) AS processing_p95
    FROM opening_samples WHERE lag_seconds>=0
) lag
CROSS JOIN (
    SELECT count(*) AS requests, count(*) FILTER (WHERE status_code>=400) AS errors,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS request_p95_ms
    FROM request_metrics WHERE farm_id=:farm AND account_id=:account AND method='GET'
      AND occurred_at>=:start_at AND occurred_at<:stop_at
      AND route_template IN ('/api/v1/dashboard','/api/v1/animals','/api/v1/animals/{animal_id}','/api/v1/events')
) req
"""

TELEMETRY_SCOPE = """
    FROM telemetry t JOIN devices d ON d.id=t.device_id AND d.farm_id=t.farm_id
    WHERE t.farm_id=:farm AND (t.source='sim')=:simulation AND t.received_at<=:as_of
      AND t.observed_at>=:start_at AND t.observed_at<:stop_at
"""
TELEMETRY_SUMMARY = """SELECT count(*) AS readings,count(DISTINCT t.device_id) AS collars,
    count(DISTINCT date(timezone(:tz,t.observed_at))) AS days,min(t.observed_at) AS first_at,max(t.observed_at) AS last_at
""" + TELEMETRY_SCOPE
TELEMETRY_DAILY = """SELECT date(timezone(:tz,t.observed_at)) AS day,d.hardware_id,d.name,count(*) AS samples,
    count(*) FILTER (WHERE t.gnss_valid AND t.latitude IS NOT NULL AND t.longitude IS NOT NULL) AS positions,
    count(t.surface_temperature_c) AS temperatures,
    min(t.surface_temperature_c) AS temperature_min,max(t.surface_temperature_c) AS temperature_max,
    count(*) FILTER (WHERE t.quality->>'movement_state'='rest') AS rest_samples,
    count(*) FILTER (WHERE t.quality->>'movement_state'='moving') AS moving_samples,
    min(t.battery_mv) AS battery_min_mv,max(t.battery_mv) AS battery_max_mv,
    min(t.observed_at) AS first_at,max(t.observed_at) AS last_at
""" + TELEMETRY_SCOPE + """    GROUP BY 1,d.hardware_id,d.name ORDER BY 1 DESC,d.hardware_id LIMIT :limit"""
TELEMETRY_READINGS = """SELECT d.hardware_id,a.diio,a.name AS animal_name,t.seq,t.observed_at,t.received_at,
    t.gnss_valid,t.latitude,t.longitude,t.surface_temperature_c,t.activity_index,
    CASE t.quality->>'movement_state' WHEN 'rest' THEN 'Reposo' WHEN 'moving' THEN 'Movimiento' END AS movement_state,t.battery_mv
""" + TELEMETRY_SCOPE.replace('    WHERE', '    LEFT JOIN animals a ON a.id=t.animal_id AND a.farm_id=t.farm_id\n    WHERE') + \
    """    ORDER BY t.observed_at,d.hardware_id,t.id LIMIT :limit"""

COLLARS = """
WITH inventory AS (
    SELECT * FROM devices WHERE farm_id=:farm ORDER BY name,id LIMIT :limit
), counts AS (
    SELECT t.device_id,count(*) AS period_readings FROM telemetry t JOIN inventory d ON d.id=t.device_id
    WHERE t.farm_id=:farm AND (t.source='sim')=:simulation AND t.received_at<=:as_of
      AND t.observed_at>=:start_at AND t.observed_at<:stop_at GROUP BY t.device_id
)
SELECT d.id,d.hardware_id,d.dev_eui,d.name,d.transport,
       CASE WHEN NOT d.enabled THEN 'Retirado' WHEN d.status='maintenance' THEN 'En mantenimiento'
            WHEN assigned.diio IS NOT NULL THEN 'Instalado' ELSE 'Disponible' END AS status,
       d.firmware_version,d.interval_seconds,d.installed_at,
       latest.observed_at AS last_observed_at,received.last_received_at,battery.battery_mv,
       coalesce(counts.period_readings,0) AS period_readings,assigned.diio,assigned.animal_name,
       assigned.assigned_from,
       (SELECT count(*) FROM assignments x WHERE x.farm_id=d.farm_id AND x.device_id=d.id
        AND x.valid_to<=:as_of) AS historical_assignments,
       CASE WHEN NOT d.enabled THEN coalesce(retired.at,maintenance.at) END AS withdrawn_at,
       maintenance.result AS withdrawal_reason
FROM inventory d LEFT JOIN counts ON counts.device_id=d.id
LEFT JOIN LATERAL (
    SELECT t.observed_at FROM telemetry t WHERE t.device_id=d.id AND t.farm_id=d.farm_id
      AND (t.source='sim')=:simulation AND t.received_at<=:as_of AND t.observed_at<=:as_of
    ORDER BY t.observed_at DESC,t.received_at DESC,t.id LIMIT 1
) latest ON true
LEFT JOIN LATERAL (
    SELECT max(t.received_at) AS last_received_at FROM telemetry t WHERE t.device_id=d.id AND t.farm_id=d.farm_id
      AND (t.source='sim')=:simulation AND t.received_at<=:as_of
) received ON true
LEFT JOIN LATERAL (
    SELECT t.battery_mv FROM telemetry t WHERE t.device_id=d.id AND t.farm_id=d.farm_id
      AND (t.source='sim')=:simulation AND t.battery_mv IS NOT NULL
      AND t.received_at<=:as_of AND t.observed_at<=:as_of
    ORDER BY t.observed_at DESC,t.received_at DESC,t.id LIMIT 1
) battery ON true
LEFT JOIN LATERAL (
    SELECT a.diio,a.name AS animal_name,x.valid_from AS assigned_from
    FROM assignments x JOIN animals a ON a.id=x.animal_id AND a.farm_id=x.farm_id AND a.species='bovine'
    WHERE x.farm_id=d.farm_id AND x.device_id=d.id AND x.valid_from<=:as_of
      AND (x.valid_to IS NULL OR x.valid_to>:as_of)
) assigned ON true
LEFT JOIN LATERAL (
    SELECT al.at FROM audit_log al WHERE NOT d.enabled AND al.farm_id=d.farm_id
      AND al.object_type='device' AND al.object_id=d.id::text AND al.action='set_enabled' AND al.at<=:as_of
      AND al.before->>'enabled'='true' AND al.after->>'enabled'='false'
    ORDER BY al.at DESC,al.id LIMIT 1
) retired ON true
LEFT JOIN LATERAL (
    SELECT m.at,m.result FROM maintenance m WHERE NOT d.enabled AND m.farm_id=d.farm_id AND m.device_id=d.id
      AND m.kind='retirement' AND m.at<=:as_of
      AND NOT EXISTS (SELECT 1 FROM audit_log al WHERE al.farm_id=d.farm_id AND al.object_type='device'
        AND al.object_id=d.id::text AND al.action='set_enabled' AND al.after->>'enabled'='true'
        AND al.before->>'enabled'='false' AND al.at>m.at AND al.at<=:as_of)
    ORDER BY m.at DESC,m.id LIMIT 1
) maintenance ON true
ORDER BY d.name,d.id
"""

GATEWAYS = """
WITH inventory AS (
    SELECT * FROM gateways WHERE farm_id=:farm ORDER BY name,id LIMIT :limit
), receptions AS (
    SELECT r.gateway_id,count(*) AS period_receptions
    FROM inventory g JOIN telemetry_receptions r ON r.gateway_id=g.id AND r.farm_id=g.farm_id
    JOIN telemetry t ON t.id=r.telemetry_id AND t.farm_id=r.farm_id
    WHERE r.farm_id=:farm AND (t.source='sim')=:simulation
      AND r.received_at>=:start_at AND r.received_at<:stop_at GROUP BY r.gateway_id
)
SELECT g.id,g.gateway_eui,g.name,
       CASE WHEN g.archived_at IS NOT NULL THEN 'Archivado' WHEN g.status='retired' THEN 'Retirado'
            WHEN g.status='maintenance' THEN 'En mantenimiento' ELSE 'Instalado' END AS status,
       ST_X(g.position) AS longitude,ST_Y(g.position) AS latitude,g.installed_at,
       greatest(CASE WHEN NOT :simulation AND g.last_seen_at<=:as_of THEN g.last_seen_at END,
                last_reception.received_at) AS last_seen_at,
       g.node_id,coalesce(r.period_receptions,0) AS period_receptions,g.archived_at AS withdrawn_at,
       NULL::text AS withdrawal_reason
FROM inventory g LEFT JOIN receptions r ON r.gateway_id=g.id
LEFT JOIN LATERAL (
    SELECT max(r.received_at) AS received_at FROM telemetry_receptions r
    JOIN telemetry t ON t.id=r.telemetry_id AND t.farm_id=r.farm_id
    WHERE r.gateway_id=g.id AND r.farm_id=g.farm_id AND (t.source='sim')=:simulation AND r.received_at<=:as_of
) last_reception ON true
ORDER BY g.name,g.id
"""
