# Firmware de GeoCattle

## Propósito y alcance

Los sketches del collar, receptoras y repetidores se preparan por placa. [Guía de firmware](README.md)

## Contratos locales

- El emisor emplea el mismo identificador de hasta 16 caracteres en USB y LoRa. Las unidades nuevas comparten el binario con alias vacío y obtienen su identidad de la eFuse del ESP32. Usa una compilación exclusiva para conservar un alias histórico.
- Mantén compatibles las tramas de radio y los mensajes seriales de captura al añadir comandos de identificación.

## Verificación

Compila el sketch de la placa modificada. Usa las pruebas de contrato de [QA](../qa/AGENTS.md) para validación sin placas.
