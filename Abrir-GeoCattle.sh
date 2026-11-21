#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if (( $# > 2 )); then
  printf 'Uso: %s [correo-del-dueño] [nombre-del-predio]\n' "$0" >&2
  exit 2
fi

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null || ! docker compose version >/dev/null 2>&1; then
  printf 'GeoCattle requiere Python 3.11 o posterior y Docker con el plugin Compose.\n' >&2
  exit 1
fi

config=.env.docker
owner_setup_marker=.runtime/linux-launcher-owner-ready
python3 scripts/docker_project.py prepare --environment development --env-file "$config"
python3 - "$config" <<'PY'
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from scripts.docker_project import read_config

path = Path(sys.argv[1])
values = read_config(path, 'development')
origins = [origin.strip() for origin in values.get('ALLOWED_ORIGINS', '').split(',') if origin.strip()]
origins.extend(['http://localhost:8084', 'http://127.0.0.1:8084'])
changes = {'WEB_PORT': '8084', 'ALLOWED_ORIGINS': ','.join(dict.fromkeys(origins))}
if any(values.get(key) != value for key, value in changes.items()):
    lines = path.read_text(encoding='utf-8-sig').splitlines(keepends=True)
    kept = [line for line in lines if line.partition('=')[0].strip() not in changes]
    content = ''.join(kept).rstrip('\r\n') + '\n'
    content += ''.join(f'{key}={value}\n' for key, value in changes.items())
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.close()
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
PY
start_args=(start --environment development --env-file "$config")
if [[ ! -f "$owner_setup_marker" || $# -gt 0 ]]; then
  start_args+=(--owner-email "${1:-desarrollo@geocattle.local}" --farm "${2:-Desarrollo GeoCattle}")
fi
python3 scripts/docker_project.py "${start_args[@]}"
mkdir -p .runtime
touch -- "$owner_setup_marker"

url=http://localhost:8084/
printf 'Abre %s. Para una cuenta nueva, consulta ADMIN_PASSWORD en %s.\n' "$url" "$config"
if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v xdg-open >/dev/null; then
  xdg-open "$url" >/dev/null 2>&1 &
fi
