#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 scripts/configure.py
bash scripts/compose.sh up -d --build
bash scripts/compose.sh --profile tools run --rm seed
echo 'GeoCattle disponible en http://localhost:8080'
echo 'Usuario: demo@geocattle.local. Contraseña: DEMO_PASSWORD en .env'

