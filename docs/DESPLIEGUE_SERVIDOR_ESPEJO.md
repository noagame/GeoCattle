# Desplegar el servidor espejo (guía para el administrador del servidor o su agente de IA)

Esta guía es el procedimiento completo para instalar GeoCattle como **servidor espejo** en un Debian ajeno. Si eres un agente de IA que configura el servidor: síguela en orden, respeta las [reglas](#reglas-que-no-se-negocian) y detente en cada paso marcado **[ESPERA AL DUEÑO DEL PC]**. Los comandos de las secciones de referencia están en [Despliegue en Debian](DESPLIEGUE_DEBIAN_CLOUDFLARE.md#modo-espejo-el-pc-del-campo-como-sistema-principal).

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

1. **Secretos.** `MFA_ENCRYPTION_KEY`, `MIRROR_REPLICA_PASSWORD`, `MIRROR_SYNC_KEY`, `TUNNEL_TOKEN` y las contraseñas de `.env.pilot` nunca se escriben en el chat, en registros, en tickets ni en Git. Los comandos que los piden (`server-init`, `subscribe`) los leen **sin eco**: deja que el dueño del PC los escriba en su propia sesión SSH. Para comprobar que existen usa `grep -c '^CLAVE=' .env.pilot`, nunca muestres su valor. `.env.pilot` queda con `chmod 600`.
2. **No crear cuentas en el servidor.** Las cuentas, predios y factores TOTP llegan del PC. No uses `--admin-email` ni `--owner-email` (el script los rechaza con el perfil `mirror`) ni insertes usuarios en la base.
3. **No borrar volúmenes.** Nunca `docker compose down -v`, `docker volume rm` ni `docker system prune --volumes`. En especial `espejo-ssh-keys`: si sus llaves cambian, el PC deja de conectarse porque fijó la huella. Tampoco regeneres las llaves SSH del host (`/etc/ssh/ssh_host_*`).
4. **No abrir puertos** ni publicar `5432`, `15432`, `18084` u otros en el host. La web sale solo por Cloudflare Tunnel.
5. **No editar** los `compose*.yaml`, el código ni `scripts/` del paquete. Si algo falla, informa el error tal cual al dueño del PC.
6. **No ejecutar en el servidor** los comandos del PC (`pc-setup`, `pc-admin`, `keygen`, `tunnel`, `install-task`, `pc-status`, `pc-drop-slot`).
7. Las llaves del PC se autorizan **solo** con `scripts/mirror.py authorize … --host-account`, no editando `authorized_keys` a mano.

## Requisitos del servidor

- Debian 12 o 13, `amd64` (`uname -m` → `x86_64`). Para `arm64` la imagen `postgis/postgis:16-3.4` no sirve sin cambios: detente y avisa.
- 2 GB de RAM y 5 GB de disco libres. `python3` (viene con Debian).
- **Docker Engine nativo** con el plugin Compose 2.24 o superior. No sirven Docker rootless, Docker Desktop ni Docker dentro de otra VM, porque la cuenta SSH debe alcanzar la IP del contenedor `172.30.248.19` desde el host.
- Subredes Docker `172.30.248.0/28` y `172.30.248.16/28` libres (`docker network inspect` de las redes existentes).
- Salida a internet HTTPS y TCP/UDP 7844 hacia Cloudflare. Sin puertos de entrada nuevos.
- **Una cuenta Linux para el dueño del PC** (por ejemplo `geocattle`), con:
  - acceso por SSH con su llave personal;
  - pertenencia al grupo `docker`;
  - reenvío TCP permitido: `AllowTcpForwarding yes` (valor por defecto) y sin `DisableForwarding`, `PermitOpen none` ni `Match` que lo anulen para esa cuenta. Revisa con `sudo sshd -T -C user=geocattle,host=x,addr=127.0.0.1 | grep -Ei 'forwarding|permitopen'`.
- **Todos los comandos de GeoCattle se ejecutan con esa cuenta**, desde `/srv/GeoCattle`. `authorize --host-account` escribe en el `~/.ssh/authorized_keys` de quien lo ejecuta, y esa debe ser la cuenta a la que entra el PC.

### Cloudflare

Hace falta un dominio en Cloudflare y un túnel administrado desde el panel (Zero Trust → Networks → Tunnels):

1. Crea el túnel (tipo *cloudflared*) y copia su **token**. Ese token es el `TUNNEL_TOKEN`.
2. Agrega un *Public hostname*, por ejemplo `geocattle.ejemplo.cl`, con servicio **HTTP** y URL `web:80`.
3. No instales `cloudflared` en el host: corre como contenedor del paquete.

Quien administre el dominio decide quién crea el túnel. Si no eres tú, pide el token por un canal privado y que lo pegue directamente en `.env.pilot`.

## Procedimiento

Usa `DOMINIO` (por ejemplo `geocattle.ejemplo.cl`) y `CUENTA@SERVIDOR`: la cuenta del dueño del PC y la IP o nombre del servidor, con `:PUERTO` si SSH no usa el 22.

### 1. Docker y cuenta (administrador del servidor)

Instala Docker Engine desde el repositorio oficial ([guía](DESPLIEGUE_DEBIAN_CLOUDFLARE.md#instalar-docker-engine-y-compose)), crea la cuenta del dueño del PC con su llave pública personal, agrégala al grupo `docker` y crea `/srv/GeoCattle` con esa cuenta como dueña. Comprueba `docker compose version` desde la cuenta.

### 2. Paquete

El dueño del PC entrega `geocattle-AAAAmmddTHHMMSSZ.tar.gz` y su `.sha256`:

```bash
cd /tmp && sha256sum -c geocattle-*.tar.gz.sha256        # debe decir OK
tar -xzf /tmp/geocattle-*.tar.gz -C /srv/GeoCattle && cd /srv/GeoCattle
```

### 3. Configuración privada, primera parte

```bash
python3 scripts/docker_project.py prepare --environment production --env-file .env.pilot --domain DOMINIO
python3 scripts/mirror.py server-init --skip-secrets
chmod 600 .env.pilot
```

`prepare` crea `.env.pilot` con contraseñas aleatorias y nunca reemplaza un archivo existente. Esta primera pasada de `server-init` genera `MIRROR_SYNC_KEY` y `.runtime/espejo/authorized_keys`, sin pedir nada.

### 4. [ESPERA AL DUEÑO DEL PC] Configuración del PC

El dueño del PC, en su propia sesión SSH, lee la clave con `grep ^MIRROR_SYNC_KEY= /srv/GeoCattle/.env.pilot` y luego, en Windows y con GeoCattle cerrado:

```bat
.venv\Scripts\python.exe scripts\compartir_base.py exportar --verificar
.venv\Scripts\python.exe scripts\mirror.py pc-setup --ssh-jump CUENTA@SERVIDOR
.venv\Scripts\python.exe scripts\mirror.py keygen
```

`pc-setup` activa la replicación lógica y pide sin eco la `MIRROR_SYNC_KEY`. Además crea en `.env.academic` la `MFA_ENCRYPTION_KEY` y la `MIRROR_REPLICA_PASSWORD`. `keygen` imprime una línea `ssh-ed25519 …` pública: el dueño la envía como archivo `id_ed25519.pub`. **No es secreta.**

### 5. [ESPERA AL DUEÑO DEL PC] Configuración privada, segunda parte

El dueño del PC ejecuta en el servidor, en su sesión:

```bash
cd /srv/GeoCattle && python3 scripts/mirror.py server-init
```

Esta vez pide sin eco la `MFA_ENCRYPTION_KEY` de su `.env.academic`. Sin ella los códigos TOTP de las cuentas no funcionan en la web. Después, quien tenga el token lo pega en `TUNNEL_TOKEN=` de `.env.pilot` (reemplaza `TOKEN_FICTICIO_DE_CLOUDFLARE`).

Comprueba sin mostrar valores:

```bash
for k in MIRROR_SYNC_KEY MFA_ENCRYPTION_KEY TUNNEL_TOKEN; do printf '%s ' "$k"; grep -c "^$k=" .env.pilot; done
grep -c '^TUNNEL_TOKEN=TOKEN_FICTICIO' .env.pilot      # debe dar 0
```

### 6. Arranque

```bash
python3 scripts/docker_project.py start --environment production --env-file .env.pilot --profile cloudflare --profile mirror
docker builder prune -f
curl -fsS https://DOMINIO/api/v1/health
```

La primera vez construye las imágenes (varios minutos). Deben quedar *healthy* `database`, `api`, `worker`, `web`, `cloudflared` y `espejo-ssh`. `migrate` termina con código 0. Para los comandos `docker compose` directos, exporta antes:

```bash
export COMPOSE_FILE=compose.yaml:compose.cloudflare.yaml:compose.mirror.yaml COMPOSE_ENV_FILES=.env.pilot COMPOSE_PROFILES=cloudflare,mirror
docker compose ps
```

### 7. Autorizar la llave del PC

Copia `id_ed25519.pub` a `/srv/GeoCattle/` y, **con la cuenta del dueño del PC**:

```bash
python3 scripts/mirror.py authorize id_ed25519.pub --host-account
tail -n 1 ~/.ssh/authorized_keys     # debe empezar con restrict,port-forwarding,permitopen="172.30.248.19:22",command="/bin/false"
```

### 8. [ESPERA AL DUEÑO DEL PC] Túnel y primer administrador

En el PC: abrir `Abrir-GeoCattle.cmd`, crear el administrador con `scripts\mirror.py pc-admin --email CORREO` y activar su TOTP en **Mi perfil → Activar doble verificación**. Después deja el túnel permanente:

```bat
.venv\Scripts\python.exe scripts\mirror.py install-task
schtasks /Run /TN "GeoCattle Espejo"
```

El primer túnel guarda las huellas SSH del servidor y de `espejo-ssh` en el PC.

### 9. [ESPERA AL DUEÑO DEL PC] Suscripción

Con el túnel abierto, el dueño del PC ejecuta en el servidor, en su sesión:

```bash
cd /srv/GeoCattle && python3 scripts/mirror.py subscribe --pc-database geocattle_academic
```

Pide sin eco la `MIRROR_REPLICA_PASSWORD` del PC. Comprueba que ambos lados tengan las mismas migraciones, respalda la base del servidor y copia la del PC. `geocattle_academic` es el `POSTGRES_DB` del PC.

### 10. Verificación final

```bash
python3 scripts/mirror.py status
```

Debe mostrar «Suscripción: activa», un último mensaje del PC de hace pocos segundos y un pulso del campo reciente. Luego, en `https://DOMINIO`:

- Al entrar con una cuenta aparece «Espejo del campo · datos al … (hace N s)» y el pie dice «Conectado al servidor web».
- Los mapas ofrecen OpenStreetMap y «Satélite en línea». Los mapas locales no existen en el servidor; es lo esperado.
- El administrador entra con contraseña y TOTP. Una solicitud de soporte enviada desde la web pasa a «Aplicado» en «Mis envíos».
- Con la captura USB del PC en marcha, **Hardware → Receptor USB** muestra en la web «Captura activa» con los mismos contadores que el PC. Esos contadores llegan en `receiver_status` y vencen 90 s después de que la captura se detiene. Si el PC tiene varios predios físicos activos, necesita `INGEST_FARM_ID` en su `.env.academic`. Los collares nuevos se aprueban en el PC; en la web solo se ven como detección pendiente.
- `curl -s -o /dev/null -w '%{http_code}' -X POST https://DOMINIO/api/v1/ingest/telemetry` responde `403` o `401`: la web no acepta ingesta.

Informa al dueño del PC: la salida de `status`, `docker compose ps`, y que no quedaron puertos nuevos (`ss -tlnp` sin `15432`, `18084` ni `5432` en interfaces públicas).

## Operación

| Situación | Qué hacer |
| --- | --- |
| `status` sin mensajes recientes | El PC está apagado o sin internet: es normal y se pone al día solo. Si el PC está encendido, revisa `docker compose logs espejo-ssh` y pide al dueño su `.runtime\espejo\tunel.log`. |
| «Errores aplicar» sube durante un corte | Normal: son conexiones rechazadas mientras el PC no está. Si sube con el PC conectado, revisa `docker compose logs database`: distintas migraciones en PC y servidor (ver Actualizar). |
| TOTP rechazado solo en la web | `MFA_ENCRYPTION_KEY` del servidor distinta de la del PC. El dueño la corrige en `.env.pilot` y se repite el paso 6. |
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
