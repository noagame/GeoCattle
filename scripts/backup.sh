#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
umask 077
backup_dir="${GEOCATTLE_BACKUP_DIR:-backups}"
mkdir -p -- "$backup_dir"
geocattle_backup="$backup_dir/geocattle-$(date -u +%Y%m%dT%H%M%S%NZ).dump"
partial="$(mktemp "$backup_dir/.geocattle-XXXXXXXX.part")"
trap 'rm -f -- "$partial"' EXIT
# Contraseña del contenedor; no se pasa por argumentos ni se imprime.
bash scripts/compose.sh exec -T database sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom' > "$partial"
if [ ! -s "$partial" ]; then
  echo 'Respaldo vacío, se eliminó el archivo incompleto.' >&2
  exit 1
fi
bash scripts/compose.sh exec -T database pg_restore --list < "$partial" > /dev/null
mv -- "$partial" "$geocattle_backup"
echo "Respaldo: $geocattle_backup"

