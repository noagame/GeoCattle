# GeoCattle

GeoCattle es una aplicación de supervisión bovina con mapas, geocercas, telemetría de collares y gestión sanitaria por predio. Usa **React, TypeScript y Leaflet** en la interfaz, **FastAPI** en el servidor y **PostgreSQL/PostGIS** para guardar datos y evaluar geometrías.

## Estado del sistema

Revisión del **16 de noviembre de 2026**.

| Área | Estado |
|---|---|
| Aplicación en `main` | Gestión de predios, usuarios, animales, fichas sanitarias, alertas y telemetría. El acceso de administrador requiere TOTP. |
| Geocercas en `main` | Editor de vértices, geocercas versionadas y ubicación histórica en alertas por pérdida de comunicación. La migración `004` conserva las referencias previas. [Detalle](docs/CORRECCIONES_GEOCERCAS_ALERTAS_2026-10-29.md). |
| Inventario de gateways en `main` | El dueño y el administrador pueden registrar, ubicar, editar y archivar equipos por predio y consultar sus recepciones. La migración `005` conserva el historial. El estado del inventario es administrativo. [Detalle](docs/CRUD_GATEWAYS.md). |
| Captura en `main` | LoRa directo entre un collar y una T3, con USB serial al anfitrión. Admite CSV V4 y JSON V5, incluidos envíos de 45 segundos. |
| Captura por repetidores | En `dev/hardware-captura` existen el selector Directo/Gateways, perfiles USB separados y recepción por lotes. Hay pruebas pendientes antes de integrar. [Estado de la rama](https://github.com/noagame/GeoCattle/blob/dev/hardware-captura/docs/WIP_CAPTURA_GATEWAYS.md). |
| Acceso de administrador en el prototipo local | El inicio de sesión en el PC de desarrollo quedó temporalmente con solo usuario y contraseña. Consulta [la configuración local](#acceso-de-administrador-en-el-prototipo-local). |
| Docker y LoRaWAN | Docker permite arrancar la aplicación y añadir MQTT/ChirpStack mediante perfiles opcionales. La validación física de la red LoRaWAN sigue pendiente. |

La [validación de GitHub de la versión base `37c3d87`](https://github.com/noagame/GeoCattle/actions/runs/42116618131) pasó los controles de frontend, contratos de captura, reglas de dominio y API con PostGIS temporal. Las [pruebas de la rama de captura](https://github.com/noagame/GeoCattle/actions/runs/42661603348) todavía muestran fallos. El ensayo de recepción de lotes del 10 de noviembre corresponde al prototipo local de esa rama.

Consulta [resumen.md](resumen.md) para ver la evolución y la evidencia de verificaciones anteriores.

## Desarrollo separado por áreas

El trabajo de los dos colaboradores se organiza en el mismo repositorio, conservando las carpetas y funcionalidades actuales:

- `main`: versión estable publicada.
- `develop`: integración y revisión de cambios compatibles.
- `dev/software`: interfaz, API, mapas, geocercas, alertas y gestión; referencia de Fabián Del Villar (`noagame`).
- `dev/hardware-captura`: recepción de collares, gateways y protocolos; referencia de Boris (`BorBP`).

**Ambos pueden modificar software y otras áreas.** Las ramas separan tareas, no restringen la edición de archivos. Los contratos compartidos se revisan entre ambos antes de integrar por PR hacia `develop`; las entregas revisadas pasan después a `main`.

Ver [CONTRIBUTING.md](CONTRIBUTING.md) y [Desarrollo colaborativo](docs/DESARROLLO_COLABORATIVO.md) para sincronizar sin reemplazar el trabajo del otro, conocer los controles automáticos y configurar las protecciones de GitHub. El trabajo de receptores que sigue pendiente queda identificado como desarrollo en curso en su rama; no se publica automáticamente como estable.

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

## Cómo levantar GeoCattle

Usa la raíz del repositorio como directorio de trabajo. Para una instalación nueva, clona `main` con `git clone --branch main https://github.com/noagame/GeoCattle.git` y entra en `GeoCattle`.

| Entorno | Archivo privado | Web por defecto | Puerto PostgreSQL |
|---|---|---|---|
| Docker con datos de demostración | `.env` | `8080` | `55432` |
| Docker con hardware físico | `.env.docker` | `8086` | `55436` |
| Prototipo nativo de Windows ya preparado | `.env.academic` | `8084` | `55434` |

### Docker en Windows y Linux

Se requiere Python 3.11 o posterior, Docker con motor Linux activo y Docker Compose 2 o posterior. Ejecuta `docker version` y comprueba que aparezca la sección del servidor. El primer arranque descarga y construye imágenes. [Instalación oficial de Compose](https://docs.docker.com/compose/install/).

**Demostración**, desde PowerShell:

```powershell
py -3 scripts/docker_project.py start
```

En Linux, usa `python3` en lugar de `py -3`. El iniciador crea la configuración si falta, levanta PostgreSQL/PostGIS, aplica las migraciones, inicia API, proceso de alertas y web, y carga la demo. Abre [GeoCattle en el puerto 8080](http://localhost:8080/). El usuario inicial es `demo@geocattle.local` y su contraseña se consulta localmente en `DEMO_PASSWORD` de `.env`. Los 70 bovinos de la demo son sintéticos.

**Captura física con Docker**, desde PowerShell:

```powershell
py -3 scripts/docker_project.py start --environment development --owner-email propietario@example.com --farm "Mi predio"
py -3 -m venv .venv-capture
.\.venv-capture\Scripts\python.exe -m pip install -r adapters/requirements.txt
.\.venv-capture\Scripts\python.exe scripts/start_capture.py --backend docker
```

En Linux usa `python3` y `.venv-capture/bin/python`. Sustituye el correo y el nombre del predio. Para una cuenta nueva, consulta `ADMIN_PASSWORD` en `.env.docker`. Abre [GeoCattle en el puerto 8086](http://localhost:8086/) y registra el collar con su identidad y transporte. Crea la asociación vigente con el bovino para atribuir sus lecturas.

Conecta la T3 receptora al anfitrión por USB de datos, enciende el collar y cierra Monitor Serie y Plotter. El capturador detecta la receptora por identidad USB y utiliza `.runtime/docker-capture/`. En Linux el usuario necesita permisos sobre el dispositivo serial. En la primera vinculación, deja conectada una sola receptora y espera un paquete LoRa válido.

Para MQTT, añade `--profile iot` al arranque. `--profile lorawan` añade ChirpStack y activa también `iot`. La recepción directa por USB entrega por HTTP a la API.

Comprueba la [salud de la API de Docker](http://localhost:8086/api/v1/health) o el mismo endpoint en `8080` para simulación. Consulta `status` y `logs` con `scripts/docker_project.py`. Usa `backup` para generar un respaldo y `stop` para detener contenedores conservando los volúmenes. Repite `--environment development` y los perfiles que hayas activado al administrar ese entorno. El arranque en Linux x86_64 se comprobó en Docker Desktop sobre Windows. [Evidencia de portabilidad](docs/REVISION_DOCKER_PORTABILIDAD.md).

### Prototipo nativo en Windows

La instalación ya preparada necesita `.env.academic`, PostgreSQL/PostGIS local, `.venv` y el frontend compilado. Sus datos y credenciales se configuran en cada PC. Para una instalación nueva, utiliza los pasos de Docker o consulta la [guía de desarrollo local](docs/DESARROLLO_LOCAL.md).

1. Abre [`Abrir-GeoCattle.cmd`](Abrir-GeoCattle.cmd) para levantar la base, la API y el proceso de alertas. La web abre en [localhost:8084](http://localhost:8084/).
2. Conecta la receptora T3 con un cable USB de datos, enciende el collar y cierra Monitor Serie y Plotter.
3. Abre [`Iniciar-Captura.cmd`](Iniciar-Captura.cmd). En `main` inicia la captura directa con identificación USB. En el prototipo local de la rama de hardware, el mismo archivo permite elegir **Directo** o **Gateways**.
4. Deja abierta la consola de captura. Comprueba una lectura nueva en [Recepción de collares](http://localhost:8084/#hardware) y confirma la persistencia en PostgreSQL antes de dar por verificada la integración.

Ctrl+C detiene la captura en primer plano. `Pausar-Captura-COM5.ps1` libera el puerto de una captura en segundo plano. `Detener-Prototipo.ps1` detiene los servicios locales. El archivo diario y la cola SQLite están en `.runtime/capture/`. La aplicación persiste las lecturas en PostgreSQL/PostGIS.

En `main`, el arranque aplica hasta `005_gateway_management.sql`. Respalda la base antes de actualizar una instalación existente y valida primero la migración en una copia.

### Acceso de administrador en el prototipo local

En el PC donde se preparó el prototipo, se desactivó temporalmente el código de doble verificación **al entrar al panel de administración**. Abre `Abrir-GeoCattle.cmd`, entra en [GeoCattle local](http://localhost:8084/) e inicia sesión con el usuario y la contraseña de administrador que ya tienes. Las operaciones sensibles conservan su verificación adicional.

Esta opción corresponde al backend modificado de esa instalación nativa de Windows, en `development` y con acceso desde el mismo equipo. Su configuración privada en `.env.academic` usa `LOCAL_ADMIN_PASSWORD_ONLY=true`. Para volver a pedir el código al iniciar sesión, cambia el valor a `false` y reinicia la API local. Puedes reiniciar con `Detener-Prototipo.ps1` y volver a abrir `Abrir-GeoCattle.cmd` y, si corresponde, `Iniciar-Captura.cmd`.

Una instalación nueva desde `main` conserva el requisito de TOTP. La opción temporal requiere el cambio de backend del prototipo y está documentada aquí como parte del estado de ese equipo.

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
npm test
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
- [Gestión e historial de gateways](docs/CRUD_GATEWAYS.md).
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
