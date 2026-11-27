# GeoCattle

> **¿Vas a desplegar o administrar el servidor espejo (Debian) a partir de un paquete `geocattle-*.tar.gz`?** Sigue [docs/DESPLIEGUE_SERVIDOR_ESPEJO.md](docs/DESPLIEGUE_SERVIDOR_ESPEJO.md) y sus reglas: no edites código ni Compose, no crees cuentas en el servidor, no borres volúmenes y deja que el dueño del PC escriba los secretos. El resto de este archivo es para desarrollar GeoCattle.

GeoCattle supervisa ganado por predio. Integra gestión bovina y sanitaria, mapas y geocercas, telemetría de collares, alertas y captura LoRa. Usa FastAPI con Python 3.11+, PostgreSQL/PostGIS y React con TypeScript, Vite y Leaflet. CI usa Python 3.12 y Node.js 22.

## Dónde trabajar

| Área | Ubicación |
| --- | --- |
| API y reglas | `backend/geocattle/`. `main.py` monta la API, `v3_api.py` reúne operaciones V3, `hardware_api.py` expone la captura y `worker.py` ejecuta tareas periódicas. |
| Interfaz | `frontend/src/`. Revisar `api.ts`, `types.ts` y `v3types.ts` al cambiar contratos que consume la interfaz. |
| Esquema | `database/migrations/`. `backend/geocattle/migrate.py` aplica los SQL en orden y registra cada migración. |
| Captura | `adapters/` contiene lectores, parsers y cola de entrega. `scripts/start_capture.py` inicia la captura en el anfitrión. |
| Arranque | `Abrir-GeoCattle.cmd` inicia el prototipo nativo en Windows. `Abrir-GeoCattle-LAN.cmd` añade acceso HTTPS por la red local. `Abrir-GeoCattle.sh` inicia desarrollo en Linux mediante Docker Compose. |
| Pruebas | `backend/tests/`, `frontend/tests/` y `qa/`. Los comandos de CI están en [validacion.yml](.github/workflows/validacion.yml). |

## Contratos que se deben preservar

- Mantén la autorización por predio y rol en el backend. Al cambiar operaciones protegidas, conserva las comprobaciones de sesión, CSRF y MFA que correspondan, y verifica los permisos de los roles afectados. [Usuarios y registro](docs/USUARIOS_Y_REGISTRO.md)
- Conserva las vigencias de las asociaciones collar–bovino y sector–geocerca, las versiones de las geocercas y la autoría de los registros históricos. Para alertas de desconexión conserva la última ubicación válida conocida al detectar el evento. [Geocercas y alertas](docs/CORRECCIONES_GEOCERCAS_ALERTAS_2026-10-29.md)
- Cambia el esquema mediante una nueva migración numerada. Conserva las migraciones ya aplicadas y valida las nuevas en una copia migrada con datos representativos. Respalda la base antes de aplicar cambios en una instalación existente. [Operación](docs/OPERACION.md)
- En captura, conserva la compatibilidad con CSV V4 y JSON V5, la deduplicación, la cola durable y los reintentos. Respeta la identidad USB del receptor y la ausencia de coordenadas cuando el GPS carece de fix. Mantén separados los datos físicos y los simulados. [Contrato API](docs/CONTRATO_API.md) · [Captura USB](docs/USB_COM5.md)
- Conserva secretos, datos físicos, colas SQLite, respaldos y archivos de ejecución de `.runtime/` fuera de Git. Para documentar opciones de configuración, usa valores ficticios en `.env.example`.
- Configura la misma `INVITATION_BASE_URL` para API y worker. Usa la URL que abre el destinatario. El SMTP y el restablecimiento local de TOTP se operan desde el archivo privado de cada despliegue. [Operación](docs/OPERACION.md)

## Arranque y verificación

- **Simulación con Docker**, desde la raíz: `py -3 scripts/docker_project.py start` en Windows o `python3 scripts/docker_project.py start` en Linux. La web usa el puerto `8080` por defecto. Para entorno físico y prototipo Windows, consulta las configuraciones y los pasos del [README](README.md) y de [Desarrollo local](docs/DESARROLLO_LOCAL.md).
- **Producción en Debian 12 o 13**, usa `docker_project.py --environment production --profile cloudflare` con la acción y el archivo privado del despliegue. La web y API se publican por Cloudflare sin puertos en el host. La T3 base entrega por USB al registro local y una segunda T3 (`GeoCattle_Nube_T3`) escucha los mismos lotes, hace de raíz de respaldo si la base está apagada y los entrega por WiFi a producción. Con `--profile mirror` el servidor es un espejo del PC del campo (`MIRROR_MODE`), que sigue como sistema principal y sin T3 nube. [Despliegue en Debian](docs/DESPLIEGUE_DEBIAN_CLOUDFLARE.md) · [Modo espejo](docs/planificacion/PLAN_MODO_ESPEJO.md)
- Compose aplica topes de CPU y memoria y rota logs por servicio. El arranque base usa PostgreSQL/PostGIS, API, worker y web. Los perfiles explícitos habilitan servicios auxiliares. La generación OSM corre bajo demanda, fuera del arranque. [Recursos de Docker Desktop y WSL2](docs/DESARROLLO_LOCAL.md#recursos-de-docker-desktop-y-wsl2)
- En Docker de desarrollo, `compose.usb.yaml` monta el estado USB para la API y el worker. El worker lo publica en modo `field` para el predio de captura. [Estado USB en modo espejo](docs/CONTRATO_API.md#estado-usb-en-modo-espejo)
- **Frontend**, desde `frontend/`: `npm ci`, `npm test` y `npm run build`. El build incluye la comprobación de TypeScript.
- **Reglas del backend**, desde `backend/`: `uv sync --extra test` y `uv run pytest tests/test_rules.py -q`.
- **Integración del backend**, desde la raíz: `py -3 scripts/local_backend.py test --env-file RUTA_QA` en Windows o `python3 scripts/local_backend.py test --env-file RUTA_QA` en Linux. Usa una configuración de simulación que apunte a PostgreSQL/PostGIS de QA previamente migrado. Si ejecutas pytest directamente, apunta `TEST_DATABASE_URL` y `DATABASE_URL` a la misma base aislada. `qa/test_hardware_api.py` requiere además `GEOCATTLE_TEST_DATABASE=1` y fixtures preparados. [Verificación](docs/VERIFICACION.md)
- **Captura sin placas**, desde la raíz: instala `backend/requirements.lock` y `adapters/requirements.txt` en el entorno de pruebas, añade `backend/` a `PYTHONPATH` y replica el bloque `captura_contratos` de CI, incluidas sus variables de entorno. [CI](.github/workflows/validacion.yml)

Ejecuta las verificaciones pertinentes al cambio. Indica qué pruebas se ejecutaron, cuáles se omitieron y si quedó pendiente una validación con hardware. Para detener Docker conservando los datos, usa `scripts/docker_project.py stop` con el mismo entorno y perfiles del arranque.

## Colaboración

- Revisa `git status --short --branch` antes de editar o cambiar de rama. Conserva los cambios existentes y limita el diff al alcance pedido.
- `main` reúne la aplicación y la captura. Integra y publica los cambios en esta rama. Coordina cambios en contratos, migraciones y arranque. Sigue [CONTRIBUTING.md](CONTRIBUTING.md) y [Desarrollo colaborativo](docs/DESARROLLO_COLABORATIVO.md).

# DOX framework

- DOX is highly performant AGENTS.md hierarchy installed here
- Agent must follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:
- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

## Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run existing verification when relevant
6. Report any docs intentionally left unchanged and why

## User Preferences

When the user requests a durable behavior change, record it here or in the relevant child AGENTS.md

- El README presenta primero los arranques de desarrollo en `localhost:8084`. Windows usa `Abrir-GeoCattle.cmd` y Linux usa `Abrir-GeoCattle.sh` con Docker Compose y `.env.docker`. Vite se documenta para la recarga en caliente.
- La base satelital local cubre La Araucanía (detalle máximo solo en Temuco) y se instala fuera de Git en `.runtime/mapa-satelital/`. La cuadrícula WGS84 es el respaldo y OpenStreetMap queda disponible en línea. [Instalación y fuente](docs/MAPA_SATELITAL.md)
- OpenStreetMap local se genera con Docker desde el extracto completo de Chile (sin recortar) y se instala fuera de Git en `.runtime/mapa-osm/`; la interfaz lo ofrece como base aparte de la satelital. [Instalación y fuente](docs/MAPA_OSM_LOCAL.md)

## Child DOX Index

La raíz contiene los archivos de Compose, los lanzadores de Windows y Linux, las reglas de colaboración y los contratos que cruzan áreas. Los índices enlazan los ámbitos hijos directos.

- [.github/AGENTS.md](.github/AGENTS.md) — CI, revisión y plantillas de GitHub.
- [adapters/AGENTS.md](adapters/AGENTS.md) — protocolos, recepción serial y entrega de telemetría.
- [backend/AGENTS.md](backend/AGENTS.md) — aplicación Python, dependencias y pruebas.
- [database/AGENTS.md](database/AGENTS.md) — migraciones y comprobaciones PostgreSQL/PostGIS.
- [docs/AGENTS.md](docs/AGENTS.md) — operación, especificaciones, planificación y evidencias.
- [frontend/AGENTS.md](frontend/AGENTS.md) — aplicación web, mapas, recursos y pruebas.
- [firmware/AGENTS.md](firmware/AGENTS.md) — sketches, identidad del collar y contratos de radio y USB.
- [infrastructure/AGENTS.md](infrastructure/AGENTS.md) — proxy, MQTT y LoRaWAN.
- [qa/AGENTS.md](qa/AGENTS.md) — pruebas transversales y evidencias de QA.
- [scripts/AGENTS.md](scripts/AGENTS.md) — arranque, configuración, respaldos y utilidades.
