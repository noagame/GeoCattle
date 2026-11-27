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
- `GeoCattle_Nube_T3` no transmite mientras oye balizas vigentes de otra raíz; tras 25 s sin ellas actúa como raíz de respaldo (balizas de nodo 0 y ACK bus_v1 con los estados de la base, solo a lotes con destino 0) y vuelve a callar al oír otra raíz; `GC_ROOT_FALLBACK 0` la deja pasiva. Guarda los collares JSON V5 que oye directo (origen 0, como la base) y los lotes Data de gateways con las validaciones de la base, deduplica por collar/sesión/secuencia entre ambos caminos y entrega por HTTPS a `receiver-batch`. Guarda hasta 4096 lecturas en LittleFS bajo `/cola/`, en archivos de 13 registros (un bloque de 4 KB; nunca un archivo grande con escrituras aleatorias, porque LittleFS reescribe hasta el final y se queda sin espacio), con hasta el 70 % de los bloques; acepta `http://` solo hacia IP privadas para pruebas locales, reemplaza las más antiguas al llenarse y descarta solo rechazos 422/409. Su `config.h` con WiFi y claves queda fuera de Git; `config.example.h` documenta los campos. No imprime sobres `gc_bus` por USB. [T3 nube](README.md#t3-nube-por-wifi)
- La T3 base mantiene bus_v1 y los ACK USB. Copia las lecturas de gateways a una cola sin espera para LittleFS, y entrega por HTTPS desde otra tarea. Conserva los 256 registros más recientes y confirma solo IDs persistidos. El aprovisionamiento USB verifica el EUI y guarda hasta tres redes y las credenciales en NVS. [Base T3](README.md#base-t3-con-wifi-y-usb)

## Verificación

Para cambios del emisor, compila ambos perfiles con `esp32:esp32:esp32`. Para los demás sketches, compila el gateway con `esp32:esp32:XIAO_ESP32S3` y la base T3 y la T3 nube con `esp32:esp32:esp32:PartitionScheme=no_ota`, ambos con RadioLib 7.8.1. Para la base usa Arduino-ESP32 3.x y ArduinoJson 7, verifica el tamaño del binario y conserva la partición de LittleFS descrita en la [guía](README.md#base-t3-con-wifi-y-usb). Usa las pruebas de contrato de [QA](../qa/AGENTS.md) y sigue la [verificación con placas](README.md#verificación-en-terreno).
