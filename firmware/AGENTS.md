# Firmware de GeoCattle

## Propósito y alcance

Los sketches del collar, receptoras y repetidores se preparan por placa. [Guía de firmware](README.md)

## Contratos locales

- El emisor emplea el mismo identificador en la respuesta de alta USB y en la telemetría LoRa. Las unidades nuevas usan la identidad del ESP32. Conserva el identificador histórico en la unidad que ya lo tiene registrado.
- Mantén compatibles las tramas de radio y los mensajes seriales de captura al añadir comandos de identificación.

## Verificación

Compila el sketch de la placa modificada. Usa las pruebas de contrato de [QA](../qa/AGENTS.md) para validación sin placas.
