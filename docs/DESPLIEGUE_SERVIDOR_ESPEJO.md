# Desplegar el servidor espejo (guía para el administrador del servidor o su agente de IA)

Esta guía es el procedimiento completo para instalar GeoCattle como **servidor espejo** en un Debian ajeno. Tiene dos partes:

- **[Parte A](#parte-a--servidor-administrador-o-su-ia)**. El administrador del servidor o su agente publica la web y entrega los datos de acceso al dueño del PC.
- **[Parte B](#parte-b--conexión-con-el-pc-dueño-del-pc-con-su-acceso-ssh)**: el dueño conecta desde Windows con un solo comando y su acceso SSH personal.

Si administras el servidor, ejecuta solo la Parte A, en orden, y respeta las [reglas](#reglas-que-no-se-negocian).

## Qué se está desplegando

GeoCattle tiene dos instalaciones:

| | PC del campo (Windows, del dueño del proyecto) | Servidor espejo (Debian, esta guía) |
| --- | --- | --- |
| Rol | **Sistema principal.** Recibe los collares por USB, guarda todo y crea las cuentas. | **Copia de solo lectura** publicada en internet. |
| Base de datos | PostgreSQL nativo, publicación lógica `geocattle_espejo`. | PostGIS en Docker, suscripción `geocattle_espejo`. |
| Escrituras | Todas. | Ninguna directa: solicitudes de veterinario, órdenes del administrador y solicitudes de soporte quedan en una bandeja (`mirror_outbox`) que el PC recoge y aplica. |
| Internet | Puede estar sin conexión; al volver se pone al día. | Publica la web por Cloudflare Tunnel; **no abre puertos de entrada**. |

### Cómo se conectan

El PC inicia todas las conexiones con **una sola cuenta SSH del servidor** (la del dueño del proyecto). No hay puertos nuevos en el servidor ni VPN.

```text
PC ──ssh usuario@servidor (cuenta Linux normal, -L 18022 → 172.30.248.19:22)
      └─► contenedor espejo-ssh (IP fija 172.30.248.19 en la red Docker tunnel-web)
            ├─ -R 15432 → PostgreSQL del PC   ──► la base del servidor se suscribe aquí (PC → servidor)
            └─ -L 18095 → web:80 del servidor  ──► el worker del PC lee la bandeja (servidor → PC)
Internet ──► Cloudflare ──► cloudflared (contenedor) ──► web:80   (solo la página web)
```

- **PC → servidor:** replicación lógica de PostgreSQL. Un cambio en el PC aparece en la web en menos de un segundo.
- **Servidor → PC:** el worker del PC consulta la bandeja cada pocos segundos con `MIRROR_SYNC_KEY`, aplica cada envío una sola vez con su autor y el resultado vuelve por la replicación.
- **Cortes:** si el PC se apaga, la web sigue mostrando los últimos datos y marca «datos del campo hace N». La bandeja guarda los envíos y la suscripción reintenta cada 5 s. El PC retiene hasta 2 GB de cambios.
- **Validación mutua:** el PC fija las huellas SSH del servidor y de `espejo-ssh` y rechaza un cambio. El servidor acepta la llave del PC solo para ese salto: `restrict`, `permitopen="172.30.248.19:22"` y `command="/bin/false"`, sin consola. La bandeja exige `MIRROR_SYNC_KEY` y la suscripción `MIRROR_REPLICA_PASSWORD`.

## Reglas que no se negocian

1. **Secretos.** `MFA_ENCRYPTION_KEY`, `MIRROR_REPLICA_PASSWORD`, `MIRROR_SYNC_KEY`, `TUNNEL_TOKEN` y las contraseñas de `.env.pilot` nunca se escriben en el chat, en registros, en tickets ni en Git. `pc-connect` intercambia las claves necesarias por la sesión SSH personal. Para comprobar que existen usa `grep -c '^CLAVE=' .env.pilot`, sin mostrar su valor. `.env.pilot` queda con `chmod 600`.
2. **Cuentas de GeoCattle.** Crea la cuenta Linux para SSH en A1. Las cuentas de la aplicación, los predios y los factores TOTP llegan del PC. El perfil `mirror` rechaza `--admin-email` y `--owner-email`.
3. **No borrar volúmenes.** Nunca `docker compose down -v`, `docker volume rm` ni `docker system prune --volumes`. En especial `espejo-ssh-keys`: si sus llaves cambian, el PC deja de conectarse porque fijó la huella. Tampoco regeneres las llaves SSH del host (`/etc/ssh/ssh_host_*`).
4. **No abrir puertos** ni publicar `5432`, `15432`, `18084` u otros en el host. La web sale solo por Cloudflare Tunnel.
5. **No editar** los `compose*.yaml`, el código ni `scripts/` del paquete. Si algo falla, informa el error tal cual al dueño del PC.
6. **No ejecutar en el servidor** los comandos del PC (`pc-setup`, `pc-admin`, `keygen`, `tunnel`, `install-task`, `pc-status`, `pc-drop-slot`).
7. Usa la llave **personal** para habilitar el acceso SSH en A1. `pc-connect` usa `authorize --host-account` para instalar la llave **del túnel** con permisos limitados.

## Requisitos del servidor

- Debian 12 o 13, `amd64` (`uname -m` → `x86_64`). Para `arm64` la imagen `postgis/postgis:16-3.4` no sirve sin cambios: detente y avisa.
- 2 GB de RAM y 5 GB de disco libres. Acceso administrativo a Debian con `sudo` o una consola de root.
- **Docker Engine nativo** con el plugin Compose 2.24 o superior. No sirven Docker rootless, Docker Desktop ni Docker dentro de otra VM, porque la cuenta SSH debe alcanzar la IP del contenedor `172.30.248.19` desde el host.
- Subredes Docker `172.30.248.0/28` y `172.30.248.16/28` libres (`docker network inspect` de las redes existentes).
- Salida a internet HTTPS y TCP/UDP 7844 hacia Cloudflare. Sin puertos de entrada nuevos.
- **Una cuenta Linux para el dueño del PC** (por ejemplo `geocattle`), con:
  - acceso por SSH con su llave personal;
  - pertenencia al grupo `docker`;
  - reenvío TCP local permitido, con `AllowTcpForwarding yes` o `local`, `DisableForwarding no` y `PermitOpen any` o un permiso para `172.30.248.19:22`. Si hay reglas `Match`, verifica que se cumplan desde la dirección de origen del PC.
- **Todos los comandos de GeoCattle se ejecutan con esa cuenta**, desde `/srv/GeoCattle`. `authorize --host-account` escribe en el `~/.ssh/authorized_keys` de quien lo ejecuta, y esa debe ser la cuenta a la que entra el PC.

### Cloudflare

Hace falta un dominio en Cloudflare y un túnel administrado desde el panel (Zero Trust → Networks → Tunnels):

1. Crea el túnel (tipo *cloudflared*) y copia su **token**. Ese token es el `TUNNEL_TOKEN`.
2. Agrega un *Public hostname*, por ejemplo `geocattle.ejemplo.cl`, con servicio **HTTP** y URL `web:80`.
3. No instales `cloudflared` en el host: corre como contenedor del paquete.

Para publicar la web se necesita acceso al dominio y al túnel. Si los gestiona otra persona, coordina con ella A2 mientras avanzas con Debian y el paquete.

## Parte A · Servidor (administrador o su IA)

Los bloques usan Bash y la cuenta `geocattle`. Ejecútalos en el Debian del servidor. Desde A3, los comandos de GeoCattle corren como esa cuenta para que el dueño del PC pueda administrar `/srv/GeoCattle`.

### A0. Abrir la entrega

Si recibiste el ZIP, cópialo a `/tmp/GeoCattle-servidor-espejo.zip` en Debian y extrae su contenido en un directorio nuevo. En una consola root puedes omitir `sudo`.

```bash
sudo apt-get update
sudo apt-get install -y unzip
sudo mkdir -m 755 /tmp/geocattle-envio &&
  sudo unzip -q /tmp/GeoCattle-servidor-espejo.zip -d /tmp/geocattle-envio &&
  sudo chmod a+r /tmp/geocattle-envio/*
```

Si ya tienes los archivos extraídos, pon en `/tmp/geocattle-envio/` el TAR, su SHA-256 y `llave-ssh-dueno.pub` con permiso de lectura para `geocattle`. Usa un solo paquete por directorio.

### A1. Docker y cuenta

En Debian limpio, configura el repositorio oficial e instala Docker Engine y Compose. Si ya tienes Docker Engine nativo, conserva esa instalación y ejecuta solo las dos primeras órdenes del bloque. Verifica Docker y Compose al crear la cuenta. [Instalación oficial de Docker en Debian](https://docs.docker.com/engine/install/debian/)

```bash
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl python3
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
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker info --format 'Docker {{.ServerVersion}}'
```

Comprueba que `python3 --version` y `curl --version` funcionen. Revisa que no haya redes que se solapen con las del espejo.

```bash
sudo docker network ls -q | xargs -r sudo docker network inspect \
  --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}'
```

Usa el servicio SSH del Debian. Si administras un Debian limpio desde consola y falta el servicio, instálalo con `sudo apt-get install -y openssh-server` y actívalo con `sudo systemctl enable --now ssh`.

Instala la llave pública **personal** del dueño del PC. El bloque conserva las llaves que ya estén autorizadas. El grupo `docker` da acceso administrativo al servidor. [Permisos de Docker](https://docs.docker.com/engine/install/linux-postinstall/)

```bash
if ! id geocattle >/dev/null 2>&1; then
  sudo adduser --disabled-password --gecos GeoCattle geocattle
fi
sudo usermod -aG docker geocattle
sudo install -d -o geocattle -g geocattle /srv/GeoCattle
sudo -iu geocattle bash -se <<'BASH'
umask 077
install -d -m 700 "$HOME/.ssh"
authorized="$HOME/.ssh/authorized_keys"
key=$(cat /tmp/geocattle-envio/llave-ssh-dueno.pub)
test -n "$key"
touch "$authorized"
chmod 600 "$authorized"
if ! grep -Fxq -- "$key" "$authorized"; then
  printf '\n%s\n' "$key" >> "$authorized"
fi
docker compose version
docker info --format 'Docker {{.ServerVersion}}'
BASH
```

Revisa la configuración efectiva de SSH. Si usas reglas `Match`, sustituye `host` y `addr` por el nombre y la IP con los que el servidor verá al PC. Consulta [Requisitos del servidor](#requisitos-del-servidor).

```bash
sudo sshd -T -C user=geocattle,host=localhost,addr=127.0.0.1 \
  | grep -E '^(pubkeyauthentication|allowtcpforwarding|disableforwarding|permitopen|authorizedkeysfile) '
```

### A2. Cloudflare

Crea el túnel y su nombre público con HTTP `web:80` como origen. Deja solo el token, en una línea, en `~geocattle/.geocattle-tunnel-token` (propietario `geocattle`, permisos `600`). A4 lo incorporará a `.env.pilot` y retirará esa copia temporal. Con un gestor de secretos puedes provisionar el archivo directamente. Si copias el token desde el panel, este comando permite pegarlo sin eco en una consola privada.

```bash
cd / && sudo -u geocattle -H bash -c '
  umask 077
  IFS= read -rsp "Token de Cloudflare: " token || exit 1
  printf "\n" >&2
  printf "%s\n" "$token" > "$HOME/.geocattle-tunnel-token"
  chmod 600 "$HOME/.geocattle-tunnel-token"
'
```

### A3. Paquete

```bash
sudo -iu geocattle bash -se <<'BASH'
cd /tmp/geocattle-envio
sha256sum --strict -c geocattle-*.tar.gz.sha256
umask 022
tar -xzf geocattle-*.tar.gz -C /srv/GeoCattle
BASH
```

La suma debe indicar `OK` antes de extraer. La máscara `022` de este bloque permite que el usuario sin privilegios de la imagen lea el código y las migraciones. Lee `/srv/GeoCattle/AGENTS.md` para confirmar el alcance del despliegue.

### A4. Configuración y arranque

Reemplaza `geocattle.ejemplo.cl` por el nombre público de A2, sin `https://`.

```bash
sudo -iu geocattle bash -se -- geocattle.ejemplo.cl <<'BASH'
cd /srv/GeoCattle
domain=$1
python3 scripts/docker_project.py prepare --environment production --env-file .env.pilot --domain "$domain"
python3 scripts/mirror.py server-init --skip-secrets
chmod 600 .env.pilot
python3 - <<'PY'
from pathlib import Path
import re

config = Path(".env.pilot")
token_file = Path.home() / ".geocattle-tunnel-token"
lines = config.read_text(encoding="utf-8").splitlines()
entries = [index for index, line in enumerate(lines) if line.startswith("TUNNEL_TOKEN=")]
if len(entries) != 1:
    raise SystemExit("Comprueba que .env.pilot tenga una sola línea TUNNEL_TOKEN=.")
entry = entries[0]
if token_file.exists():
    if token_file.stat().st_mode & 0o077:
        raise SystemExit("Aplica chmod 600 al archivo privado del token de A2.")
    token = token_file.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_+/=.-]+", token) or token == "TOKEN_FICTICIO_DE_CLOUDFLARE":
        raise SystemExit("Introduce un token válido en el archivo privado de A2.")
    lines[entry] = f"TUNNEL_TOKEN={token}"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    token_file.unlink()
elif lines[entry] in ("TUNNEL_TOKEN=", "TUNNEL_TOKEN=TOKEN_FICTICIO_DE_CLOUDFLARE"):
    raise SystemExit("Falta el token de Cloudflare. Completa A2 y vuelve a ejecutar A4.")
PY
python3 scripts/docker_project.py start --environment production --env-file .env.pilot --profile cloudflare --profile mirror
docker compose --env-file .env.pilot \
  -f compose.yaml -f compose.cloudflare.yaml -f compose.mirror.yaml \
  --profile cloudflare --profile mirror ps --all
curl --fail --silent --show-error --retry 5 --retry-all-errors --max-time 15 \
  "https://$domain/api/v1/health"
BASH
```

`prepare` crea `.env.pilot` con valores nuevos en la primera ejecución y lo conserva al repetir A4. `server-init --skip-secrets` genera `MIRROR_SYNC_KEY` y `.runtime/espejo/authorized_keys`. La primera construcción tarda varios minutos. Comprueba que `database`, `api`, `web`, `cloudflared` y `espejo-ssh` estén *healthy*, que `worker` esté *Up* y que `migrate` haya terminado con `Exited (0)`. El endpoint público debe responder HTTP 200.

### A5. Entrega

La web queda publicada pero **vacía y sin cuentas**: es lo esperado. Los datos y las cuentas llegan cuando el dueño conecta su PC en la Parte B. Entrega al dueño del PC:

- la cuenta SSH, la IP o nombre del servidor y el puerto SSH;
- el dominio público;
- la salida de `docker compose ps --all` y la respuesta de salud de A4.

Aquí termina tu parte. El dueño conectará desde su PC con la cuenta SSH entregada.

## Parte B · Conexión con el PC (dueño del PC, con su acceso SSH)

`CUENTA@SERVIDOR` es la cuenta recibida, con `:PUERTO` si SSH no usa el 22. En el PC los comandos se ejecutan desde la carpeta de GeoCattle con `.venv\Scripts\python.exe`.

### B1. Administrador y TOTP en el PC

Abre `Abrir-GeoCattle.cmd`. Si aún no tienes un administrador de plataforma, créalo en el PC. `pc-admin` pide una contraseña de al menos 12 caracteres sin eco. Luego entra en `http://localhost:8084` con esa cuenta y activa el TOTP en **Mi perfil → Activar doble verificación**.

```bat
.venv\Scripts\python.exe scripts\mirror.py pc-admin --email CORREO
```

En el primer enlace, conserva un respaldo verificado del PC. [Respaldos del prototipo](OPERACION.md#compartir-una-copia-del-prototipo)

### B2. Conectar el espejo desde Windows

```bat
.venv\Scripts\python.exe scripts\mirror.py pc-connect --ssh-jump CUENTA@SERVIDOR
```

Usa OpenSSH de Windows con tu llave personal en el agente SSH o en `~/.ssh`. Si tiene frase de paso, cárgala con `ssh-add` antes de conectar. Si está en otra ruta, indica `--identity-file RUTA`. Si el paquete se instaló fuera de `/srv/GeoCattle`, indica `--server-dir RUTA`.

El comando verifica el modo réplica del servidor, activa la publicación en el PC y configura la clave MFA y la llave restringida del túnel en el servidor. Si se actualiza la clave MFA, vuelve a ejecutar el arranque del servidor para aplicarla. Instala y ejecuta la tarea de Windows «GeoCattle Espejo», que mantiene el túnel y vuelve a iniciarlo al entrar a Windows. Al crear la suscripción comprueba las migraciones, respalda la base del servidor y espera la copia inicial. Confirma esa primera copia cuando el comando lo pida o usa `--yes` para confirmarla al invocarlo. Las huellas SSH quedan en `.runtime\espejo\known_hosts`.

Si falla un paso, corrige la causa indicada y repite el mismo comando. Se conserva una suscripción existente y se informa su estado. `--no-task` mantiene el túnel en segundo plano durante la sesión de Windows, sin registrarlo para el próximo inicio.

### B3. Verificación

Al terminar, `pc-connect` muestra el `status` remoto. Comprueba «Suscripción: activa», un último mensaje del PC de hace pocos segundos y un pulso del campo reciente. Luego abre `https://DOMINIO` y comprueba lo siguiente.

- Al entrar con una cuenta aparece «Datos del campo al … (hace N s)» y el pie dice «Conectado al servidor web».
- Los mapas ofrecen OpenStreetMap y «Satélite en línea». Los mapas locales no existen en el servidor; es lo esperado.
- El administrador entra con contraseña y TOTP. Una solicitud de soporte enviada desde la web pasa a «Aplicado» en «Mis envíos».
- Con la captura USB del PC en marcha, **Hardware → Receptor USB** muestra en la web «Captura activa» con los mismos contadores que el PC. Esos contadores llegan en `receiver_status` y vencen 90 s después de que la captura se detiene. Si el PC tiene varios predios físicos activos, necesita `INGEST_FARM_ID` en su `.env.academic`. Los collares nuevos se aprueban en el PC; en la web solo se ven como detección pendiente.
- `curl -s -o /dev/null -w '%{http_code}' -X POST https://DOMINIO/api/v1/ingest/telemetry` responde `403` o `401`: la web no acepta ingesta.

## Apéndice · Conexión manual

Si necesitas ejecutar los pasos por separado, usa el orden siguiente con la Parte A completa y tu acceso SSH personal.

1. En el PC, ejecuta `mirror.py pc-setup --ssh-jump CUENTA@SERVIDOR`. Cuando pida `MIRROR_SYNC_KEY`, introdúcela desde el `.env.pilot` privado del servidor. Ejecuta `mirror.py keygen` y transfiere solo `id_ed25519.pub`.
2. En el servidor, ejecuta `python3 scripts/mirror.py server-init` e introduce la `MFA_ENCRYPTION_KEY` de tu archivo privado del PC. Ejecuta `python3 scripts/mirror.py authorize id_ed25519.pub --host-account`. Si agregaste la clave MFA, repite `start` del paso A4.
3. Reinicia GeoCattle en el PC para cargar su configuración y ejecuta `mirror.py install-task` y `schtasks /Run /TN "GeoCattle Espejo"`.
4. En el servidor, ejecuta `python3 scripts/mirror.py subscribe --pc-database NOMBRE_DE_POSTGRES_DB_DEL_PC`. Introduce `MIRROR_REPLICA_PASSWORD` cuando se pida y comprueba con `python3 scripts/mirror.py status`.

## Operación

| Situación | Qué hacer |
| --- | --- |
| `status` sin mensajes recientes | El PC está apagado o sin internet: es normal y se pone al día solo. Si el PC está encendido, revisa `docker compose logs espejo-ssh` y pide al dueño su `.runtime\espejo\tunel.log`. |
| «Errores aplicar» sube durante un corte | Normal: son conexiones rechazadas mientras el PC no está. Si sube con el PC conectado, revisa `docker compose logs database`: distintas migraciones en PC y servidor (ver Actualizar). |
| TOTP rechazado solo en la web | El dueño comprueba que `MFA_ENCRYPTION_KEY` coincida en ambos archivos privados y, si corrige la del servidor, repite el arranque de A4. |
| El PC estuvo desconectado más de lo que caben 2 GB de cambios | El dueño ejecuta en el servidor `python3 scripts/mirror.py resync --pc-database geocattle_academic`. |
| Reinicio del servidor | Los contenedores vuelven solos (`restart: unless-stopped`). Comprueba con `status`. |

### Actualizar

El dueño del PC envía un paquete nuevo. Se actualiza **primero el servidor y después el PC**:

```bash
cd /tmp && sha256sum -c geocattle-*.tar.gz.sha256
tar -xzf /tmp/geocattle-NUEVO.tar.gz -C /srv/GeoCattle && cd /srv/GeoCattle    # conserva .env.pilot y .runtime/
python3 scripts/docker_project.py start --environment production --env-file .env.pilot --profile cloudflare --profile mirror
```

Luego el dueño actualiza el PC (`Abrir-GeoCattle.cmd` migra), ejecuta `mirror.py pc-setup` en el PC y `python3 scripts/mirror.py refresh` en el servidor. Mientras los esquemas difieran, la suscripción reintenta sin aplicar cambios y no daña datos.

### Respaldos

Los datos reales viven en el PC. La base del servidor es reconstruible con `resync`, por lo que el servidor no necesita su propio temporizador de respaldos. Basta conservar `/srv/GeoCattle/.env.pilot`, `/srv/GeoCattle/.runtime/` y los volúmenes Docker.
