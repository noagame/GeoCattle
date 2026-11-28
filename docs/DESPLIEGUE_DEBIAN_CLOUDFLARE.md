# Despliegue en Debian 12 o 13 con Cloudflare Tunnel

Cloudflare publica `https://geocattle.example.com`. El conector abre conexiones salientes hacia Cloudflare y entrega la web y `/api` a `http://web:80` en Docker. La configuración de producción elimina las publicaciones de puertos de nginx y PostgreSQL. La API, el worker y la base permanecen en redes de Compose. MQTT, ChirpStack y USB quedan fuera del túnel.

## Instalar Docker Engine y Compose

En Debian 12 (Bookworm) o 13 (Trixie), instala Docker desde su repositorio APT oficial. El bloque toma la versión de `/etc/os-release`. Si el servidor ya tiene Docker de Debian, Podman u otro runtime, inventaría primero sus contenedores y volúmenes y resuelve los conflictos de paquetes según la guía oficial.

```bash
sudo apt update
sudo apt install ca-certificates curl git openssl python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
docker compose version
```

Usa el plugin Compose oficial actualizado. El archivo de producción usa la etiqueta YAML `!reset` para retirar los puertos heredados. Para ejecutar los comandos sin sudo, un administrador puede añadir a la cuenta operadora al grupo `docker` con `sudo usermod -aG docker "$USER"` y abrir una sesión nueva. El grupo equivale a acceso de administrador al servidor. [Instalación oficial de Docker en Debian](https://docs.docker.com/engine/install/debian/) · [Permisos de Docker](https://docs.docker.com/engine/install/linux-postinstall/)

Mantén cerrados los puertos de entrada de la aplicación en el firewall del servidor y del proveedor. Conserva el canal administrativo que ya uses. Permite DNS, HTTPS saliente para descargas y TCP/UDP 7844 hacia Cloudflare. Si activas correo, permite el puerto saliente del proveedor SMTP. [Firewall de Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/)

## Código y archivo privado

Con Git, clona el remoto autorizado en `/srv/GeoCattle`. Sin acceso al remoto, genera un paquete en el equipo de desarrollo con `py -3 scripts/empaquetar_despliegue.py`, que lo deja en la carpeta hermana `GeoCattle-Despliegue/paquete/`. Contiene los archivos versionados y los nuevos que Git no ignora, con finales LF, y excluye `.env*`, `.runtime/`, respaldos, colas y el `config.h` de la T3. Copia el `.tar.gz` y su `.sha256` al servidor.

```bash
sha256sum -c geocattle-AAAAmmddTHHMMSSZ.tar.gz.sha256
sudo mkdir -p /srv/GeoCattle && sudo chown "$USER": /srv/GeoCattle
tar -xzf geocattle-AAAAmmddTHHMMSSZ.tar.gz -C /srv/GeoCattle
cd /srv/GeoCattle
python3 scripts/docker_project.py prepare --environment production --env-file .env.pilot --domain geocattle.example.com
chmod 600 .env.pilot
```

El generador crea contraseñas aleatorias para PostgreSQL, la aplicación, la cuenta inicial, el administrador V3 y la ingesta. Con `--domain` escribe `ALLOWED_HOSTS`, `ALLOWED_ORIGINS` e `INVITATION_BASE_URL` para ese dominio y deja `TUNNEL_TOKEN` pendiente. La opción solo actúa al crear el archivo. Mantén `APP_ENV=production`, `SIMULATION_ENABLED=false`, `COOKIE_SECURE=true` y `DEMO_PASSWORD` vacío. Conserva el nombre del proyecto y el de la base durante actualizaciones. Respalda el archivo privado junto con la base, con acceso restringido. Si usas `MFA_ENCRYPTION_KEY`, genérala una vez con `openssl rand -hex 32` y consérvala. En su ausencia, la clave se deriva de `SESSION_SECRET`.

Reemplaza en `.env.pilot` el token ficticio por el del conector. Sin `--domain`, agrega también las entradas del dominio.

```dotenv
ALLOWED_HOSTS=geocattle.example.com,localhost,127.0.0.1
ALLOWED_ORIGINS=https://geocattle.example.com
INVITATION_BASE_URL=https://geocattle.example.com
TUNNEL_TOKEN=TOKEN_FICTICIO_DE_CLOUDFLARE
```

La API y el worker reciben la misma URL pública. Para enviar invitaciones, configura `INVITATION_EMAIL_ENABLED=true`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS_MODE`, `SMTP_USERNAME`, `SMTP_PASSWORD` y `SMTP_FROM` con los datos del proveedor. Usa TLS implícito (`ssl`, normalmente 465) o `starttls` (normalmente 587). [Operación SMTP](OPERACION.md#correo-smtp-de-invitaciones)

## Crear la ruta pública

1. En Cloudflare Zero Trust, abre **Networks → Connectors → Cloudflare Tunnels** y crea un túnel con el tipo **Cloudflared**. Copia el token del conector a `.env.pilot`. El contenedor lo lee de `TUNNEL_TOKEN`.
2. En **Published application routes** (o **Public Hostnames**), agrega el dominio elegido y selecciona **HTTP** con servicio `http://web:80`. Conserva el Host público en la solicitud al origen. Comprueba el registro DNS proxificado que crea Cloudflare.
3. Activa la redirección a HTTPS para ese dominio en Cloudflare. Mantén `CF-Connecting-IP` habilitado y evita **Pseudo IPv4 / Overwrite Headers** si necesitas conservar las IPv6 originales. Si la zona usa reglas de caché personalizadas, excluye `/api/*`.

Configura Access para la T3 en la ruta de ingesta indicada más abajo. La web y las invitaciones usan las sesiones de GeoCattle.

## Primer arranque

Para una instalación nueva, comprueba que `.env.pilot` tenga un `V3_ADMIN_PASSWORD` de al menos 12 caracteres (`--domain` lo genera) y elige correos distintos para el propietario y el administrador. Si vas a trasladar una base existente, sigue primero el procedimiento de traslado.

```bash
python3 scripts/docker_project.py start --environment production --env-file .env.pilot \
  --profile cloudflare --owner-email propietario@example.com --farm 'Predio' \
  --admin-email admin@example.com
```

PostgreSQL/PostGIS conserva los datos en el volumen `database-data`. Compose espera a PostgreSQL, aplica las migraciones pendientes, inicia la API y el worker y comprueba nginx antes de conectar el túnel. Las herramientas de Compose crean el propietario con `ADMIN_PASSWORD` y el administrador V3 con `V3_ADMIN_PASSWORD`. Las cuentas existentes conservan sus credenciales. El administrador debe enrolar TOTP. El arranque de actualizaciones omite los argumentos de alta. [Administrador V3](../README.md#acceso-de-administrador)

```bash
export COMPOSE_FILE=compose.yaml:compose.cloudflare.yaml
export COMPOSE_ENV_FILES=.env.pilot COMPOSE_PROFILES=cloudflare
```

Esas variables seleccionan el mismo proyecto para los comandos Compose y los scripts de respaldo de esta guía. Ejecútalos desde la raíz del repositorio.

## Verificación y diagnóstico

```bash
bash scripts/compose.sh config --quiet
bash scripts/compose.sh ps -a
bash scripts/compose.sh exec -T web wget -qO- http://127.0.0.1/api/v1/health
curl -fsS https://geocattle.example.com/api/v1/health
bash scripts/compose.sh logs --tail=100 migrate api worker web cloudflared
```

Verifica que `migrate` haya terminado con código cero, que `web` y `cloudflared` figuren sanos y que los servicios activos carezcan de puertos publicados. La verificación pública debe indicar `status: ok` y `environment: production`. Abre la web, inicia sesión y comprueba la cookie `Secure`, una operación autorizada sobre el predio, MFA del administrador y un enlace de invitación si habilitaste SMTP. Evita compartir la salida completa de `docker compose config`, que contiene credenciales.

| Síntoma | Comprobar |
| --- | --- |
| Error 1033 o conector no disponible | Token del túnel activo, salida TCP/UDP 7844, resolución DNS y logs de `cloudflared`. |
| HTTP 502 desde Cloudflare | Servicio `http://web:80`, estado de nginx y API, y resultado de migración. |
| HTTP 400 o fallo al iniciar sesión | Host público conservado, `ALLOWED_HOSTS`, origen HTTPS exacto y redirección a HTTPS en Cloudflare. |
| Docker indica una red solapada | El despliegue reserva `172.30.248.0/28` y `172.30.248.16/28`. Comprueba redes Docker y rutas del servidor. Cambia las subredes y las direcciones de confianza juntas en Compose y nginx si el entorno exige otras. |
| SMTP pendiente o rechazado | Credenciales, modo TLS, remitente, salida de red y logs del worker. |

## Receptoras T3, almacenamiento y entrega

El collar transmite por LoRa a los XIAO bus_v1 (nodos 1 y 2), que retransmiten a la T3 base (nodo 0). La base mantiene bus_v1 y los ACK, y entrega por USB al PC, que registra en GeoCattle local. Una segunda T3 con [`GeoCattle_Nube_T3`](../firmware/README.md#t3-nube-por-wifi) escucha los mismos lotes de los gateways y los collares que oye directo, sin transmitir mientras oye la base. Los guarda en su flash y los entrega por HTTPS a Cloudflare, a la API y a PostgreSQL de producción. Las dos receptoras son independientes: una caída de WiFi no afecta al registro local. Si la base está apagada, la T3 nube hace de raíz de respaldo: emite las balizas y confirma los lotes, así los gateways siguen entregando por WiFi. Como alternativa de una sola placa, la T3 base también admite la salida WiFi aprovisionada por USB. En el [modo espejo](#modo-espejo-el-pc-del-campo-como-sistema-principal) la T3 nube no se usa: la web recibe todo desde la base del PC.

MQTT y ChirpStack quedan fuera de este flujo. La ruta HTTP tampoco transporta el UDP de un packet forwarder LoRaWAN. Basics Station por WebSocket queda como trabajo futuro.

1. Usa la `INGEST_KEY` de `.env.pilot` y el UUID del predio de producción. La T3 nube los recibe en `config.h` junto con el origen HTTPS y hasta tres redes WiFi. Valida el servidor con el paquete de CA raíz de Mozilla del core ESP32. Conserva las credenciales del servidor local por separado.
2. Se recomienda un service token exclusivo de la T3. Crea una aplicación Cloudflare Access self-hosted con política **Service Auth** para `/api/v1/ingest/receiver-batch` y agrega el ID y el secreto en `config.h`. La misma ruta recibe el heartbeat. Candidatos y consultas de Hardware usan su sesión web.
3. Si los eventos de seguridad identifican un bloqueo por desafío de bots, limita el Skip al hostname, método POST, ruta exacta y componente identificado. Incluye la IP de salida de la T3 si es fija. Mantén Access y la autenticación de la API. Bot Fight Mode básico carece de excepciones WAF por ruta. Si usas reglas de caché particulares, excluye `/api/*`. [Opciones de Skip](https://developers.cloudflare.com/waf/custom-rules/skip/options/)

Nginx acepta cuerpos de hasta 2 MiB. La API admite hasta ocho líneas por POST y la T3 puede enviar un POST por segundo al drenar el búfer. Dimensiona cualquier límite de tasa según las T3 que compartan IP. En reposo la placa informa estado cada 15 s y aumenta la espera ante fallos. Hardware muestra la red, RSSI, ocupación, pendientes y firmware. El estado remoto vence a los 90 s.

Carga el [firmware de la T3 nube](../firmware/README.md#t3-nube-por-wifi). El PC continúa con [captura local Gateways](USB_COM5.md). Si falla WiFi o Cloudflare, la T3 nube conserva hasta 4096 lecturas en su flash (unas 51 h de un collar cada 45 s) y reemplaza las más antiguas cuando se llena. El registro completo de una desconexión más extensa queda en el equipo local si el USB y el capturador permanecieron activos.

Los collares nuevos llegan a **Collares detectados** por LoRa. Apruébalos desde el predio en la web. Para configurar un XIAO, conéctalo al equipo local y usa **Gateways detectados → Detectar gateway por USB** en Chrome o Edge sobre HTTPS. La sesión de dueño o administrador autoriza reservar, grabar y confirmar el nodo 1 o 2. [Lotes HTTPS de la T3](CONTRATO_API.md#lotes-https-de-la-receptora-t3)

## Modo espejo: el PC del campo como sistema principal

En este modo el PC del predio recibe las lecturas por USB desde la T3 base, calcula las alertas y opera sin internet. El servidor es un espejo casi en vivo: recibe la base del PC por replicación lógica de PostgreSQL mediante un túnel SSH que abre el propio PC. El modo recomendado usa solo la cuenta SSH del servidor; la alternativa entra por un hostname SSH de Cloudflare Access. El administrador de plataforma y el veterinario pueden encolar los cambios permitidos. Cualquier cuenta autenticada puede encolar su solicitud personal de soporte con `MIRROR_REMOTE_CHANGES=true` en ambos lados. El PC aplica los envíos al conectarse y deja las solicitudes veterinarias pendientes del dueño. La T3 nube no se usa en este modo. [Plan](planificacion/PLAN_MODO_ESPEJO.md) · [Contrato](CONTRATO_API.md#modo-espejo)

```text
Solo SSH (recomendado):
PC ──ssh usuario@servidor (-L 18022 → 172.30.248.19:22)──► espejo-ssh ◄── PostgreSQL del servidor (suscripción)
   └─ por ese tramo: -R 15432 → base del PC   ·   -L 127.0.0.1:18095 → web:80 (bandeja del worker)
Con Cloudflare Access:
PC ──ssh -R por cloudflared──► espejo-ssh   ·   worker ──HTTPS──► https://geocattle.example.com/api/v1/mirror/inbox
```

Cada lado valida al otro: el PC fija las huellas SSH de la cuenta del servidor y de `espejo-ssh` en `.runtime\espejo\known_hosts` y rechaza un cambio; el servidor solo acepta la llave del PC, limitada a esos reenvíos; la bandeja exige `MIRROR_SYNC_KEY` y la suscripción `MIRROR_REPLICA_PASSWORD`.

### Solo SSH

La cuenta SSH del servidor debe pertenecer al grupo `docker` y permitir el reenvío TCP (`AllowTcpForwarding yes`, valor por defecto en Debian). Cloudflare publica la web (`geocattle.example.com`). Tras completar la Parte A de la guía, el dueño ejecuta el comando siguiente en Windows desde la raíz de GeoCattle. Agrega `:PUERTO` si SSH usa un puerto distinto de 22.

```bat
.venv\Scripts\python.exe scripts\mirror.py pc-connect --ssh-jump usuario@servidor.example.com
```

El comando entra con la llave SSH personal y autoriza una llave distinta para el túnel. La segunda llave queda limitada al salto a `172.30.248.19:22` en la cuenta del servidor. También configura `MIRROR_SERVER_URL=http://127.0.0.1:18095`, instala la tarea de Windows y comprueba la réplica. Para crear el administrador con TOTP o verificar el resultado sigue la Parte B. [Despliegue del servidor espejo](DESPLIEGUE_SERVIDOR_ESPEJO.md)

### Cloudflare Access (alternativa)

En el túnel existente agrega dos rutas además de la web:

| Hostname | Tipo y servicio | Protección |
| --- | --- | --- |
| `espejo-ssh.example.com` | **SSH**, `espejo-ssh:22` | Aplicación Access con política **Service Auth** y un service token exclusivo del PC. |
| `soporte.example.com` | **HTTP**, `http://espejo-ssh:18084` | Aplicación Access con política **Allow** solo para los correos de los administradores. |

El service token del PC se entrega al túnel como `TUNNEL_SERVICE_TOKEN_ID` y `TUNNEL_SERVICE_TOKEN_SECRET`, que `mirror.py` toma de `MIRROR_SSH_ACCESS_ID` y `MIRROR_SSH_ACCESS_SECRET` del archivo privado del PC. Comprueba que un intento sin token sea rechazado.

### Servidor

El administrador del servidor completa estos pasos con la misma cuenta Linux que entregará al dueño del PC. La web queda lista para recibir la suscripción. `pc-connect` transfiere la clave MFA en la sesión SSH y aplica el cambio a los servicios. Para Cloudflare Access, sigue el procedimiento manual e introduce la clave MFA con `server-init` antes de suscribir. [Despliegue del servidor espejo](DESPLIEGUE_SERVIDOR_ESPEJO.md)

```bash
cd /srv/GeoCattle
python3 scripts/docker_project.py prepare --environment production --env-file .env.pilot --domain geocattle.example.com
python3 scripts/mirror.py server-init --skip-secrets   # MIRROR_SYNC_KEY y entorno de origen
# Pega TUNNEL_TOKEN en .env.pilot.
python3 scripts/docker_project.py start --environment production --env-file .env.pilot --profile cloudflare --profile mirror
export COMPOSE_FILE=compose.yaml:compose.cloudflare.yaml:compose.mirror.yaml
export COMPOSE_ENV_FILES=.env.pilot COMPOSE_PROFILES=cloudflare,mirror
```

Las cuentas de GeoCattle, los predios y los factores TOTP llegan del PC. Crea el administrador de plataforma en el PC con `mirror.py pc-admin --email CORREO` y activa TOTP en **Mi perfil → Activar doble verificación**. La web espejo exige TOTP para el administrador y los factores se gestionan en el PC.

### Conexión manual con Cloudflare Access

Con GeoCattle cerrado, desde la raíz y con el Python de `.venv`:

```bat
.venv\Scripts\python.exe scripts\compartir_base.py exportar --verificar
.venv\Scripts\python.exe scripts\mirror.py pc-setup --server-url https://geocattle.example.com --ssh-host espejo-ssh.example.com
.venv\Scripts\python.exe scripts\mirror.py keygen
```

`pc-setup` reinicia PostgreSQL nativo con `wal_level=logical` y retiene hasta 2 GB de cambios mientras no haya conexión. También crea el rol `geocattle_replica` y la publicación `geocattle_espejo`, y agrega a `.env.academic` `MIRROR_MODE=field`, `MIRROR_REPLICA_PASSWORD` y `MFA_ENCRYPTION_KEY` (igual a la clave efectiva actual). Pide sin eco `MIRROR_SYNC_KEY` del servidor y el service token SSH. Instala [cloudflared para Windows](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/) en el PATH o indica su ruta en `MIRROR_CLOUDFLARED`. Para el soporte remoto agrega `https://soporte.example.com` a `ALLOWED_ORIGINS` del PC.

Copia la línea pública que imprime `keygen` al servidor y autorízala:

```bash
python3 scripts/mirror.py server-init  # introduce la MFA_ENCRYPTION_KEY del PC sin eco
python3 scripts/mirror.py authorize id_ed25519.pub
```

Repite el `start` de la sección Servidor si agregaste la clave MFA. La llave queda limitada a los reenvíos del túnel. En el PC, abre GeoCattle con `Abrir-GeoCattle.cmd` y deja el túnel como tarea de Windows.

```bat
.venv\Scripts\python.exe scripts\mirror.py install-task
schtasks /Run /TN "GeoCattle Espejo"
```

### Suscribir manualmente y verificar

```bash
python3 scripts/mirror.py subscribe --pc-database NOMBRE_DE_POSTGRES_DB_DEL_PC
python3 scripts/mirror.py status
```

`subscribe` comprueba que el PC responda por el túnel y que ambos lados tengan las mismas migraciones. Después respalda la base del servidor, vacía sus tablas espejo y copia la base completa del PC. Pide sin eco `MIRROR_REPLICA_PASSWORD`. Desde ese momento los cambios llegan en segundos. En el PC, `mirror.py pc-status` muestra el slot y el WAL retenido. Verifica en la web el aviso "datos del campo hace N s", una solicitud de veterinario que quede pendiente del dueño en el PC y una orden de administrador aplicada.

Comprueba «Conectado al servidor web» en el pie de la réplica y alterna entre OpenStreetMap y Satélite en línea. Envía una solicitud personal de soporte y comprueba que pase a «Aplicado» en «Mis envíos» y aparezca en «Mis solicitudes a soporte» con el mismo folio que en el PC.

| Síntoma | Comprobar |
| --- | --- |
| `status` sin mensajes recientes | Tarea "GeoCattle Espejo" y `.runtime\espejo\tunel.log` en el PC, ruta SSH y token en Cloudflare, `docker compose logs espejo-ssh`. |
| Errores de aplicación crecientes | Migraciones distintas entre PC y servidor. Actualiza el servidor y el PC y ejecuta `mirror.py refresh`. |
| `pc-status` con WAL `lost` o slot ausente | El corte superó los 2 GB retenidos. En el servidor ejecuta `mirror.py resync --pc-database ...`; si el PC no respondía, antes `mirror.py pc-drop-slot` en el PC. |
| TOTP rechazado solo en la web | `MFA_ENCRYPTION_KEY` del servidor distinta de la del PC. |

### Actualizar

La réplica no copia cambios de esquema. Respalda ambos lados y actualiza en este orden: primero el servidor (paquete nuevo y `start` con los mismos perfiles), después el PC (código nuevo y `Abrir-GeoCattle.cmd`, que migra). Termina con `python3 scripts/mirror.py pc-setup` en el PC, para publicar tablas nuevas, y `python3 scripts/mirror.py refresh` en el servidor. Mientras los esquemas difieran, la suscripción reintenta sin aplicar cambios y no daña datos.

## Mapas

En `replica`, el navegador solicita las teselas en línea directamente a OpenStreetMap (base inicial) o Esri World Imagery (Satélite en línea). La cuadrícula WGS84 queda visible donde no cargan las teselas. La web espejo prescinde de los paquetes y manifiestos locales. [Esri World Imagery](https://goto.arcgisonline.com/maps/World_Imagery)

El PC del campo usa los paquetes locales instalados en `.runtime/mapa-satelital/` y `.runtime/mapa-osm/`. En un despliegue Docker sin espejo, nginx los puede servir desde montajes de solo lectura. [Mapa satelital](MAPA_SATELITAL.md) · [OpenStreetMap local](MAPA_OSM_LOCAL.md)

## Respaldo, recuperación y actualización

Con las variables Compose de esta guía exportadas, crea y verifica un respaldo antes de actualizar una instalación existente.

```bash
bash scripts/backup.sh
bash scripts/verify-backup.sh backups/geocattle-AAAAmmddTHHMMSSZ.dump
```

Cada respaldo verifica su catálogo con `pg_restore --list` antes de publicar el archivo. El segundo comando restaura en una base nueva de ensayo e imprime su nombre y los conteos. Revisa el resultado y guarda una copia del dump y de la configuración privada fuera del servidor. Para recuperar el servicio en ese mismo PostgreSQL, prueba primero la restauración. Durante una ventana de mantenimiento detén `cloudflared web worker api` con `bash scripts/compose.sh stop cloudflared web worker api`, cambia `POSTGRES_DB` en `.env.pilot` al nombre de la base restaurada y vuelve a ejecutar el arranque de producción sin los argumentos de propietario. Esto conserva la base anterior. Verifica los datos y el acceso antes de reabrir el servicio a los usuarios. [Respaldo y recuperación](OPERACION.md#respaldo-y-recuperación)

Para respaldos diarios a las 03:30 UTC, copia [la unidad de respaldo](../infrastructure/geocattle-backup.service) y [su temporizador](../infrastructure/geocattle-backup.timer) a `/etc/systemd/system/`. Ajusta la cuenta y el directorio a los del servidor y usa el mismo archivo privado de producción. Ejecuta `sudo systemctl daemon-reload`, `sudo systemctl enable --now geocattle-backup.timer` y `sudo systemctl start geocattle-backup.service` para comprobar la primera copia. Verifica con `systemctl list-timers geocattle-backup.timer` y `journalctl -u geocattle-backup.service`. El servicio guarda los dumps en `.runtime/backups-timer/` y rota los de 30 días o más después de un respaldo exitoso. Prueba la restauración de un dump del timer con `scripts/verify-backup.sh`.

Tras respaldar y revisar las migraciones nuevas, actualiza el código con `git pull --ff-only` o extrae un paquete nuevo sobre el mismo directorio (conserva `.env.pilot` y `.runtime/`), y ejecuta nuevamente `start` con el mismo entorno, archivo y perfil. Revisa el estado y prueba la URL pública. Para detener el despliegue conservando el volumen, usa el siguiente comando.

```bash
python3 scripts/docker_project.py stop --environment production --env-file .env.pilot --profile cloudflare
```

## Trasladar datos físicos del prototipo

1. Haz un respaldo previo de origen y destino existente. Comprueba la versión mayor de PostgreSQL y la versión de extensión con `SHOW server_version;` y `SELECT postgis_lib_version();`. El destino base usa PostgreSQL 16 / PostGIS 3.4. Ensaya la restauración con versiones compatibles y actualiza el software del destino si el origen es más reciente. Antes del corte final pausa la captura y las escrituras en origen. Conserva la cola local en su directorio y confirma allí las lecturas pendientes antes de cambiar de destino.
2. En Windows nativo, usa `.venv\Scripts\python.exe scripts/compartir_base.py exportar --verificar`. Para Docker local de desarrollo, usa un Python con `psycopg` instalado, por ejemplo el entorno del backend, y ejecuta `python scripts/compartir_base.py exportar --origen docker --env-file .env.docker --verificar`. Usa un instante sin datos de simulación. Transfiere `geocattle.dump` y `geocattle.sha256` juntos por un canal privado.
3. En Debian prepara `.env.pilot` y detén `api`, `worker`, `web` y `cloudflared` si el proyecto ya está en ejecución. Ejecuta `python3 scripts/compartir_base.py importar RUTA/geocattle.dump --destino produccion --env-file .env.pilot`. El importador hace un respaldo del destino existente, comprueba SHA-256, restaura en una base temporal, valida las migraciones, aplica las pendientes y convierte el entorno de los predios físicos a `production` antes de activar la copia. La operación sustituye el contenido del destino por el de la instantánea.
4. Si conservas los factores TOTP, configura `MFA_ENCRYPTION_KEY` del destino con la clave efectiva del origen (`MFA_ENCRYPTION_KEY` o, si estaba vacía, `SESSION_SECRET`). Si cambias esa clave, aplica el procedimiento de restablecimiento a las cuentas afectadas. Revisa invitaciones pendientes si cambia la clave de sesión o el dominio. Ejecuta `start` de producción y verifica usuarios, MFA, predios, inventario, telemetría y geocercas antes de activar la estación remota. [Copias privadas y TOTP](OPERACION.md#compartir-una-copia-del-prototipo)

## Administración PostgreSQL remota con Access

La administración habitual se hace desde el servidor con Docker. Si necesitas una conexión remota temporal, crea primero una aplicación Cloudflare Access para `db.example.com` con solo las identidades administradoras autorizadas y MFA. Después agrega una ruta de tipo **TCP** a `tcp://database:5432`. Para que el conector alcance PostgreSQL, incorpora este archivo privado adicional en `COMPOSE_FILE` en el servidor durante el acceso.

```yaml
services:
  cloudflared:
    networks:
      default:
```

Guárdalo como `.runtime/compose.db-access.yaml` y ejecuta `COMPOSE_FILE=compose.yaml:compose.cloudflare.yaml:.runtime/compose.db-access.yaml bash scripts/compose.sh up -d cloudflared`. Comprueba que un intento sin sesión Access sea rechazado antes de distribuir el hostname. Conserva PostgreSQL sin puertos publicados.

Provisiona un login PostgreSQL exclusivo, con contraseña propia, sin privilegios de dueño ni escritura. Otorga `CONNECT` solo a la base requerida, `USAGE` solo al esquema necesario y `SELECT` sobre las vistas o tablas específicas que requiere su tarea. Revisa también los permisos heredados de `PUBLIC` en las bases de la instancia. En el cliente usa el proxy local y abre `psql` con ese usuario.

```bash
cloudflared access tcp --hostname db.example.com --url localhost:15432
psql -h 127.0.0.1 -p 15432 -U geocattle_readonly -d geocattle_pilot
```

Al terminar retira la ruta TCP y recrea el conector con los dos archivos Compose habituales. [Cloudflare Access para TCP](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/use-cases/tcp/)
