# GeoCattle

Guía de levantamiento revisada el **9 de noviembre de 2026**. Consulta primero [los entornos y pasos de arranque](#levantamiento-completo-elegir-el-entorno).

Estado remoto comprobado: `main` en `37c3d87`, `develop` en `dda2ba7`, `dev/software` en `d7f29b7` y `dev/hardware-captura` en `3574754`. Main incluye gestión de gateways (migración 005) y documentación de dominio; hardware mantiene trabajo de captura pendiente. Estos identificadores describen la revisión, no fijan futuras versiones.

## Cambios funcionales y versión de referencia

Editor de geocercas con vértices seleccionables y arrastrables, edición sincronizada por coordenadas, deshacer y confirmaciones de borrado. Varias geocercas independientes por sector y varios sectores por geocerca, con versiones e historial conservados. Las alertas de desconexión muestran la última ubicación válida conocida al detectar el evento, sin sustituirla al reconectarse el collar. Se aclara el funcionamiento de la regla térmica y se mantiene la validación de campo como requisito de activación real.

Detalles, contrato y límites: [correcciones de geocercas y alertas](docs/CORRECCIONES_GEOCERCAS_ALERTAS_2026-10-29.md). La migración `004_geofence_identity_event_position.sql` se aplica con el arranque habitual, después de respaldar la base.


Aplicación de supervisión bovina con mapas, geocercas, telemetría de collares y gestión sanitaria por predio. Frontend **React/TypeScript/Leaflet**, backend **FastAPI** y base **PostgreSQL/PostGIS**.

## Base funcional incorporada el 25 de octubre de 2026

Esta versión incorpora la recepción física USB/LoRa por identidad USB, la visualización de sensores, mejoras de mapas y asociaciones históricas, el registro de colaboradores mediante el dueño y la configuración de alertas por predio. Incluye además el arranque Docker para Windows/Linux y su verificación aislada.

Consulta [resumen.md](resumen.md) para ver los cambios, las verificaciones y los límites de esta entrega.

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
- Mapa Leaflet con imagen satelital y cartografía vial locales, OpenStreetMap opcional, escala métrica, recentrado y dibujo de geocercas versionadas.
- Asociaciones históricas entre collar y animal, sector y geocerca, con vigencias y sin reatribuir lecturas anteriores.
- Recepción académica LoRa punto a punto mediante una T3 USB: CSV V4 y JSON V5, cola durable, deduplicación y reintentos hacia la API.
- Visualización de GPS, satélites usados, HDOP, temperatura superficial, aceleración, actividad, movimiento, batería, USB y calidad radio según los campos recibidos.
- Historial paginado, gráficas y trayectoria por collar, registro diario y exportación JSONL de la página consultada.
- **Alertas y atención → Configurar alertas**: batería, temperatura, actividad y cercanía al límite de geocerca. Solo dueño y administrador pueden guardar parámetros; cada cambio conserva versión y auditoría.
- Condición técnica de las alertas separada de su atención humana; supervisión de ausencia de comunicación y vigencia GPS.
- Gateways, KPI, mantenimiento, auditoría, avisos externos en cola y simulación identificada y separada del hardware real.

## Levantamiento completo: elegir el entorno

Revisión de instrucciones: **9 de noviembre de 2026**. Los comandos siguientes se ejecutan en la raíz del repositorio.

| Uso | Configuración | Web por defecto | PostgreSQL anfitrión | Captura USB |
|---|---|---|---|---|
| Demostración sintética Docker | `.env`, simulation | 8080 | 55432 | No enviar datos físicos |
| Hardware real con Docker | `.env.docker`, development | 8086 | 55436 | Proceso separado en el anfitrión |
| Prototipo nativo Windows ya preparado | `.env.academic` | 8084 | 55434 | Proceso Windows |

Los puertos pueden cambiar en la configuración privada. Cada entorno conserva sus datos; arrancar Docker no importa la base del prototipo nativo. Para una instalación nueva se recomienda Docker sobre `main`. La rama `dev/hardware-captura` incorpora selección Directo/Gateways todavía en desarrollo.

### 1. Requisitos y copia del código

- Git para clonar; Python 3.11 o superior.
- Docker con motor **Linux** activo y Docker Compose 2 o posterior compatible.
- En Windows, Docker Desktop con su backend WSL2/virtualización preparado. En Linux, Docker Engine y Compose accesibles por el usuario.
- Acceso a Internet para la primera descarga de imágenes y dependencias; puertos disponibles y espacio para imágenes, volúmenes y respaldos.

No hace falta instalar Node ni PostgreSQL en el anfitrión para la aplicación Docker. La captura USB sí necesita Python y sus dependencias en el equipo que conecta la receptora.

En una carpeta nueva:

```text
git clone --branch main https://github.com/noagame/GeoCattle.git
cd GeoCattle
docker version
docker compose version
```

`docker version` debe mostrar también la versión del **servidor**. Que Compose esté instalado no significa que el motor esté funcionando. Para una copia existente, revisar `git status` y `git branch --show-current` antes de actualizar; seguir [la guía de colaboración](docs/DESARROLLO_COLABORATIVO.md) para conservar cambios propios.

### 2. Arranque de simulación (sin placas)

Windows PowerShell:

```powershell
py -3 scripts/docker_project.py start
```

Linux:

```bash
python3 scripts/docker_project.py start
```

El iniciador genera `.env` si falta, conserva configuraciones existentes, construye imágenes, inicia servicios y carga la demo sintética. Abrir `http://localhost:8080`. Usuario inicial: `demo@geocattle.local`; consultar **localmente** `DEMO_PASSWORD` en el archivo privado. No publicar ese archivo ni sus valores.

La demo de 70 bovinos sirve para recorrer la aplicación; no demuestra una red física de 70 collares.

### 3. Arranque para datos físicos con Docker

Windows:

```powershell
py -3 scripts/docker_project.py start --environment development --owner-email propietario@example.com --farm "Mi predio"
```

Linux:

```bash
python3 scripts/docker_project.py start --environment development --owner-email propietario@example.com --farm "Mi predio"
```

Sustituir correo y predio por los que se utilizarán. Se prepara `.env.docker`, se levanta la aplicación y se crea el dueño si no existe. Su contraseña inicial procede de `ADMIN_PASSWORD` de ese archivo privado; las credenciales de una cuenta existente no se sustituyen. Abrir `http://localhost:8086`. Si se omiten correo/predio, arrancan los servicios pero no se crea una cuenta nueva.

Antes de atribuir lecturas, registrar en esta instalación el collar con su identidad y transporte compatibles, el bovino y su asociación vigente. Una base Docker nueva no contiene las asociaciones de la instalación nativa. Las lecturas sin asociación no deben atribuirse retroactivamente por suposición.

### 4. Iniciar la captura USB en el anfitrión

Conectar la **receptora T3** por cable USB de datos y alimentar el collar. Cerrar Monitor Serie/Plotter y cualquier lector del mismo puerto. No es necesario conectar el collar por USB al computador.

Windows, primera preparación:

```powershell
py -3 -m venv .venv-capture
.\.venv-capture\Scripts\python.exe -m pip install -r adapters/requirements.txt
.\.venv-capture\Scripts\python.exe scripts/start_capture.py --backend docker
```

Linux:

```bash
python3 -m venv .venv-capture
.venv-capture/bin/python -m pip install -r adapters/requirements.txt
.venv-capture/bin/python scripts/start_capture.py --backend docker
```

En Linux se necesita permiso sobre el dispositivo serial, normalmente mediante el grupo de dispositivos de la distribución (por ejemplo, `dialout`) y una nueva sesión tras cambiar la pertenencia. No usar permisos universales como solución permanente.

El iniciador usa `.env.docker`, exige development sin simulación y reconoce la receptora por identidad USB; no presupone COM5. En el primer enlace conectar solo la receptora que se desea recordar y esperar un paquete válido con información radio. Se conserva la cola en `.runtime/docker-capture/`. El contenedor API lee su estado mediante `compose.usb.yaml`; el puerto USB se abre en el anfitrión.

Dejar la ventana de captura abierta. `Ctrl+C` detiene el lector conservando datos. Evitar arrancar un segundo lector sobre el mismo archivo de captura. Para un archivo de configuración alternativo utilizar el mismo `--env-file RUTA` tanto al levantar Docker como al iniciar captura.

**Solo rama de hardware:** `--select-mode` permite elegir antes de detectar USB, y `--receiver-mode direct` o `--receiver-mode gateways` fija el método. En Windows, `Iniciar-Captura.cmd` muestra el menú al abrirlo sin argumentos. Esas opciones no pertenecen al capturador estable de main; el trabajo de lotes y alternancia conserva verificaciones pendientes. El CRUD de gateways de main es gestión de inventario, no certificación de la red de repetidores.

### 5. Qué levanta cada opción

La aplicación principal inicia **PostgreSQL/PostGIS → migración → API/worker → web** según dependencias de Compose. `start` construye y espera servicios; en simulación ejecuta además el seed. `migrate` es un servicio de una ejecución: terminar correctamente no significa fallo. Los volúmenes conservan la base.

- Web: interfaz y proxy al backend.
- API: sesiones, permisos, ingestión y consultas.
- Worker: evaluación periódica y avisos.
- Captura USB: proceso aparte, necesario para la T3 física.
- Perfil `iot`: broker MQTT e ingestor.
- Perfil `lorawan`: infraestructura ChirpStack/Redis/base asociada; el iniciador añade `iot` automáticamente.

Para activar servicios opcionales en desarrollo (en Windows usar `py -3`):

```bash
python3 scripts/docker_project.py start --environment development --profile iot
# O infraestructura LoRaWAN, que incluye iot:
python3 scripts/docker_project.py start --environment development --profile lorawan
```

La ruta directa T3 → USB → API no requiere MQTT/ChirpStack. Activar servicios LoRaWAN requiere después aprovisionar gateway, dispositivos, claves y codec; no transforma la radio P2P en LoRaWAN. TLS/proveedores externos requieren configuración adicional; el arranque local HTTP no es un despliegue público listo para producción.

### 6. Verificar, respaldar y detener

Windows:

```powershell
py -3 scripts/docker_project.py status --environment development
py -3 scripts/docker_project.py logs --environment development
Invoke-RestMethod http://localhost:8086/api/v1/health
py -3 scripts/docker_project.py backup --environment development
# Detener primero la captura con Ctrl+C:
py -3 scripts/docker_project.py stop --environment development
```

En Linux sustituir `py -3` por `python3`; para salud usar `curl http://localhost:8086/api/v1/health`. En simulación omitir `--environment development` y usar puerto 8080. Con perfiles opcionales, repetir los mismos `--profile` al consultar/detener para abarcar sus servicios.

La salud debe indicar `status: ok` y el entorno elegido. Comprobar después inicio de sesión, predio, collar y una lectura nueva persistida con su fecha/secuencia. API saludable por sí sola no prueba recepción radio. Confirmar datos en Recepción de collares e historial; una línea capturada no demuestra todavía entrega final a PostgreSQL.

`backup` genera un dump en `backups/`; verificar restauración por separado. `stop` conserva volúmenes. No usar `down -v` ni borrar `.runtime` como procedimiento de reinicio. En una actualización con base existente: respaldar primero y validar migraciones en una copia antes de arrancar el código nuevo.

### 7. Diagnóstico rápido

| Síntoma | Revisión |
|---|---|
| No existe dockerDesktopLinuxEngine / servidor no responde | Abrir Docker Desktop, comprobar backend Linux/WSL y repetir docker version |
| Puerto ocupado | Identificar el servicio o configurar otro puerto; no cerrar procesos desconocidos |
| No puede abrir serial | Cerrar otros lectores, revisar identidad USB y permisos; el número COM puede cambiar |
| Recibe pero no persiste | Revisar logs, URL/API, entorno, registro del dispositivo y cola pendiente |
| No aparece posición | Revisar fix/calidad GPS y asociación, sin inventar coordenadas |
| Captura de un entorno frente a web de otro | Hacer coincidir backend, env-file, URL y directorio de captura |
| Error de migración | Conservar error y respaldo; no borrar volúmenes ni marcar migraciones como aplicadas manualmente |

### Evidencia y límites de la revisión

El 9 de noviembre de 2026 pasaron **40 pruebas** de contratos de arranque/configuración y portabilidad de captura. Las ayudas CLI fueron verificadas; Compose validó con `config --quiet` simulación y desarrollo, incluidos iot/lorawan, usando configuración QA independiente. Estos controles no abrieron puertos seriales ni modificaron bases operativas.

En esa revisión el motor Linux de Docker no respondió y no había aplicaciones escuchando en 8080/8084/8086. **No se confirmó un levantamiento real completo en esta ejecución.** Las pruebas de comandos usan Docker simulado y config no necesita un motor activo.

Existe evidencia anterior de Docker Linux x86_64 sobre Windows: 113 pruebas backend, 94 adaptadores/hardware, 126 comprobaciones HTTP y 589 lecturas QA conservadas tras reinicio, además de 90 pruebas Windows. Son resultados históricos, no una prueba nueva ni una certificación de otro PC, ARM o USB real hacia Docker. Ver [revisión Docker](docs/REVISION_DOCKER_PORTABILIDAD.md) y [evidencia](docs/evidencias/docker_portabilidad_2026-10-25.json).

## Prototipo físico en Windows

La instancia local preparada sirve [Recepción de collares](http://localhost:8084/#hardware), con PostgreSQL/PostGIS en el puerto 55434. La T3 se reconoce por su identidad USB y recibe por LoRa al emisor T-Beam; no hace falta conectar ambos por USB de datos simultáneamente.

**Una clonación nueva no incluye la base física, los binarios locales ni las credenciales del PC.** Los scripts siguientes requieren esa preparación local, `.env.academic`, un entorno Python con las dependencias de backend y adaptadores, y el frontend compilado. Consulta [Desarrollo local](docs/DESARROLLO_LOCAL.md) y [USB COM5](docs/USB_COM5.md). No ejecutar el seed de simulación sobre la base física.

Usa estos dos iniciadores con doble clic desde la raíz del proyecto:

| Iniciador | Función |
|---|---|
| [`Abrir-GeoCattle.cmd`](Abrir-GeoCattle.cmd) | Levanta PostgreSQL, la API y el proceso de alertas. Abre la aplicación en el navegador. |
| [`Iniciar-Captura.cmd`](Iniciar-Captura.cmd) | Permite elegir **Directo** o **Gateways** antes de buscar la receptora por identidad USB. Inicia los servicios locales si hacen falta. |

Cierra el Monitor Serie y el Plotter antes de capturar. En el primer enlace espera un paquete válido de la receptora. Deja abierta la ventana mientras dure la captura y usa Ctrl+C para detenerla. Para pausar una captura iniciada en segundo plano, ejecuta `Pausar-Captura-COM5.ps1` desde PowerShell.

El protocolo JSON V5 admite `p` entre `30000` y `45000` ms. El período anunciado queda en `quality.period_ms`. Tras actualizar el adaptador, detén la captura y vuelve a abrir `Iniciar-Captura.cmd`. Para reiniciar todo el prototipo, ejecuta `Detener-Prototipo.ps1` y abre otra vez los iniciadores que necesites.

Las capturas diarias y la cola SQLite son un archivo intermedio local; **PostgreSQL/PostGIS sigue siendo la base de la aplicación**. No se necesita Arduino IDE para ejecutar el software. El firmware y las herramientas de programación de placas no forman parte de esta actualización.

## Mapa sin Internet

Abre el mapa o el editor de geocercas y elige **Satélite local**. Puedes cambiar a **Caminos locales** u **OpenStreetMap** mientras editas. El dibujo, las geocercas y las posiciones permanecen encima al cambiar el fondo. Los dos fondos locales se sirven desde GeoCattle. Mantén encendidos el servidor y PostgreSQL y, si accedes desde otro equipo, conéctalo a la red local del servidor.

La instalación de la demostración usa un recorte de Temuco y alrededores de 24 × 24 km de enero a marzo de 2025, a partir de datos Copernicus Sentinel modificados. La resolución original de 10 m por píxel sirve para reconocer referencias grandes como el río, bosques y límites visibles entre cultivos. Para trazar según cercos individuales o senderos angostos, usa una ortofoto georreferenciada de mayor resolución o verifica los vértices en terreno. La aplicación indica cuando el centro del mapa queda fuera de la imagen instalada. [Mosaicos Copernicus Sentinel-2](https://source.coop/tge-labs/sentinel-2-quarterly-cloudless-mosaics).

La vista vial usa la [Red Vial de la Dirección de Vialidad del MOP](https://mapasvialidad.mop.gob.cl/descargas-2/). Para instalar otra capa de caminos coloca una `FeatureCollection` GeoJSON autorizada en `frontend/public/mapa-local/base.geojson`. Usa WGS84 con coordenadas `[longitud, latitud]`. Puedes incluir `name` para el rótulo y `bbox` para el botón de encuadre. GeoCattle usa los caminos como respaldo si falta el mapa satelital y muestra la cuadrícula WGS84 si falta el archivo vial. OpenStreetMap permanece como opción en línea. [Política de teselas de OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/).

Para reemplazar la imagen con una ortofoto autorizada, prepara un **GeoTIFF RGB de 8 bits georreferenciado**. Usa el conversor en un entorno Python aparte con `rasterio` y `Pillow`. Genera la carpeta en otra ubicación y copia el resultado completo a `frontend/public/mapa-local/satelite`, incluidos `manifest.json` y los directorios de zoom. Para una ortofoto de 1 m por píxel puedes usar `--max-zoom 17`.

```bash
python -m pip install rasterio Pillow
python scripts/preparar_mapa_satelital.py predio.tif satelite-nuevo --nombre "Ortofoto del predio" --atribucion "Autor y fecha de la ortofoto" --max-zoom 17
```

- **Instalación local.** Ejecuta `npm run build` en `frontend` y recarga GeoCattle. Los archivos de `frontend/public/mapa-local` se copian a `frontend/dist/mapa-local`.
- **Docker.** Reconstruye y recrea el servicio `web` con el mismo archivo de entorno y proyecto de la instalación. El Dockerfile incorpora `frontend/public` al compilar.

## Usuarios y alertas

El arranque no crea un administrador global automáticamente. Para provisionarlo en Docker development, definir `V3_ADMIN_PASSWORD` en `.env.docker` (archivo privado) y ejecutar:

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.usb.yaml --profile tools run --rm --no-deps seed python -m geocattle.seed_v3 --admin-email administrador@example.com
```

Sustituir el correo y configurar TOTP. Para simulación usar `.env` y solo `compose.yaml`. Ejecutar después de las migraciones y conservar el segundo factor en una aplicación de autenticación.


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
