# Scripts de operación y desarrollo

## Propósito y alcance

`docker_project.py` gestiona entornos Docker. `local_backend.py` ejecuta tareas de desarrollo y QA. `prototype_windows.py` levanta el prototipo nativo y `start_capture.py` selecciona contexto y receptor. Los scripts de respaldo y exportación conservan datos. `preparar_mapa_satelital.py` genera recursos que consume el frontend.

## Contratos locales

- Al cambiar arranque o captura revisa los lanzadores de la raíz y sus argumentos. Mantén alineados entorno, archivo de configuración, URL de API y directorio de captura.
- Conserva los volúmenes, respaldos y colas al detener o reiniciar servicios. Mantén las pruebas con efectos sobre datos en una instancia QA.
- `serve_lan_windows.py` sirve el prototipo por HTTPS en el puerto `8445` de una IPv4 privada. Reutiliza PostgreSQL local y la interfaz compilada. Aplica cookie segura y MFA para administrador. Guarda las claves en `%LOCALAPPDATA%\GeoCattle\lan-tls` y exporta solo el certificado público a `.runtime/`.
- El iniciador LAN detecta la IPv4 al abrirse y muestra el enlace aunque GeoCattle ya esté escuchando en ella. Guarda el último enlace verificado en `.runtime/GeoCattle-LAN-URL.txt`. Si hay varias direcciones sin una ruta preferida, la opción `--bind` selecciona la red.
- `account_maintenance.py` prueba SMTP y restablece TOTP en el prototipo. Usa `.env.academic` como configuración privada predeterminada y se conecta por loopback con la cuenta de aplicación para el restablecimiento. [Operación](../docs/OPERACION.md)
- `register_collar_usb.py` identifica el collar recién conectado por el descriptor USB o por un paquete JSON V5 del emisor directo. Espera hasta 55 segundos para admitir el ciclo de 45 segundos de firmware anterior y descarta los sobres de receptor. Registra la detección con la credencial privada de captura y abre el inventario. La aprobación usa la sesión web del predio.
- `seed_validation_data.py` prepara lotes ficticios en un predio de validación por actor y entorno. Usa la configuración privada explícita, exige un dueño con acceso o un administrador y ejecuta `pg_dump` sobre la misma base antes de cargar. Usa una transacción para el lote, conserva el flujo V3 y asigna pastoreo solo a versiones vigentes que ya existen. La carga excluye collares y telemetría. [Uso y recuperación](../docs/VERIFICACION.md#carga-de-un-rebaño-de-validación)
- Al cambiar la generación cartográfica revisa el manifiesto y la ruta de teselas que consume [frontend](../frontend/AGENTS.md).

## Verificación

Usa `python -m unittest qa.test_docker_project qa.test_docker_portability_safety` desde la raíz para cambios de orquestación Docker. Para el inicio de captura usa `qa.test_capture_startup` y `qa.test_capture_portability` en el entorno de [CI](../.github/workflows/validacion.yml). [Portabilidad Docker](../docs/REVISION_DOCKER_PORTABILIDAD.md) · [Prototipo Windows](../docs/DESARROLLO_LOCAL.md)

Para la carga de validación ejecuta `backend/tests/test_seed_validation_data.py` en PostGIS de QA y comprueba la vista previa, la carga y su repetición con el archivo privado de esa base. [Verificación](../docs/VERIFICACION.md#carga-de-un-rebaño-de-validación)
