# Firmware de GeoCattle

## Propósito y alcance

Los sketches del collar, receptoras y repetidores se preparan por placa. [Guía de firmware](README.md)

## Contratos locales

- `GeoCattle_Emisor_45s` usa el perfil T-Beam AXP2101 por defecto y selecciona la T3 V1.6.1 SX1276 con `GEOCATTLE_BOARD_T3_V161`. La T3 comparte I2C entre la OLED y el ADXL345 y usa GPS NMEA externo opcional en modo recepción. Consulta el pinout y los comandos de compilación. [Guía de firmware](README.md)
- Los dos perfiles conservan JSON V5, el intervalo de 45 s y la identificación USB `GEOCATTLE_IDENTIFY_V1`. El emisor emplea el mismo identificador de hasta 16 caracteres en USB y LoRa. Las unidades nuevas del mismo perfil comparten el binario con alias vacío y obtienen su identidad de la eFuse del ESP32. Usa una compilación exclusiva para conservar un alias histórico.
- En la T3 el voltaje y el porcentaje provienen del ADC. Presencia de batería, carga y USB se transmiten como desconocidos (`-1`). GPS y sensores ausentes conservan sus valores nulos y los bits de diagnóstico de JSON V5.
- `GeoCattle_Gateway` es el único sketch de repetidor. Obtiene `gateway_eui` de la eFuse y guarda el nodo 1 o 2 en NVS mediante `GEOCATTLE_SET_NODE_V1 <eui> <nodo>`, que exige el EUI propio. Sin nodo no participa en la malla. bus_v1 limita la red a dos repetidores; ampliarla requiere cambiar la máscara de ruta y `validHeader` de forma coordinada con adapters y backend.
- Los sketches de red (gateway y base T3) requieren RadioLib 7.8.1; RadioLib 8.0 no compila su API.
- Mantén compatibles las tramas de radio y los mensajes seriales de captura al añadir comandos de identificación.

## Verificación

Para cambios del emisor, compila ambos perfiles con `esp32:esp32:esp32`. Para los demás sketches, compila el perfil de la placa modificada: gateway con `esp32:esp32:XIAO_ESP32S3` y base T3 con `esp32:esp32:esp32`, ambos con RadioLib 7.8.1. Usa las pruebas de contrato de [QA](../qa/AGENTS.md) para validación sin placas.
