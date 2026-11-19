# GeoCattle

GeoCattle es una aplicación de supervisión bovina con mapas, geocercas, telemetría de collares y gestión sanitaria por predio. Usa **React, TypeScript y Leaflet** en la interfaz, **FastAPI** en el servidor y **PostgreSQL/PostGIS** para guardar datos y evaluar geometrías.

## Estado del sistema

Revisión del **18 de noviembre de 2026**.

| Área | Estado |
|---|---|
| Aplicación | Gestión de predios, usuarios, bovinos, fichas sanitarias, alertas y telemetría. |
| Geocercas | Varias geocercas por predio, una zona vigilada por animal y traslado de collares con vigencias históricas. |
| Mapa sin Internet | Imagen satelital de Temuco incluida, escala métrica y soporte para ortofotos y caminos locales. |
| Inventario de gateways | Registro, ubicación, edición, archivado e historial de recepciones, con migración `005`. [Detalle](docs/CRUD_GATEWAYS.md). |
| Captura USB | Selector **Directo** o **Gateways**, detección por identidad USB, lotes JSON, cola local y reintentos ante fallos de entrega o bloqueos breves del archivo de estado. [Operación](docs/DESARROLLO_LOCAL.md). |
| Registro veterinario | Ficha técnica, mediciones y cambios sanitarios con historial protegido. La migración `006` adapta el guardado al rol restringido de PostgreSQL. |
| Alertas de sensores | Umbral térmico, mínimo de actividad y duración configurables por predio. El simulador permite probar cambios antes de guardarlos. |
| Acceso de administrador | Usuario y contraseña en desarrollo y simulación. El TOTP es configurable para ese inicio de sesión. [Configuración](#acceso-de-administrador). |
| Hardware | Código Arduino del collar, las dos receptoras y los dos repetidores. [Firmware](firmware/README.md). |
| Docker y LoRaWAN | Docker levanta la aplicación y admite perfiles MQTT/ChirpStack. La validación física de LoRaWAN está pendiente. |

El código de la aplicación y de la captura se mantiene en `main`. Para contribuir consulta [CONTRIBUTING.md](CONTRIBUTING.md). Las comprobaciones de GitHub cubren compilación del frontend, contratos de captura, reglas de dominio y API con PostGIS temporal. El ensayo físico por repetidores del 10 de noviembre verificó recepción y persistencia de lotes en el prototipo local.

## Funcionalidades

- Sesiones HttpOnly, CSRF, permisos por predio y roles de administrador, dueño, trabajador y veterinario. TOTP configurable para el inicio de sesión de administrador y verificación adicional para operaciones sensibles.
- Contexto multipredio, gestión de clientes, invitaciones, membresías, confianza por acción y aprobación de propuestas del trabajador. Las invitaciones vencidas se consultan mediante el filtro correspondiente.
- Bovinos con DIIO, ficha técnica y sanitaria, historial, tratamientos y agenda con autoría.
- Mapa Leaflet con imagen satelital y cartografía vial locales, OpenStreetMap opcional, escala métrica, recentrado y dibujo de geocercas versionadas.
- Asociaciones históricas entre collar y animal, sector y geocerca, con vigencias que preservan las lecturas anteriores. En **Territorio → Sectores y geocercas** se puede trasladar un animal con su collar a otro potrero.
- Recepción académica LoRa directo mediante una T3 USB con CSV V4 y JSON V5, y captura de lotes JSON mediante una T3 base. La cola local deduplica y reintenta la entrega a la API.
- Visualización de GPS, satélites usados, HDOP, temperatura superficial, aceleración, actividad, movimiento, batería, USB y calidad radio según los campos recibidos.
- Historial paginado, gráficas y trayectoria por collar, registro diario y exportación JSONL de la página consultada.
- **Alertas y atención → Configurar alertas** reúne batería, temperatura, actividad y cercanía al límite de geocerca. Dueño y administrador pueden simular reglas de sensores y guardar valores por predio con versión y auditoría.
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
.\.venv-capture\Scripts\python.exe scripts/start_capture.py --backend docker --select-mode
```

En Linux usa `python3` y `.venv-capture/bin/python`. Sustituye el correo y el nombre del predio. Para una cuenta nueva, consulta `ADMIN_PASSWORD` en `.env.docker`. Abre [GeoCattle en el puerto 8086](http://localhost:8086/) y registra el collar con su identidad y transporte. Crea la asociación vigente con el bovino para atribuir sus lecturas.

Conecta la T3 receptora al anfitrión por USB de datos, enciende el collar y cierra Monitor Serie y Plotter. El capturador detecta la receptora por identidad USB y utiliza `.runtime/docker-capture/`. En Linux el usuario necesita permisos sobre el dispositivo serial. En la primera vinculación, deja conectada una sola receptora y espera un paquete LoRa válido.

Para MQTT, añade `--profile iot` al arranque. `--profile lorawan` añade ChirpStack y activa también `iot`. La recepción directa por USB entrega por HTTP a la API.

Comprueba la [salud de la API de Docker](http://localhost:8086/api/v1/health) o el mismo endpoint en `8080` para simulación. Consulta `status` y `logs` con `scripts/docker_project.py`. Usa `backup` para generar un respaldo y `stop` para detener contenedores conservando los volúmenes. Repite `--environment development` y los perfiles que hayas activado al administrar ese entorno. El arranque en Linux x86_64 se comprobó en Docker Desktop sobre Windows. [Evidencia de portabilidad](docs/REVISION_DOCKER_PORTABILIDAD.md).

### Prototipo nativo en Windows

La instalación ya preparada necesita `.env.academic`, PostgreSQL/PostGIS local, `.venv` y el frontend compilado. Sus datos y credenciales se configuran en cada PC. Para una instalación nueva, utiliza los pasos de Docker o consulta la [guía de desarrollo local](docs/DESARROLLO_LOCAL.md).

1. Abre [`Abrir-GeoCattle.cmd`](Abrir-GeoCattle.cmd) para levantar la base, la API y el proceso de alertas. La web abre en [localhost:8084](http://localhost:8084/).
2. Conecta la receptora T3 con un cable USB de datos, enciende el collar y cierra Monitor Serie y Plotter.
3. Abre [`Iniciar-Captura.cmd`](Iniciar-Captura.cmd). Elige **Directo** para la T3 que recibe del collar o **Gateways** para la T3 base de los repetidores. Se detectará el USB del modo seleccionado.
4. Deja abierta la consola de captura. Comprueba una lectura nueva en [Recepción de collares](http://localhost:8084/#hardware) y confirma la persistencia en PostgreSQL antes de dar por verificada la integración.

Ctrl+C detiene la captura en primer plano. `Pausar-Captura-COM5.ps1` libera el puerto de una captura en segundo plano. `Detener-Prototipo.ps1` detiene los servicios locales. El archivo diario y la cola SQLite están en `.runtime/capture/`. La aplicación persiste las lecturas en PostgreSQL/PostGIS.

En **Recepción de collares**, revisa la última lectura y, por separado, la fecha de la última posición GPS válida. Con la T3 base, **0 saltos** representa recepción directa en la base. Para comprobar el paso por repetidores, verifica que los paquetes registren **1 o 2 saltos**.

El arranque aplica las migraciones pendientes en orden. Respalda la base antes de actualizar una instalación existente y valida primero la migración en una copia.

El engranaje junto a «Cerrar sesión» abre el perfil personal. La barra lateral agrupa las páginas relacionadas según los permisos de cada rol.

### Acceso de administrador

En desarrollo y simulación, el administrador entra con **correo y contraseña**. Usa las credenciales de administrador de tu instalación. En el prototipo existente, abre [GeoCattle local](http://localhost:8084/) tras ejecutar `Abrir-GeoCattle.cmd`.

En una instancia Docker nueva, levanta primero los servicios. Define `V3_ADMIN_PASSWORD` en `.env.docker` y crea el administrador con este comando:

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.usb.yaml --profile tools run --rm --no-deps seed python -m geocattle.seed_v3 --admin-email administrador@example.com
```

Usa una contraseña de al menos doce caracteres y el correo elegido. Para simulación usa `.env` y solo `-f compose.yaml`. Las credenciales y los factores existentes se administran localmente.

Para volver a pedir TOTP al iniciar sesión, define `ADMIN_LOGIN_MFA=true` en el archivo privado del entorno y reinicia la API. `APP_ENV=production` exige TOTP al administrador. La verificación adicional de operaciones sensibles sigue disponible.

### Usuarios y alertas

El administrador crea cuentas de dueños. El dueño invita a trabajadores y veterinarios desde Equipo y permisos. Cada invitado activa su cuenta con un enlace de uso único y vencimiento. Los enlaces se entregan manualmente.

En **Alertas y atención → Configurar alertas**, dueño y administrador pueden editar y guardar los parámetros del predio. Trabajador y veterinario mantienen consulta y atención. **Probar alertas de sensores** usa lecturas simuladas y los valores visibles en el formulario antes de guardarlos. Los resultados de la prueba quedan en pantalla.

- **Temperatura superficial.** Una lectura nueva igual o superior al umbral abre la alerta. Una lectura inferior la resuelve.
- **Actividad reducida.** Un promedio inferior al mínimo durante una ventana completa de lecturas abre la alerta. Una ventana completa cuyo promedio se recupera la resuelve.
- **Activación en terreno.** La activación operativa de temperatura y actividad requiere `PREVENTIVE_RULES_VALIDATED=true`. Al desactivar una regla, las alertas vigentes de ese tipo pasan al historial como resueltas y conservan su evidencia.
- **Prueba térmica del prototipo.** Con `APP_ENV=development`, agrega `PROTOTYPE_TEMPERATURE_ENABLED=true` al archivo privado de entorno (`.env.academic` en Windows nativo o `.env.docker` en Docker físico) y aplica la configuración reiniciando la API. Recarga el panel, activa **Temperatura superficial elevada** y guarda. El valor es `false` por defecto. Esta opción se limita a la regla térmica en desarrollo. [Configuración de alertas](docs/CONFIGURACION_ALERTAS.md).

### Mapa local y traslado de collares

En **Sectores y geocercas**, elige **Satélite local** para abrir la imagen incluida. Cubre 24 × 24 km de Temuco y alrededores, con resolución de origen de 10 m por píxel. Las posiciones y geocercas se dibujan encima y se conservan al cambiar de fondo. GeoCattle y PostgreSQL deben estar disponibles en el PC o la red local. [Fuente y licencia de Sentinel-2](frontend/public/mapa-local/satelite/FUENTE.md).

**Caminos locales** admite una capa opcional `frontend/public/mapa-local/base.geojson`. Exporta cartografía autorizada a GeoJSON `FeatureCollection` en WGS84, con coordenadas `[longitud, latitud]`. Si falta la capa, aparece la cuadrícula WGS84. **OpenStreetMap** utiliza el servicio en línea.

Para instalar una ortofoto del predio, usa un GeoTIFF RGB de 8 bits georreferenciado. El conversor usa `rasterio` y `Pillow` en un entorno Python aparte. Tras generar la carpeta, instala su contenido en `frontend/public/mapa-local/satelite`. En la instalación nativa recompila `frontend` con `npm run build`. En Docker recompila y recrea el servicio `web` usando la configuración con la que se inició ese proyecto.

```bash
python -m pip install rasterio Pillow
python scripts/preparar_mapa_satelital.py predio.tif satelite-nuevo --nombre "Ortofoto del predio" --atribucion "Fuente y fecha" --max-zoom 17
```

El panel **Trasladar collar entre geocercas** preselecciona el collar cuando solo hay uno asociado y destaca su zona vigilada. Selecciona el potrero de destino y confirma el traslado. Cada animal conserva su propio collar, historial y alerta. La salida se confirma con dos posiciones GPS válidas consecutivas fuera de su zona vigente. Para supervisar varios animales a la vez, cada uno necesita un collar activo.

## Desarrollo y verificaciones

```bash
# Backend con PostgreSQL/PostGIS de prueba, según docs/VERIFICACION.md
python3 scripts/local_backend.py test

# Contrato y adaptadores: sin placas ni escritura en la base operativa
python -m unittest qa.test_capture_startup qa.test_serial_receiver qa.test_capture_runtime qa.test_lora_json qa.test_lora_usb qa.test_lora_bus qa.test_receiver_profiles qa.test_receiver_switching qa.test_esp32_contract qa.test_academic_bridge

# Arranque, pruebas HTTP y persistencia en un proyecto Docker aislado
python qa/docker_portability.py

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

Se conservan los documentos originales del repositorio y la telemetría histórica local. Los archivos de entorno privados, bases, colas USB, capturas y credenciales permanecen en cada instalación. El mapa de demostración incluido procede de una fuente pública.

La posición se considera vigente hasta `2T + 30 s`; la ausencia de comunicación supera `3T + 30 s` desde una recepción nueva. Duplicados y datos tardíos no rejuvenecen esos estados. Sin fix no se inventan coordenadas. Si el collar no envía UTC, se marca la hora aproximada de primera recepción del PC.

La batería muestra tensión y, solo si llega en el paquete, porcentaje estimado; no se calcula autonomía ficticia. Temperatura superficial y actividad no diagnostican enfermedades. La captura P2P no es una red LoRaWAN y no garantiza recuperar paquetes que nunca llegaron al PC. Permanecen pendientes la validación de campo, calibración, capacidad de múltiples collares, autonomía, entrega externa de avisos, codec/downlinks, FMA oficial y aceptación del piloto.

El archivo histórico por particiones y los resúmenes materializados son una propuesta documentada, todavía no implementada. El resumen diario actual consulta la telemetría original. No se incorporan cobros ni suscripciones.
