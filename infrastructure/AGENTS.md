# Infraestructura

## Propósito y alcance

`nginx.conf` y `web.Dockerfile` sirven la web y encaminan solicitudes a la API. `Caddyfile` configura TLS. `mosquitto/` y `chirpstack/` contienen configuración de los perfiles IoT y LoRaWAN que declara Compose.

## Contratos locales

- Conserva las rutas `/api` al ajustar el proxy. Revisa cómo Compose monta los archivos y propaga la configuración a cada servicio.
- Compose monta `.runtime/mapa-satelital/` y `.runtime/mapa-osm/` de solo lectura en `web`. Nginx usa un worker y sirve `/mapa-local/satelite/` y `/mapa-local/osm/` con `Cache-Control: public, max-age=86400` para teselas WebP y PNG y `no-cache` para el manifiesto. Los recursos ausentes devuelven 404 y conservan las cabeceras de seguridad.
- Mantén opcionales el broker MQTT y ChirpStack. La recepción LoRa directa usa el capturador USB del anfitrión y la API. Conserva las credenciales fuera de los archivos de infraestructura versionados.
- En producción, `compose.cloudflare.yaml` elimina publicaciones de puertos. Cloudflared alcanza nginx por `tunnel-web`. Nginx confía en los encabezados de Cloudflare solo desde la IP reservada al conector y Uvicorn solo confía en nginx por `web-api`. Coordina cualquier cambio de IP en Compose y nginx.
- Nginx omite su versión en `Server` y emite HSTS cuando el esquema efectivo es HTTPS. La cabecera de esquema reenviada solo cuenta desde la IP reservada al conector.
- `img-src` de nginx permite las teselas de OpenStreetMap y `server.arcgisonline.com`, que sirve World Imagery al navegador en el espejo.
- El perfil espejo propaga `MIRROR_REMOTE_ADMIN` y `MIRROR_REMOTE_CHANGES` del archivo privado a API, worker y migración. Con valor `false` deshabilitan respectivamente las órdenes administrativas y los cambios veterinarios y las solicitudes personales de soporte.
- Mantén `espejo-ssh/Dockerfile` en una versión de Alpine con soporte de seguridad.
- `compose.mirror.yaml` (perfil `mirror`, junto a `compose.cloudflare.yaml`) pone API, worker y migración en `MIRROR_MODE=replica` y agrega `espejo-ssh` (`espejo-ssh/`): sshd sin shell ni contraseñas que solo acepta, con la clave del PC de `.runtime/espejo/authorized_keys`, reenvíos remotos a 15432 y 18084 y un reenvío local hacia `web:80` (bandeja del espejo). Vive en `default` y `tunnel-web` con la IP fija `172.30.248.19`, sin puertos publicados: el PC llega saltando desde la cuenta SSH del servidor. La llave del servidor persiste en el volumen `espejo-ssh-keys`.
- Las unidades `geocattle-backup.*` ejecutan y rotan respaldos PostgreSQL en Debian. Ajusta las rutas y la cuenta al instalarlas. Access puede proteger la ruta exacta de lotes HTTPS de la T3. [Despliegue](../docs/DESPLIEGUE_DEBIAN_CLOUDFLARE.md)

## Verificación

Valida con `docker compose config --quiet` usando los mismos archivos, variables y perfiles del entorno QA correspondiente. Revisa el flujo de [portabilidad Docker](../docs/REVISION_DOCKER_PORTABILIDAD.md) y la ruta `/api/v1/health` al verificar un arranque aislado.
