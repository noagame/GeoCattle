# Scripts de operación y desarrollo

## Propósito y alcance

`docker_project.py` gestiona entornos Docker. `local_backend.py` ejecuta tareas de desarrollo y QA. `prototype_windows.py` levanta el prototipo nativo y `start_capture.py` selecciona contexto y receptor. Los scripts de respaldo y exportación conservan datos. `preparar_mapa_satelital.py` genera recursos que consume el frontend.

## Contratos locales

- Al cambiar arranque o captura revisa los lanzadores de la raíz y sus argumentos. Mantén alineados entorno, archivo de configuración, URL de API y directorio de captura.
- Conserva los volúmenes, respaldos y colas al detener o reiniciar servicios. Mantén las pruebas con efectos sobre datos en una instancia QA.
- `serve_lan_windows.py` sirve el prototipo por HTTPS en el puerto `8445` de una IPv4 privada. Reutiliza PostgreSQL local y la interfaz compilada. Aplica cookie segura y MFA para administrador. Guarda las claves en `%LOCALAPPDATA%\GeoCattle\lan-tls` y exporta solo el certificado público a `.runtime/`.
- El iniciador LAN detecta la IPv4 al abrirse y muestra el enlace aunque GeoCattle ya esté escuchando en ella. Guarda el último enlace verificado en `.runtime/GeoCattle-LAN-URL.txt`. Si hay varias direcciones sin una ruta preferida, la opción `--bind` selecciona la red.
- `register_collar_usb.py` identifica el collar recién conectado por el descriptor USB o por un paquete JSON V5 del emisor directo. Espera hasta 55 segundos para admitir el ciclo de 45 segundos de firmware anterior y descarta los sobres de receptor. Conserva los perfiles de recepción y abre el inventario local con un borrador de alta. La confirmación usa la sesión web del predio.
- Al cambiar la generación cartográfica revisa el manifiesto y la ruta de teselas que consume [frontend](../frontend/AGENTS.md).

## Verificación

Usa `python -m unittest qa.test_docker_project qa.test_docker_portability_safety` desde la raíz para cambios de orquestación Docker. Para el inicio de captura usa `qa.test_capture_startup` y `qa.test_capture_portability` en el entorno de [CI](../.github/workflows/validacion.yml). [Portabilidad Docker](../docs/REVISION_DOCKER_PORTABILIDAD.md) · [Prototipo Windows](../docs/DESARROLLO_LOCAL.md)
