# QA transversal

## Propósito y alcance

Pruebas de arranque, portabilidad, contratos seriales, adaptadores, ingesta y hardware API. Los scripts de humo y fixtures también viven aquí. `v3/` agrupa evidencias de la verificación V3 y su script de humo.

## Contratos locales

- Las pruebas de contrato usan entradas ficticias y servicios de prueba. Para una prueba con PostgreSQL usa una base QA aislada. `test_hardware_api.py` exige `GEOCATTLE_TEST_DATABASE=1`, `TEST_DATABASE_URL`, esquema migrado y fixtures.
- `test_hardware_api.py` comprueba también la persistencia del heartbeat T3, su vencimiento y el acceso por predio y rol.
- `test_register_collar_usb.py` comprueba la identificación y el POST de detección. `test_lora_usb.py` y `test_academic_bridge.py` verifican el recibo de candidato en las colas de captura.
- `test_lora_usb.py` cubre espera de lote ante 429 y 5xx y vinculación de la cola con su destino. `test_lora_bus.py` comprueba que el lote HTTPS de la T3 conserva la identidad USB, marca el reloj estimado y rechaza una trama directa.
- `test_register_gateway_usb.py` cubre la identificación, la reserva y la configuración del nodo por USB del asistente de gateways.
- `test_mirror_tables.py` exige que cada tabla de las migraciones tenga una sola clase del modo espejo. `test_mirror_script.py` comprueba la publicación, la suscripción, el túnel (con Cloudflare y solo SSH), las claves restringidas del contenedor y de la cuenta del servidor, la IP fija de `espejo-ssh`, el perfil `mirror` y que solo se reinicie la base nativa propia.
- `test_mirror_script.py` comprueba el intercambio por stdin de `pc-connect`, la reanudación del arranque tras actualizar MFA y la conservación de la suscripción existente. Para ensayar `pc-connect` de extremo a extremo usa una base, una configuración y llaves SSH de prueba en una copia aislada del paquete.
- `test_docker_project.py` comprueba que el arranque del espejo indique de dónde llegan las cuentas y omita los pasos de aprovisionamiento de usuarios.
- `test_deployment_security.py` comprueba las guardas del archivo privado y del paquete de producción, y que el paquete del servidor deje fuera lanzadores, pruebas, firmware y documentación de desarrollo. Con Compose verifica los puertos y controles de escritura del perfil espejo sin iniciar servicios. Con `GEOCATTLE_QA_NGINX_IMAGE` apuntando a una imagen local de Nginx con curl y la web compilada, verifica las cabeceras y el límite del cuerpo en un contenedor sin red.
- `test_compartir_base.py` comprueba el SHA-256 y la compatibilidad del registro de migraciones con el código local usando archivos ficticios.
- `test_lora_json.py` comprueba la trama JSON V5 de la T3 con sensores ausentes y estados de batería desconocidos. `test_lora_usb.py` conserva la comprobación de presencia para el voltaje de CSV V4.
- `test_mqtt_ingestion.py` requiere un broker local con autenticación y una API de simulación de QA. La lectura encolada precede a la lectura reciente y pertenece a la asignación vigente del bovino ficticio.
- Antes de ejecutar pruebas de humo o preparar usuarios, verifica a qué instancia apuntan. Conserva el origen y el alcance de las evidencias archivadas.
- `docker_portability.py` comprueba ambos mapas locales en Nginx. Cuando están instalados, valida los manifiestos, el formato WebP o PNG, las cabeceras de caché y las de seguridad. Comprueba también el 404 de los recursos ausentes.
- `smoke_api.py` comprueba que retirar un collar vinculado devuelve 409 y que se puede retirar después de cerrar su asignación.
- `benchmark_capture.py` genera JSON V5 y bus_v1 con collares ficticios y mide consultas e ingesta por HTTP. `smoke_capture_recovery.py` levanta y detiene su propia API para comprobar la recuperación de la cola SQLite. Ambos requieren `psutil`, un PostgreSQL dedicado `geocattle_qa_*` y loopback.
- `smoke_capture_http.py` comprueba los cuatro roles sobre HTTPS, detección, ciclo de vida, exportaciones, sesión y MFA. Con `--smtp` también verifica el envío del worker mediante un servidor SMTP de prueba en loopback. [Verificación](../docs/VERIFICACION.md#recorrido-http-carga-y-recuperación-en-qa)

## Verificación

Ejecuta desde la raíz los módulos pertinentes con `python -m unittest` en el entorno de [CI](../.github/workflows/validacion.yml). Para comprobaciones que usan base sigue [Verificación](../docs/VERIFICACION.md).
