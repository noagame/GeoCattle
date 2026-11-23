# Adaptadores de captura

## Propósito y alcance

`serial_receiver.py` maneja el descubrimiento USB. `receiver_profiles.py` y `lora_bus.py` cubren selección y decodificación para gateways. `lora_usb.py` integra el lector, el archivo local y la entrega HTTP. `lora_json.py` y `academic_bridge.py` cubren formatos y entregas compatibles.

## Contratos locales

- Para cambiar un formato, revisa el [contrato de API](../docs/CONTRATO_API.md), las [instrucciones de captura](../docs/USB_COM5.md) y los consumidores en [backend](../backend/geocattle/AGENTS.md). Conserva la compatibilidad de lecturas previas y evita depender de un número COM fijo.
- JSON V5 admite voltaje y porcentaje estimado cuando la presencia de batería es desconocida (`-1`), como ocurre con el ADC del perfil T3. La API conserva los estados desconocidos como `null`. CSV V4 exige presencia confirmada para transmitir voltaje y porcentaje.
- Distingue recepción, persistencia local y entrega confirmada. Conserva el bloqueo del capturador, la identidad de mensajes y las lecturas pendientes al reintentar o reiniciar.
- La API de captura confirma detecciones con `status:"candidate"` y un ID persistido. Completa la entrega durable con ese recibo. Envía `X-Farm-ID` cuando la configuración privada fija `INGEST_FARM_ID`.

## Verificación

Ejecuta el bloque `captura_contratos` de [CI](../.github/workflows/validacion.yml), incluidas las extensiones presentes en la rama. Usa fixtures seriales y HTTP para las comprobaciones sin placas.
