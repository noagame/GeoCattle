# GeoCattle

Aplicación de supervisión bovina con mapas, geocercas, telemetría de collares y gestión sanitaria por predio. Frontend **React/TypeScript/Leaflet**, backend **FastAPI** y base **PostgreSQL/PostGIS**.

## Actualización del 25 de octubre de 2026

Esta versión incorpora la recepción física USB/LoRa por identidad USB, la visualización de sensores, mejoras de mapas y asociaciones históricas, el registro de colaboradores mediante el dueño y la configuración de alertas por predio. Incluye además el arranque Docker para Windows/Linux y su verificación aislada.

Consulta [resumen.md](resumen.md) para ver los cambios, las verificaciones y los límites de esta entrega.

## Funcionalidades

- Sesiones HttpOnly, CSRF, permisos por predio y roles de administrador, dueño, trabajador y veterinario. MFA TOTP para administración y operaciones sensibles.
- Contexto multipredio, gestión de clientes, invitaciones, membresías, confianza por acción y aprobación de propuestas del trabajador.
- Bovinos con DIIO, ficha técnica y sanitaria, historial, tratamientos y agenda con autoría.
- Mapa Leaflet con OpenStreetMap opcional y cuadrícula local, recentrado y dibujo de geocercas versionadas.
- Asociaciones históricas entre collar y animal, sector y geocerca, con vigencias y sin reatribuir lecturas anteriores.
- Recepción académica LoRa punto a punto mediante una T3 USB: CSV V4 y JSON V5, cola durable, deduplicación y reintentos hacia la API.
- Visualización de GPS, satélites usados, HDOP, temperatura superficial, aceleración, actividad, movimiento, batería, USB y calidad radio según los campos recibidos.
- Historial paginado, gráficas y trayectoria por collar, registro diario y exportación JSONL de la página consultada.
- **Alertas y atención → Configurar alertas**: batería, temperatura, actividad y cercanía al límite de geocerca. Solo dueño y administrador pueden guardar parámetros; cada cambio conserva versión y auditoría.
- Condición técnica de las alertas separada de su atención humana; supervisión de ausencia de comunicación y vigencia GPS.
- Gateways, KPI, mantenimiento, auditoría, avisos externos en cola y simulación identificada y separada del hardware real.

## Docker en Windows y Linux

El arranque común utiliza Python 3.11+ y Docker con contenedores Linux y Compose 2+. No exige Bash, Node ni PostgreSQL instalados en el anfitrión. Docker Desktop incluye Compose; en Linux también puede utilizarse Docker Engine con el plugin Compose. Ver [instalación oficial](https://docs.docker.com/compose/install/).

Desde la raíz del repositorio, en Windows:

```powershell
py -3 scripts/docker_project.py start
```

En Linux:

```bash
python3 scripts/docker_project.py start
```

La simulación abre `http://localhost:8080`, utiliza `.env` y prepara una demo sintética. La cuenta inicial es `demo@geocattle.local`; la contraseña aleatoria se consulta localmente en `DEMO_PASSWORD`. Los 70 bovinos de la demo no son una prueba de capacidad radio.

Para una instalación Docker separada que reciba datos físicos, usar `start --environment development`, opcionalmente con `--owner-email CORREO --farm "Nombre del predio"` para crear su primer dueño. Utiliza `.env.docker`, web `8086`, PostgreSQL `55436` y archivo `.runtime/docker-capture/`; no importa ni modifica la instancia nativa `8084` y `.env.academic`.

```text
python scripts/docker_project.py status
python scripts/docker_project.py logs
python scripts/docker_project.py backup
python scripts/docker_project.py stop
```

En Linux, utilizar `python3`; para desarrollo, añadir `--environment development` a cada acción. `stop` conserva los volúmenes. Los archivos de configuración existentes no se sobrescriben y los respaldos se generan en `backups/` sin imprimir credenciales.

La captura USB se ejecuta en el anfitrión con `scripts/start_capture.py --backend docker`, usando un Python con `adapters/requirements.txt`. La receptora se identifica por USB y su puerto puede cambiar: no se presupone un COM fijo ni un USB directamente accesible dentro del contenedor. Registrar los dispositivos y asociaciones en la instalación elegida antes de atribuir las lecturas.

La revisión aprobó **90 pruebas Windows**, **113 pruebas backend y 94 de adaptadores/hardware en Linux**, **126 comprobaciones HTTP** y la persistencia de **589 lecturas QA** tras reiniciar Docker. También se comprobaron MQTT, el worker de alertas y el esquema de ChirpStack. Linux se ejecutó en contenedores x86_64 sobre Docker Desktop; otro PC físico, ARM y el USB real hacia Docker siguen pendientes. Consulta [revisión Docker y portabilidad](docs/REVISION_DOCKER_PORTABILIDAD.md) y [evidencia QA](docs/evidencias/docker_portabilidad_2026-10-25.json).

## Prototipo físico en Windows

La instancia local preparada sirve [Recepción de collares](http://localhost:8084/#hardware), con PostgreSQL/PostGIS en el puerto 55434. La T3 se reconoce por su identidad USB y recibe por LoRa al emisor T-Beam; no hace falta conectar ambos por USB de datos simultáneamente.

**Una clonación nueva no incluye la base física, los binarios locales ni las credenciales del PC.** Los scripts siguientes requieren esa preparación local, `.env.academic`, un entorno Python con las dependencias de backend y adaptadores, y el frontend compilado. Consulta [Desarrollo local](docs/DESARROLLO_LOCAL.md) y [USB COM5](docs/USB_COM5.md). No ejecutar el seed de simulación sobre la base física.

Para capturar con un solo paso, abre **Iniciar-Captura.cmd**. La receptora se reconoce por su identidad USB y puede cambiar de COM. El primer enlace se confirma con un paquete LoRa; consulta [Desarrollo local](docs/DESARROLLO_LOCAL.md#captura-con-doble-clic-e-identidad-usb).

Desde PowerShell en la raíz del proyecto:

```powershell
.\Iniciar-Prototipo.ps1
# Reiniciar solo la API después de actualizar Python:
.\Actualizar-Visualizacion.ps1
# Liberar COM5 para usar Arduino IDE:
.\Pausar-Captura-COM5.ps1
# Cerrar servicios conservando los datos:
.\Detener-Prototipo.ps1
```

Cerrar Monitor Serie y Plotter antes de capturar; solo un proceso puede abrir el puerto. `Iniciar-Captura-COM5.ps1` permite capturar en primer plano y `Reiniciar-Prototipo.ps1` reinicia el prototipo completo.

Las capturas diarias y la cola SQLite son un archivo intermedio local; **PostgreSQL/PostGIS sigue siendo la base de la aplicación**. No se necesita Arduino IDE para ejecutar el software. El firmware y las herramientas de programación de placas no forman parte de esta actualización.

## Usuarios y alertas

El administrador crea las cuentas de dueños/clientes. **El dueño invita a trabajadores y veterinarios** desde Equipo y permisos; cada persona activa su cuenta mediante un enlace con vencimiento y uso único. El administrador conserva la gestión de colaboradores ya incorporados, pero no crea nuevas invitaciones en nombre del dueño. Los enlaces se entregan manualmente: no hay correo externo configurado.

Las instalaciones nuevas crean su primer administrador de forma explícita con `python -m geocattle.seed_v3 --admin-email CORREO` y `V3_ADMIN_PASSWORD` (mínimo doce caracteres), usando el servicio tools/seed y la credencial de migración. Debe configurar TOTP para ingresar. No se publican contraseñas ni factores MFA de prueba.

En **Alertas y atención**, solo dueño y administrador del predio seleccionado pueden configurar parámetros. Trabajador y veterinario mantienen consulta y atención. Temperatura y actividad permiten preparar umbrales, pero su activación fuera de simulación conserva la validación preventiva pendiente de terreno. Las reglas automáticas de comunicación y salida de geocerca mantienen su comportamiento.

## Desarrollo y verificaciones

```bash
# Backend con PostgreSQL/PostGIS de prueba, según docs/VERIFICACION.md
python3 scripts/local_backend.py test

# Contrato y adaptadores: sin placas ni escritura en la base operativa
python -m unittest qa.test_capture_startup qa.test_serial_receiver qa.test_capture_runtime qa.test_lora_json qa.test_lora_usb qa.test_esp32_contract qa.test_academic_bridge

# Interfaz
cd frontend
npm ci
npm run build
```

Para trabajar sin contenedores en la aplicación, usa PostgreSQL/PostGIS y `uv sync --extra test` dentro de `backend/`. `scripts/local_backend.py` ofrece `migrate`, `seed` y `serve` desde la raíz; Vite usa `http://localhost:5173` con proxy hacia la API en el puerto 8000. Ver [Operación](docs/OPERACION.md) y [Verificación](docs/VERIFICACION.md).

Las pruebas de integración deben apuntar a una base aislada mediante la configuración documentada. Las pruebas de hardware API requieren además `GEOCATTLE_TEST_DATABASE=1` y fixtures preparados; no deben ejecutarse indiscriminadamente sobre la base física.

## Estructura

```text
backend/geocattle/      API, seguridad, reglas, ingestión y worker
backend/tests/          Pruebas de dominio e integración
frontend/               React, TypeScript, Vite y Leaflet
database/migrations/    Esquema SQL PostgreSQL/PostGIS versionado
adapters/               Contrato LoRa, captura USB y cola durable
scripts/                Arranque, configuración, exportación y respaldos
infrastructure/         Nginx, Mosquitto, ChirpStack y TLS local
qa/                     Contratos, adaptadores y verificaciones aisladas
docs/                   Arquitectura, operación, informes y evidencias
```

## Documentación

- [Revisión Docker y portabilidad Windows/Linux](docs/REVISION_DOCKER_PORTABILIDAD.md).

- [Resumen de cambios](resumen.md).
- [Desarrollo local](docs/DESARROLLO_LOCAL.md) y [visualización de telemetría](docs/VISUALIZACION_TELEMETRIA.md).
- [Contrato API y radio JSON V5](docs/CONTRATO_API.md#captura-radio-json-v5).
- [Mapas, asociaciones y perfiles](docs/REVISION_MAPAS_ASOCIACIONES_PERFILES.md).
- [Usuarios y registro mediante el dueño](docs/USUARIOS_Y_REGISTRO.md).
- [Configuración de alertas](docs/CONFIGURACION_ALERTAS.md).
- [Almacenamiento diario e histórico](docs/INFORME_ALMACENAMIENTO_TELEMETRIA.md).
- [Arquitectura](docs/ARQUITECTURA.md), [modelo de base](docs/MODELO_BASE_DATOS.md) y [migración V3](docs/MIGRACION_V3.md).
- [Implementación V3](docs/IMPLEMENTACION_V3.md), [requisitos](docs/REQUISITOS_INFORME_2.md), [verificación](docs/VERIFICACION.md) y planificación en `docs/planificacion/`.

## Datos y alcance

Se conservan los documentos originales del repositorio y la telemetría histórica local. `.env*`, `.runtime/`, bases, colas, capturas, credenciales y dependencias generadas quedan fuera de Git; las evidencias nuevas publicadas utilizan datos QA o muestran formularios sin ubicación privada.

La posición se considera vigente hasta `2T + 30 s`; la ausencia de comunicación supera `3T + 30 s` desde una recepción nueva. Duplicados y datos tardíos no rejuvenecen esos estados. Sin fix no se inventan coordenadas. Si el collar no envía UTC, se marca la hora aproximada de primera recepción del PC.

La batería muestra tensión y, solo si llega en el paquete, porcentaje estimado; no se calcula autonomía ficticia. Temperatura superficial y actividad no diagnostican enfermedades. La captura P2P no es una red LoRaWAN y no garantiza recuperar paquetes que nunca llegaron al PC. Permanecen pendientes la validación de campo, calibración, capacidad de múltiples collares, autonomía, entrega externa de avisos, codec/downlinks, FMA oficial y aceptación del piloto.

El archivo histórico por particiones y los resúmenes materializados son una propuesta documentada, todavía no implementada. El resumen diario actual consulta la telemetría original. No se incorporan cobros ni suscripciones.
