# GeoCattle

GeoCattle es una aplicación de supervisión bovina con mapas, geocercas, telemetría de collares y gestión sanitaria por predio. Usa **React, TypeScript y Leaflet** en la interfaz, **FastAPI** en el servidor y **PostgreSQL/PostGIS** para guardar datos y evaluar geometrías.

## Desarrollo local en el puerto 8084

Ejecuta los comandos desde la raíz del repositorio. [Repositorio GeoCattle](https://github.com/noagame/GeoCattle)

### Inicio rápido en Windows

Con la instalación ya preparada, abre [`Abrir-GeoCattle.cmd`](Abrir-GeoCattle.cmd). El lanzador inicia PostgreSQL/PostGIS, aplica las migraciones pendientes, levanta la API y el proceso de alertas, y abre [GeoCattle en localhost:8084](http://localhost:8084/). El acceso inicial está en el archivo privado `.runtime/acceso_prototipo.json`.

El prototipo nativo usa el entorno `development`, la configuración privada `.env.academic`, PostgreSQL/PostGIS local en `127.0.0.1:55434`, el entorno Python `.venv` y la interfaz compilada en `frontend/dist`. Si cambias el frontend, vuelve a compilarlo con `npm run build` dentro de `frontend` antes de abrir el lanzador. Para detener los servicios conservando los datos, ejecuta `.\Detener-Prototipo.ps1`. [Desarrollo local en Windows](docs/DESARROLLO_LOCAL.md)

### Inicio rápido en Linux

Con Docker activo, ejecuta [`Abrir-GeoCattle.sh`](Abrir-GeoCattle.sh) o `bash Abrir-GeoCattle.sh`:

```bash
./Abrir-GeoCattle.sh
```

El iniciador crea `.env.docker` si falta, construye la interfaz y levanta PostgreSQL/PostGIS, la API y el proceso de alertas en contenedores. Abre [localhost:8084](http://localhost:8084/) y, si hay escritorio, intenta abrir el navegador. El correo inicial es `desarrollo@geocattle.local` y la contraseña está en `ADMIN_PASSWORD` del archivo privado `.env.docker`. Para elegir otro correo y nombre de predio en el primer arranque:

```bash
./Abrir-GeoCattle.sh propietario@example.com "Mi predio"
```

Si `.env.docker` ya existe, el iniciador reutiliza la base y las credenciales. La base nueva empieza sin bovinos de demostración y PostgreSQL usa el puerto local `55436`. Para consultar el estado o detener los contenedores conservando la base:

```bash
python3 scripts/docker_project.py status --environment development
python3 scripts/docker_project.py stop --environment development
```

En ambos sistemas, [localhost:8084/api/v1/health](http://localhost:8084/api/v1/health) debe responder con `status: ok` y `environment: development`.

### Instalación desde cero en Windows

Requisitos: Windows 10 u 11 de 64 bits, [Git](https://git-scm.com/download/win), [Python 3.12](https://www.python.org/downloads/windows/) (3.11 o posterior) y [Node.js 22 LTS](https://nodejs.org/). El prototipo nativo no usa Docker ni modifica un PostgreSQL instalado en Windows.

1. Clona el repositorio y crea el entorno Python desde PowerShell:

   ```powershell
   git clone --branch main https://github.com/noagame/GeoCattle.git
   Set-Location GeoCattle
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
   .\.venv\Scripts\python.exe -m pip install -r adapters\requirements.txt
   ```

2. Genera la configuración privada `.env.academic` con secretos aleatorios. El comando nunca reemplaza un archivo existente.

   ```powershell
   .\.venv\Scripts\python.exe scripts\configure.py --environment development
   ```

3. Instala PostgreSQL 16 y PostGIS como binarios portátiles dentro del proyecto:
   - Descarga el ZIP de **PostgreSQL 16 para Windows x86-64** desde [binarios de EDB](https://www.enterprisedb.com/download-postgresql-binaries) y extráelo en `.runtime\postgres16`. Debe existir `.runtime\postgres16\pgsql\bin\pg_ctl.exe`.
   - Descarga el paquete `postgis-bundle-pg16-*x64.zip` desde [PostGIS para Windows](https://download.osgeo.org/postgis/windows/pg16/) y copia el contenido de su carpeta principal sobre `.runtime\postgres16\pgsql`. Debe existir `.runtime\postgres16\pgsql\share\extension\postgis.control`.
   - Si `initdb` indica que falta una DLL, instala el [Visual C++ Redistributable x64](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist).

   La instalación verificada usa PostgreSQL 16.15 y PostGIS 3.6.2.

4. Inicializa la base local con el usuario y la contraseña de `.env.academic`:

   ```powershell
   .\.venv\Scripts\python.exe scripts\prototype_windows.py init
   ```

5. Compila la interfaz:

   ```powershell
   Set-Location frontend
   npm ci
   npm run build
   Set-Location ..
   ```

6. Abre `Abrir-GeoCattle.cmd`. El primer arranque aplica las migraciones, crea la cuenta `prototipo@geocattle.local` con su predio y guarda la contraseña en `.runtime\acceso_prototipo.json`. También deja registrado el collar histórico `REAL01` sin asignación a bovino.

Si falta un paso, el lanzador indica cuál ejecutar. Para enviar invitaciones por correo, agrega la configuración SMTP a `.env.academic`. [Correo SMTP](docs/OPERACION.md) · [Captura USB](#captura-usb-en-desarrollo-nativo)

### Instalación desde cero en Linux

Los pasos usan Ubuntu o Debian. Necesitas Git, Python 3.11 o posterior y Docker Engine con el plugin Compose 2. [Instalación de Docker Engine](https://docs.docker.com/engine/install/)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
# Instala Docker Engine y el plugin Compose según la guía oficial de tu distribución.
sudo usermod -aG docker "$USER"
```

Cierra la sesión y vuelve a entrar para aplicar el grupo `docker`. Comprueba que `docker version` muestre la sección del servidor y luego ejecuta:

```bash
git clone --branch main https://github.com/noagame/GeoCattle.git
cd GeoCattle
./Abrir-GeoCattle.sh propietario@example.com "Mi predio"
```

El primer arranque descarga y construye las imágenes. Después, el [inicio rápido en Linux](#inicio-rápido-en-linux) solo necesita `./Abrir-GeoCattle.sh`. Para capturar por USB, agrega tu usuario al grupo `dialout` con `sudo usermod -aG dialout "$USER"` y vuelve a iniciar sesión. [Captura con Docker](#docker-en-windows-y-linux)

Para usar el PC Windows como servidor para otros dispositivos de la misma red, inicia el prototipo y luego abre [`Abrir-GeoCattle-LAN.cmd`](Abrir-GeoCattle-LAN.cmd). En cada apertura muestra la URL HTTPS para la IP local vigente en el puerto `8445`. Un punto de acceso del celular puede proporcionar la red local. [Configuración de acceso desde otro dispositivo](docs/DESARROLLO_LOCAL.md#acceso-https-desde-otro-dispositivo)

Para incorporar un collar compatible, ejecuta [`Registrar-Collar-USB.cmd`](Registrar-Collar-USB.cmd) en el PC servidor o recibe su primera trama LoRa. Aprueba el alta en **Collares detectados** y asigna el collar después desde la web local o por HTTPS. [Alta por USB o LoRa](docs/DESARROLLO_LOCAL.md#incorporar-un-collar-por-usb-o-lora)

## Estado del sistema

Funciones disponibles en `main`.

| Área | Estado |
|---|---|
| Aplicación | Gestión de predios, usuarios, bovinos, fichas sanitarias, alertas y telemetría. |
| Geocercas | Varias geocercas por predio, una zona vigilada por animal y traslado de collares con vigencias históricas. |
| Mapa sin Internet | Imagen satelital de Temuco incluida, escala métrica y soporte para ortofotos y caminos locales. |
| Inventario de gateways | Registro, ubicación, edición, archivado e historial de recepciones, con migración `005`. [Detalle](docs/CRUD_GATEWAYS.md). |
| Captura USB | Selector **Directo** o **Gateways**, detección por identidad USB, lotes JSON, cola local y reintentos ante fallos de entrega o bloqueos breves del archivo de estado. [Operación](docs/DESARROLLO_LOCAL.md). |
| Registro sanitario | Ficha técnica, mediciones y agenda con historial y autoría. El formulario adapta sus campos al tipo de evento. |
| Reportes del rebaño | Vista previa y CSV de inventario, sanidad, agenda, mediciones, observaciones, asignaciones, alertas y actividad diaria. |
| Indicadores del predio | Totales, serie de alertas y rankings de movimiento y salidas para dueño y administrador con predio seleccionado. |
| Solicitudes y auditoría | Propuestas al dueño con seguimiento de la decisión, y solicitudes privadas de soporte atendidas por el administrador desde el panel global. |
| Alertas de sensores | Umbral térmico, mínimo de actividad y duración configurables por predio. El simulador permite probar cambios antes de guardarlos. |
| Acceso de administrador | Usuario y contraseña en desarrollo y simulación. El TOTP es configurable para ese inicio de sesión y se puede reemplazar, quitar o restablecer. [Configuración](#acceso-de-administrador). |
| Invitaciones por correo | Envío SMTP opcional con STARTTLS o TLS, reintentos y prueba de configuración. Sin SMTP, el enlace se comparte manualmente. [Operación](docs/OPERACION.md). |
| Collares detectados | La captura LoRa y el alta USB registran collares desconocidos en una bandeja por predio. Dueño o administrador los aprueba o descarta. [Alta por USB o LoRa](docs/DESARROLLO_LOCAL.md#incorporar-un-collar-por-usb-o-lora). |
| Datos de validación | `scripts/seed_validation_data.py` carga 40 bovinos ficticios con historial en un predio de validación, con respaldo previo. [Verificación](docs/VERIFICACION.md#carga-de-un-rebaño-de-validación). |
| Hardware | Código Arduino del collar, las dos receptoras y los dos repetidores. [Firmware](firmware/README.md). |
| Docker y LoRaWAN | Docker levanta la aplicación y admite perfiles MQTT/ChirpStack. La validación física de LoRaWAN está pendiente. |

El código de la aplicación y de la captura se mantiene en `main`. Para contribuir consulta [CONTRIBUTING.md](CONTRIBUTING.md). Las comprobaciones de GitHub cubren compilación del frontend, contratos de captura, reglas de dominio y API con PostGIS temporal. El ensayo físico por repetidores del 10 de noviembre verificó recepción y persistencia de lotes en el prototipo local.

## Funcionalidades

- Sesiones HttpOnly, CSRF, permisos por predio y roles de administrador, dueño, trabajador y veterinario. TOTP configurable para el inicio de sesión de administrador y verificación adicional para operaciones sensibles.
- Contexto multipredio, gestión de clientes, invitaciones, membresías, confianza por acción y aprobación de propuestas del trabajador. Las invitaciones vencidas se consultan mediante el filtro correspondiente.
- Bovinos con DIIO, ficha técnica y sanitaria, historial, tratamientos y agenda con autoría.
- **Registro sanitario** exige producto y vía para vacuna y antibiótico. Vacuna ofrece vías intramuscular, subcutánea e intranasal. La vía oral aparece en el selector de antibiótico. Procedimiento admite productos opcionales y Muerte muestra las circunstancias y la causa si se conoce. La API valida estas reglas al guardar y al aprobar propuestas.
- **Rebaño y salud → Reportes del rebaño** permite consultar registros del predio o de un bovino y descargar el filtro aplicado en CSV. Dueño y administrador pueden exportar los totales de bovinos, collares y módulos, agrupar alertas por día, semana o mes en la zona horaria del predio y consultar los rankings por porcentaje de muestras en movimiento o por aperturas de alertas de salida de geocerca. Los rankings muestran la cobertura que sustenta cada puesto. [Contrato de reportes](docs/CONTRATO_API.md#reportes-del-rebaño)
- Mapa Leaflet con imagen satelital y cartografía vial locales, OpenStreetMap opcional, escala métrica, recentrado y dibujo de geocercas versionadas.
- Asociaciones históricas entre collar y animal, sector y geocerca, con vigencias que preservan las lecturas anteriores. En **Territorio → Sectores y geocercas** se puede trasladar un animal con su collar a otro potrero.
- Recepción académica LoRa directo mediante una T3 USB con CSV V4 y JSON V5, y captura de lotes JSON mediante una T3 base. La cola local deduplica y reintenta la entrega a la API.
- Visualización de GPS, satélites usados, HDOP, temperatura superficial, aceleración, actividad, movimiento, batería, USB y calidad radio según los campos recibidos.
- Historial paginado, gráficas y trayectoria por collar, registro diario y exportación JSONL de la página consultada.
- **Alertas y atención → Configurar alertas** reúne batería, temperatura, actividad y cercanía al límite de geocerca. Dueño y administrador pueden simular reglas de sensores y guardar valores por predio con versión y auditoría.
- Condición técnica de las alertas separada de su atención humana; supervisión de ausencia de comunicación y vigencia GPS.
- Gateways, KPI, mantenimiento, auditoría, avisos externos en cola y simulación identificada y separada del hardware real.

## Entornos y captura de hardware

Usa la raíz del repositorio como directorio de trabajo. Para una instalación nueva, clona `main` con `git clone --branch main https://github.com/noagame/GeoCattle.git` y entra en `GeoCattle`.

| Entorno | Archivo privado | Web por defecto | Puerto PostgreSQL |
|---|---|---|---|
| Desarrollo nativo en Windows | `.env.academic` | `8084` | `55434` |
| Desarrollo en Linux con `Abrir-GeoCattle.sh` | `.env.docker` | `8084` | `55436` |
| Docker con datos de demostración | `.env` | `8080` | `55432` |
| Docker de desarrollo con configuración predeterminada | `.env.docker` | `8086` | `55436` |

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

Para capturar por USB en el entorno Linux ya iniciado en el puerto 8084, conecta la receptora y ejecuta desde la raíz:

```bash
python3 -m venv .venv-capture
.venv-capture/bin/python -m pip install -r adapters/requirements.txt
.venv-capture/bin/python scripts/start_capture.py --backend docker --select-mode
```

Conecta la T3 receptora al anfitrión por USB de datos, enciende el collar y cierra Monitor Serie y Plotter. El capturador detecta la receptora por identidad USB y utiliza `.runtime/docker-capture/`. En Linux el usuario necesita permisos sobre el dispositivo serial. En la primera vinculación, deja conectada una sola receptora y espera un paquete LoRa válido.

Para MQTT, añade `--profile iot` al arranque. `--profile lorawan` añade ChirpStack y activa también `iot`. La recepción directa por USB entrega por HTTP a la API.

Comprueba la [salud de la API de Docker](http://localhost:8086/api/v1/health) o el mismo endpoint en `8080` para simulación. Consulta `status` y `logs` con `scripts/docker_project.py`. Usa `backup` para generar un respaldo y `stop` para detener contenedores conservando los volúmenes. Repite `--environment development` y los perfiles que hayas activado al administrar ese entorno. El arranque en Linux x86_64 se comprobó en Docker Desktop sobre Windows. [Evidencia de portabilidad](docs/REVISION_DOCKER_PORTABILIDAD.md).

### Captura USB en desarrollo nativo

1. Inicia GeoCattle siguiendo el [arranque de desarrollo en el puerto 8084](#desarrollo-local-en-el-puerto-8084).
2. Conecta la receptora T3 con un cable USB de datos, enciende el collar y cierra Monitor Serie y Plotter.
3. Abre [`Iniciar-Captura.cmd`](Iniciar-Captura.cmd). Elige **Directo** para la T3 que recibe del collar o **Gateways** para la T3 base de los repetidores. Se detectará el USB del modo seleccionado.
4. Deja abierta la consola de captura. Comprueba una lectura nueva en [Recepción de collares](http://localhost:8084/#hardware) y confirma la persistencia en PostgreSQL antes de dar por verificada la integración.

Ctrl+C detiene la captura en primer plano. `Pausar-Captura-COM5.ps1` libera el puerto de una captura en segundo plano. `Detener-Prototipo.ps1` detiene los servicios locales. El archivo diario y la cola SQLite están en `.runtime/capture/`. La aplicación persiste las lecturas en PostgreSQL/PostGIS.

En **Recepción de collares**, revisa la última lectura y, por separado, la fecha de la última posición GPS válida. Con la T3 base, **0 saltos** representa recepción directa en la base. Para comprobar el paso por repetidores, verifica que los paquetes registren **1 o 2 saltos**.

El arranque aplica las migraciones pendientes en orden. Respalda la base antes de actualizar una instalación existente y valida primero la migración en una copia.

El engranaje junto a «Cerrar sesión» abre el perfil personal. La barra lateral agrupa las páginas relacionadas según los permisos de cada rol.

### Acceso de administrador

En desarrollo y simulación, el administrador entra con **correo y contraseña**. Usa las credenciales de administrador de tu instalación. En el prototipo existente, abre [GeoCattle local](http://localhost:8084/) tras ejecutar `Abrir-GeoCattle.cmd`.

En una instancia Docker nueva, levanta primero los servicios. Define `V3_ADMIN_PASSWORD` en el archivo privado con el que arrancaste y úsalo en `--env-file`. El ejemplo usa `.env.docker`, el mismo archivo del iniciador de Linux:

```text
docker compose --env-file .env.docker -f compose.yaml -f compose.usb.yaml --profile tools run --rm --no-deps seed python -m geocattle.seed_v3 --admin-email administrador@example.com
```

Usa una contraseña de al menos doce caracteres y el correo elegido. Para simulación usa `.env` y solo `-f compose.yaml`. Las credenciales y los factores existentes se administran localmente.

Para volver a pedir TOTP al iniciar sesión, define `ADMIN_LOGIN_MFA=true` en el archivo privado del entorno y reinicia la API. `APP_ENV=production` exige TOTP al administrador. La verificación adicional de operaciones sensibles sigue disponible.

Para cambiar de app autenticadora, abre **Mi perfil → Seguridad y acceso → Reemplazar autenticador**. El factor anterior sigue activo hasta confirmar un código del nuevo. Si perdiste el autenticador, restablécelo desde la consola del servidor con `py -3 scripts/account_maintenance.py mfa-reset --email CORREO`. El restablecimiento queda auditado y exige inscribir un TOTP nuevo en el siguiente ingreso. [Perfil y recuperación](docs/USUARIOS_Y_REGISTRO.md)

### Usuarios y alertas

El administrador crea cuentas de dueños. El dueño invita a trabajadores y veterinarios desde Equipo y permisos. Cada invitado activa su cuenta con un enlace de uso único y vencimiento. Con SMTP configurado, GeoCattle envía el enlace por correo y muestra el estado del envío. Sin SMTP, o si el envío falla, el dueño comparte el enlace manualmente. Comprueba la configuración con `scripts/account_maintenance.py smtp-test --to CORREO` antes de activar `INVITATION_EMAIL_ENABLED`. [Correo SMTP](docs/OPERACION.md)

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

Para editar con recarga en caliente, usa PostgreSQL/PostGIS y `uv sync --extra test` dentro de `backend/`. `scripts/local_backend.py` ofrece `migrate`, `seed` y `serve` desde la raíz. El servidor de Vite usa `http://localhost:5173` y redirige las solicitudes de API al puerto 8000. [Operación](docs/OPERACION.md) · [Verificación](docs/VERIFICACION.md)

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
- [Plan de evolución y criterios de aceptación](docs/planificacion/PLAN_EVOLUCION_TRAZABILIDAD.md).
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
