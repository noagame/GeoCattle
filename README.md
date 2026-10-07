# GeoCattle SaaS · V1

Aplicación web de supervisión bovina basada en el segundo informe de desarrollo de GeoCattle. Frontend React/TypeScript/Leaflet, backend FastAPI y PostgreSQL/PostGIS, con operación local y entornos de simulación y piloto separados. Los informes y archivos originales se conservaron intactos.

## Inicio rápido

Requiere Docker, Docker Compose 2 o superior y Python 3 para generar configuración. Si existe un ejecutable oficial local en `.runtime/docker-compose`, el wrapper lo utiliza; no se necesita modificar Docker globalmente.

```bash
cd geocattle-saas
bash scripts/start.sh
```

Abre [GeoCattle](http://localhost:8080). Usuario: `demo@geocattle.local`. La contraseña aleatoria está en `DEMO_PASSWORD` del archivo privado `.env`; ese archivo se genera con permisos 600 y no se incluye en Git. La demo inicial contiene 70 bovinos sintéticos, collares y sectores de ejemplo. Nunca se presenta como telemetría real.

El arranque aplica migraciones versionadas, inicia API y worker y carga la demo mediante un comando explícito. Repetir la carga conserva los datos existentes. La API y el worker usan un usuario de base de datos distinto del usuario que realiza migraciones.

```bash
# Estado, logs y apagado sin borrar datos
bash scripts/compose.sh ps
bash scripts/compose.sh logs --tail=100 api worker
bash scripts/compose.sh down

# Volver a iniciar, conservar volúmenes y datos
bash scripts/compose.sh up -d
```

## Funcionalidades

- Cuentas con sesión HttpOnly, vencimiento, CSRF y permisos por predio/rol.
- Resumen del rebaño y mapa Leaflet con filtros, estado, calidad y antigüedad explícitos. Cuadrícula local disponible sin cartografía externa.
- Registro DIIO, carne/leche, sectores, collares y asignaciones históricas.
- Geocercas GeoJSON válidas y versionadas, edición de polígonos e impacto confirmado.
- Telemetría autenticada, idempotente y permanente; asociación según captura e historial paginado por período.
- Salida tras dos posiciones válidas exteriores; borde interior, GNSS inválido no demuestra regreso.
- Detección independiente de ausencia de comunicación y reglas preventivas configurables.
- Alertas con condición técnica y atención humana independientes; acciones y cambios auditables.
- Muestreo solicitado pendiente hasta confirmación de versión por el dispositivo.
- Bitácora de mantenimiento, avisos externos en cola e intentos visibles, exportación e indicadores locales.
- Simulación de escenarios identificada y bloqueada en producción; puente académico con buffer persistente.

La posición se considera vigente hasta `2T + 30 s`. La ausencia de comunicación se detecta al superar `3T + 30 s` desde una recepción nueva. Reentregas y datos tardíos no rejuvenecen la posición ni la comunicación. La batería se presenta en mV; no se inventa un porcentaje ni una autonomía. Temperatura superficial y actividad no diagnostican enfermedades.

## Estructura

```text
backend/geocattle/      API, seguridad, reglas, ingestión, worker y comandos
backend/tests/          Pruebas de reglas y de integración
frontend/               React, TypeScript, Vite y Leaflet
database/migrations/    Esquema SQL PostgreSQL/PostGIS versionado
infrastructure/         Nginx, Mosquitto, ChirpStack y TLS local
adapters/               Puente académico NDJSON/USB con cola y ACK
qa/                     Verificaciones API y usuarios de prueba aislados
scripts/                Configuración, arranque, respaldos y restauración
docs/                   Requisitos, decisiones, operación y evidencias
```

Documentación: [skills seleccionadas](docs/SKILLS_DESARROLLO.md), [requisitos y trazabilidad del informe](docs/REQUISITOS_INFORME_2.md), [arquitectura](docs/ARQUITECTURA.md), [contrato API](docs/CONTRATO_API.md), [operación](docs/OPERACION.md) y [evidencia de verificación](docs/VERIFICACION.md).

## Desarrollo sin contenedores para la aplicación

La base sigue siendo PostgreSQL/PostGIS; no se sustituye por SQLite.

```bash
bash scripts/compose.sh up -d database
cd backend
uv sync --extra test
cd ../frontend
npm ci
npm run dev
```

Usa `python3 scripts/local_backend.py migrate`, `seed` y `serve` desde la raíz del proyecto para cargar la configuración privada y conectar al PostgreSQL local sin poner contraseñas en la línea de comandos. El frontend Vite usa `http://localhost:5173` y proxy hacia la API `8000`.

## Verificaciones

```bash
python3 scripts/local_backend.py test
cd frontend && npm run build && cd ..
python3 qa/smoke_api.py
```

Las pruebas de integración modifican exclusivamente el entorno de simulación. Revisa `docs/VERIFICACION.md` para distinguir lo ejecutado de las pruebas de campo aún pendientes. No se afirma haber alcanzado cobertura, autonomía, disponibilidad de siete días o aceptación del productor por pasar pruebas de software.

La implementación inicia el SaaS definido por el informe. Hardware real, OTAA, codec/downlinks, proveedor de avisos, calibración, restauración periódica y aceptación del piloto deben completarse con los equipos y responsables identificados. No se han incorporado cobros ni planes de suscripción porque el informe no especifica esos flujos.

