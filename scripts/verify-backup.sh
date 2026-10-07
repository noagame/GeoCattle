#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
geocattle_backup="${1:?Uso: bash scripts/verify-backup.sh backups/archivo.dump}"
if [ ! -f "$geocattle_backup" ]; then echo 'No existe el respaldo.' >&2; exit 1; fi
# Base nueva de ensayo con nombre aleatorio; nunca restaura sobre el origen.
geocattle_restore="geocattle_restore_$(date -u +%Y%m%d%H%M%S)_$RANDOM"
bash scripts/compose.sh exec -T database sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" createdb --username="$POSTGRES_USER" "$1"' sh "$geocattle_restore"
bash scripts/compose.sh exec -T database sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --username="$POSTGRES_USER" --dbname="$1" --exit-on-error' sh "$geocattle_restore" < "$geocattle_backup"
bash scripts/compose.sh exec -T database sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql --username="$POSTGRES_USER" --dbname="$1" --set=ON_ERROR_STOP=1' sh "$geocattle_restore" <<'SQL'
SELECT 'animals' AS entity,count(*) FROM animals
UNION ALL SELECT 'devices',count(*) FROM devices
UNION ALL SELECT 'assignments',count(*) FROM assignments
UNION ALL SELECT 'geofences',count(*) FROM geofences
UNION ALL SELECT 'telemetry',count(*) FROM telemetry
UNION ALL SELECT 'events',count(*) FROM events
UNION ALL SELECT 'actions',count(*) FROM event_actions
UNION ALL SELECT 'audit',count(*) FROM audit_log
UNION ALL SELECT 'maintenance',count(*) FROM maintenance;
SELECT count(*) AS invalid_geofences FROM geofences WHERE NOT ST_IsValid(geometry);
SELECT max(observed_at) AS latest_capture FROM telemetry;
SQL
echo "Restauración verificada en $geocattle_restore. Origen conservado."
