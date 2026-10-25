# Revisión de Docker y portabilidad de GeoCattle

**Fecha de corte: 25 de octubre de 2026, America/Santiago.**

El arranque Docker dispone ahora de una entrada Python común para Windows y Linux y separa simulación, desarrollo con datos físicos e instancia nativa existente. La ejecución aislada `geocattle-portability-qa-528959` terminó **correctamente** el 25 de octubre de 2026 a las 15:29 (America/Santiago): **113 pruebas backend, 94 pruebas de adaptadores/hardware y 126 comprobaciones HTTP aprobadas**, además de MQTT, worker independiente y persistencia tras reinicio. La ejecución utilizó contenedores Linux x86_64 sobre Docker Desktop en Windows; no equivale a probar otro PC físico ni el USB real con Docker.

## 1. Entornos y datos separados

| Entorno | Configuración privada | Proyecto o servicio | Web / PostgreSQL | Datos |
|---|---|---|---|---|
| Simulación Docker | `.env` | `geocattle-simulation` | `8080` / `55432` | Demo sintética de 70 bovinos; no representa una prueba de 70 radios |
| Desarrollo Docker | `.env.docker` | `geocattle-docker-academic` | `8086` / `55436` | Base nueva, sin seed de animales; captura en `.runtime/docker-capture/` |
| Prototipo nativo Windows ya preparado | `.env.academic` | PostgreSQL y servicios Windows existentes | `8084` / `55434` | Base física y archivo `.runtime/capture/` conservados |
| Ensayo de portabilidad | `.runtime/docker-portability/<proyecto>/qa.env` | Prefijo exclusivo `geocattle-portability-qa-` | `18084` / `55440` por defecto | Datos QA y volúmenes independientes |

Los puertos de la tabla son valores predeterminados: se debe conservar el archivo privado elegido para volver a operar sobre el mismo proyecto. El wrapper rechaza utilizar `.env.academic` como configuración Docker, no sobrescribe archivos existentes y valida que `APP_ENV` y `SIMULATION_ENABLED` correspondan al entorno solicitado. No importa ni migra automáticamente la base nativa a Docker.

El nombre Compose identifica los recursos de cada despliegue. Mantener nombres distintos evita mezclar volúmenes de instalaciones separadas; la precedencia de nombres y archivos está descrita por [Docker Compose](https://docs.docker.com/compose/how-tos/environment-variables/envvars/).

## 2. Cambios revisados

| Área | Ajuste |
|---|---|
| Arranque | `scripts/docker_project.py`: preparar, iniciar, detener, consultar estado/registros y respaldar mediante `subprocess`, sin exigir Bash en el anfitrión |
| Configuración | `scripts/configure.py`: generación exclusiva de archivos nuevos con secretos aleatorios; admite un destino explícito sin reemplazar credenciales existentes |
| Aislamiento | Desarrollo Docker utiliza `.env.docker`, otros puertos, nombre de proyecto y archivo USB; el nativo conserva sus rutas y servicios |
| Imágenes | `backend/Dockerfile` diferencia `runtime` de `test`; las herramientas y suites de prueba se incorporan al destino de pruebas |
| Compose | Variables compartidas de entorno; cuenta restringida de aplicación separada de migración; perfiles opcionales `iot` y `lorawan` |
| Scripts POSIX | `.gitattributes` fija LF para `*.sh`; se evita depender de CRLF o de un intérprete Bash en Windows para el flujo común |
| Mapas | CSP de Nginx admite el dominio utilizado por las teselas OpenStreetMap; la cuadrícula local sigue disponible sin cartografía externa |
| Hora local | Dependencia `tzdata` para disponer de `America/Santiago` en el capturador, también en Windows |
| USB | `scripts/start_capture.py`: contexto nativo/Docker explícito y reconocimiento por identidad USB; el número COM no se usa como identidad permanente |
| ChirpStack | Servicio `chirpstack-init` prepara las extensiones antes de iniciar las migraciones de ChirpStack; no elimina la base existente |
| QA | `qa/docker_portability.py` crea configuración, proyecto y datos de prueba separados; comprueba resultados y conserva volúmenes al detener |

## 3. Preparación del equipo

Se requieren Git, Python 3.11 o superior y acceso del usuario a un motor Docker con contenedores Linux y Docker Compose 2 o superior. El inicio ordinario de la aplicación construye Node/frontend y Python/backend dentro de imágenes: no exige Node, PostgreSQL ni Bash instalados en el anfitrión. El capturador USB sí utiliza Python en el equipo que tiene conectada la receptora.

En Windows se puede utilizar Docker Desktop con su backend de contenedores Linux. En Linux se puede utilizar Docker Engine y el plugin Compose, o Docker Desktop. Los métodos vigentes de instalación están en la [documentación oficial de Compose](https://docs.docker.com/compose/install/).

Comprobar primero, desde una terminal normal con acceso a Docker:

```text
docker version
docker compose version
docker info --format "{{.OSType}}"
```

El último comando debe indicar `linux`. Un error de acceso al socket o al pipe de Docker es un problema de acceso del proceso al motor; no demuestra que el código de la aplicación haya fallado dentro del contenedor. En esta revisión la ejecución real se realizó con el usuario normal porque el entorno restringido del asistente no podía abrir el pipe de Docker.

## 4. Iniciar simulación en Windows o Linux

Clonar el repositorio y ejecutar los comandos desde su raíz. En Windows, usar PowerShell:

```powershell
git clone https://github.com/noagame/GeoCattle.git
Set-Location GeoCattle
py -3 scripts/docker_project.py start
```

En Linux:

```bash
git clone https://github.com/noagame/GeoCattle.git
cd GeoCattle
python3 scripts/docker_project.py start
```

La aplicación se publica en `http://localhost:8080`. La cuenta inicial de demo es `demo@geocattle.local`; su contraseña se consulta localmente en `DEMO_PASSWORD` de `.env`. El inicio genera configuración si falta, espera los servicios, aplica las migraciones y prepara el seed sintético y su conciliación V3. Si la demo ya existe se conservan sus credenciales y datos.

El comando `prepare` genera únicamente configuración y `start` también realiza esa preparación cuando falta:

```text
python scripts/docker_project.py prepare
python scripts/docker_project.py status
python scripts/docker_project.py logs
python scripts/docker_project.py backup
python scripts/docker_project.py stop
```

En Linux, sustituir `python` por `python3` cuando ese sea el nombre de la instalación. `stop` ejecuta `down` sin eliminar volúmenes; `start` permite volver a utilizar los datos del mismo proyecto. Docker distingue la retirada de contenedores de la opción que elimina volúmenes, según su [referencia de `compose down`](https://docs.docker.com/reference/cli/docker/compose/down/).

## 5. Iniciar desarrollo Docker para datos físicos

Este entorno está separado de la simulación y del prototipo nativo existente. No lleva datos físicos anteriores ni crea animales ficticios.

Windows:

```powershell
py -3 scripts/docker_project.py start --environment development --owner-email owner@example.local --farm "Predio de prueba"
```

Linux:

```bash
python3 scripts/docker_project.py start --environment development --owner-email owner@example.local --farm "Predio de prueba"
```

El ejemplo de correo y predio debe reemplazarse por los datos del propietario de esa instalación. El acceso queda en `http://localhost:8086`; la contraseña inicial se consulta localmente en `ADMIN_PASSWORD` de `.env.docker`. Si el propietario ya existe, no se cambia su contraseña, estado ni predio. Sin las dos opciones de propietario/predio, el inicio no crea cuentas. El administrador global V3 se provisiona por separado, conforme al README y al flujo MFA de la aplicación.

Registrar en esa instalación los dispositivos y las asociaciones a bovinos que correspondan antes de atribuir sus lecturas. El capturador no crea animales ni importa asignaciones del prototipo nativo.

Las demás operaciones deben seleccionar el mismo entorno:

```text
python scripts/docker_project.py status --environment development
python scripts/docker_project.py logs --environment development
python scripts/docker_project.py backup --environment development
python scripts/docker_project.py stop --environment development
```

Para una configuración alternativa, añadir el mismo `--env-file ruta/al/archivo` a cada acción. Los perfiles opcionales se habilitan con `--profile iot` o `--profile lorawan`; este último incorpora también el broker requerido. Instalar ChirpStack no configura por sí solo el hardware de campo, OTAA ni un gateway físico.

Los puertos expuestos se enlazan a `127.0.0.1`: esta preparación es local. El acceso desde otros equipos requiere una configuración de red y HTTPS explícita; no queda habilitado por el clon.

## 6. Captura USB en el anfitrión

La receptora T3 se conecta al equipo anfitrión. La aplicación de Docker recibe sus datos por HTTP; no se presupone que un puerto COM de Windows exista dentro del contenedor Linux. `compose.usb.yaml` monta únicamente el directorio de estado del capturador en modo de lectura para que la API pueda informar su disponibilidad.

Para una instalación nueva se puede utilizar un entorno Python separado. En Windows:

```powershell
py -3 -m venv .venv-capture
.\.venv-capture\Scripts\python.exe -m pip install -r adapters/requirements.txt
.\.venv-capture\Scripts\python.exe scripts/start_capture.py --backend docker
```

En Linux:

```bash
python3 -m venv .venv-capture
.venv-capture/bin/python -m pip install -r adapters/requirements.txt
.venv-capture/bin/python scripts/start_capture.py --backend docker
```

Si se utilizó un archivo Docker alternativo, añadir `--env-file ruta/al/archivo` también al capturador. Mantener cerrados Monitor Serie y Plotter. En el primer enlace, dejar solo la receptora conectada por USB de datos y el emisor alimentado; la confirmación exige un paquete LoRa con información radio. El archivo `receiver.json` guarda VID/PID y número de serie o ubicación USB; el puerto puede cambiar posteriormente. Si la selección es ambigua, se requiere un puerto explícito, no una identificación por descripción genérica.

En Linux, el usuario necesita permisos sobre el dispositivo serie; la configuración depende de la distribución y sus reglas de dispositivos. Puede indicarse una ruta estable, por ejemplo `--port /dev/serial/by-id/usb-IDENTIDAD_REAL`, cuando exista. No se debe suponer `/dev/ttyUSB0` fijo. En Windows puede seleccionarse temporalmente `--port COMx` con el puerto realmente enumerado, sin codificarlo en el sistema.

El modo explícito `--backend docker` evita elegir la instancia nativa cuando ambas configuraciones existen. `Iniciar-Captura.cmd` conserva su utilidad en el PC nativo ya preparado, pero no debe presentarse como instalación automática de Docker ni como selector de un puerto COM fijo.

Docker documenta USB/IP como un procedimiento adicional con requisitos y soporte dependientes del backend, y no garantiza todos los dispositivos. Esta revisión no instala USB/IP ni realiza un paso directo de la T3 al contenedor; conserva el capturador en el anfitrión. Véase [USB/IP en Docker Desktop](https://docs.docker.com/desktop/features/usbip/).

## 7. Respaldo y conservación

`docker_project.py backup` genera un `pg_dump` en formato custom dentro de `backups/`. Usa un nombre con proyecto, base y fecha UTC, escribe primero un archivo parcial y solo lo publica si el proceso termina con contenido. El flujo es binario también en Windows: no utiliza una redirección de texto de PowerShell. No imprime la contraseña ni la incorpora como argumento de la línea de comandos.

Detener el proyecto conserva sus volúmenes. Los datos persistentes deben permanecer fuera de la capa efímera del contenedor, según el [ciclo de vida de volúmenes de Docker](https://docs.docker.com/engine/storage/volumes/). No ejecutar una eliminación de volúmenes para reiniciar o actualizar el software.

El respaldo de PostgreSQL no incluye por sí solo los secretos de configuración, claves necesarias para MFA, archivos JSONL, cola SQLite ni identidad del capturador. Estos elementos deben preservarse por separado como información privada. `.env*`, `.runtime/`, `backups/`, dependencias y bases locales permanecen fuera de Git.

El helper Python crea respaldos pero no incorpora una acción de restauración. La restauración debe ensayarse con `pg_restore` sobre una base nueva y aislada, comprobando migraciones, integridad, conteos y acceso antes de considerar válido el respaldo. Los scripts Bash históricos trabajan con el entorno Compose predeterminado; no deben asumirse adecuados para `.env.docker` o para la base física sin seleccionar y revisar expresamente el destino. No copiar un directorio PostgreSQL activo como sustituto de un respaldo lógico.

## 8. Pruebas ejecutadas y pendientes

| Comprobación | Resultado final |
|---|---|
| Helpers y contratos en Windows | **90 unittest aprobadas**, sin abrir placas ni la base operativa |
| Motor Docker | Linux x86_64, Docker Desktop, servidor 29.9.2 |
| Configuración y construcción | Compose, frontend en Node e imagen Python runtime/test correctos |
| PostgreSQL/PostGIS | Migraciones y carga QA inicial correctas; base de tests independiente |
| Web y contrato | Nginx, HTML, CSS/JS, CSP de OpenStreetMap y endpoints verificados |
| ChirpStack y Redis | UI, Redis PONG, extensiones y tablas migradas verificados |
| MQTT | QoS 1 → broker → ingestor → PostgreSQL → recibo committed → consulta API correcto |
| Worker programado | Genera ausencia sin invocar manualmente el evaluador; una lectura nueva la resuelve y conserva su historia |
| Smoke funcional HTTP | **126 comprobaciones aprobadas, 0 fallidas** |
| Backend en Linux | **113 pytest aprobadas, ninguna omitida**; permisos, MFA, roles, asociaciones, geocercas y reglas |
| Adaptadores/hardware en Linux | **94 unittest aprobadas, ninguna omitida**; incluye 4 pruebas de API hardware con fixtures autónomos y rollback |
| Reinicio y persistencia | **589 lecturas QA antes y 589 después** de detener y volver a iniciar |
| USB físico hacia Docker | No probado; el capturador está preparado para ejecutarse en el anfitrión |
| Otro PC físico / ARM | No probado |

La ejecución completa `geocattle-portability-qa-528959` finalizó con estado `passed`. Detuvo solo sus contenedores y conservó los volúmenes; no abrió el USB ni consultó la base nativa. La evidencia publicable, sin credenciales, está en [docker_portabilidad_2026-10-25.json](evidencias/docker_portabilidad_2026-10-25.json). Los registros detallados locales permanecen en `.runtime/docker-portability/<proyecto>/`; `qa.env` contiene secretos y no se publica.

El primer intento `geocattle-portability-qa-54a797` tuvo 119 comprobaciones HTTP correctas y 2 fallidas: pretendía atribuir silencio anterior a una asignación recién creada. Se corrigió el fixture para probar una asociación antigua del seed y se añadieron cuatro regresiones sobre la ventana de supervisión; la protección del dominio no cambió. La revisión de sus logs detectó además extensiones faltantes de ChirpStack. El servicio idempotente `chirpstack-init` y una comprobación de tablas resolvieron ese arranque incompleto. Se conservan ambos resultados para trazabilidad.

La evidencia Windows de 90 pruebas está en `.runtime/review/docker-portability-host-tests-2026-10-25-retry.txt`. Algunos casos generan errores intencionales de paquetes/reconexión; el éxito global se determina por el resumen de la suite. Pytest Linux informó una advertencia de deprecación del cliente de pruebas FastAPI/Starlette; no hubo fallos ni pruebas omitidas.

Para repetir con el usuario normal y Docker disponible:

```powershell
# Windows, desde la raíz del proyecto:
py -3 qa/docker_portability.py
```

```bash
# Linux, desde la raíz del proyecto:
python3 qa/docker_portability.py
```

En este PC también puede abrirse `Probar-Docker.cmd`, que usa el `.venv` ya instalado. El ejecutor QA utiliza la biblioteca estándar en el anfitrión e instala las dependencias de tests en su imagen Linux. Cada ejecución crea proyecto, secretos y datos sintéticos separados; no elimina volúmenes ni necesita placas conectadas.

## 9. Alcance de la portabilidad

Ejecutar imágenes Linux con Docker Desktop en un PC Windows demuestra comportamiento del entorno Linux de los contenedores en ese equipo. No equivale a haber probado un segundo PC, una instalación nativa de Linux ni una arquitectura ARM. Tampoco valida acceso USB, drivers, cobertura LoRa, GNSS, batería, capacidad de 70 collares físicos ni operación prolongada.

La revisión conserva la instancia nativa de `8084`, su `.env.academic`, PostgreSQL y capturas. El despliegue Docker de desarrollo genera datos independientes; no supone una migración ni una puesta en producción. La suite completa quedó aprobada en este equipo. En el PC de destino siguen pendientes su ejecución, los permisos del puerto serie y una prueba con la receptora física.

La prueba también puede iniciarse con doble clic en `Probar-Docker.cmd` en este PC, que dispone de `.venv`. La validación añadida de extensiones sigue los [requisitos de ChirpStack](https://www.chirpstack.io/docs/chirpstack/requirements.html) y su [inicialización Docker oficial](https://github.com/chirpstack/chirpstack-docker/blob/master/configuration/postgresql/initdb/001-chirpstack_extensions.sh). La segunda ejecución comprobó ambas extensiones y las tablas de ChirpStack, además de su página web.

Esta revisión incluye los helpers de captura y Docker, la documentación y evidencia QA. Las configuraciones privadas y los datos de cada instalación se preparan y conservan por separado; no forman parte de la publicación.
