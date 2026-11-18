# Infraestructura

## Propósito y alcance

`nginx.conf` y `web.Dockerfile` sirven la web y encaminan solicitudes a la API. `Caddyfile` configura TLS. `mosquitto/` y `chirpstack/` contienen configuración de los perfiles IoT y LoRaWAN que declara Compose.

## Contratos locales

- Conserva las rutas `/api` al ajustar el proxy. Revisa cómo Compose monta los archivos y propaga la configuración a cada servicio.
- Mantén opcionales el broker MQTT y ChirpStack. La recepción LoRa directa usa el capturador USB del anfitrión y la API. Conserva las credenciales fuera de los archivos de infraestructura versionados.

## Verificación

Valida con `docker compose config --quiet` usando los mismos archivos, variables y perfiles del entorno QA correspondiente. Revisa el flujo de [portabilidad Docker](../docs/REVISION_DOCKER_PORTABILIDAD.md) y la ruta `/api/v1/health` al verificar un arranque aislado.
