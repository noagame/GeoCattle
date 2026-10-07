#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if docker compose version >/dev/null 2>&1; then
  exec docker compose "$@"
elif [ -x .runtime/docker-compose ]; then
  exec .runtime/docker-compose "$@"
elif command -v docker-compose >/dev/null && docker-compose version --short | grep -Eq '^[2-9]\.'; then
  exec docker-compose "$@"
else
  echo 'Instala Docker Compose 2+ o coloca el ejecutable oficial en .runtime/docker-compose.' >&2
  exit 1
fi
