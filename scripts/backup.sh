#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
umask 077
mkdir -p backups
geocattle_backup="backups/geocattle-$(date -u +%Y%m%dT%H%M%SZ).dump"
# Contraseña del contenedor; no se pasa por argumentos ni se imprime.
bash scripts/compose.sh exec -T database sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom' > "$geocattle_backup"
if [ ! -s "$geocattle_backup" ]; then
  rm -f "$geocattle_backup"
  echo 'Respaldo vacío, se eliminó el archivo incompleto.' >&2
  exit 1
fi
echo "Respaldo: $geocattle_backup"

