# Firmware de GeoCattle

Abre el archivo `.ino` desde su carpeta en Arduino IDE. Cada carpeta incluye los archivos que necesita su sketch.

| Carpeta | Placa | Función |
|---|---|---|
| `GeoCattle_Emisor_45s` | LILYGO T-Beam ESP32 con AXP2101 y SX1276 | Collar con GPS, temperatura y movimiento. Envía JSON V5. |
| `GeoCattle_Receptor_JSON_45s` | LILYGO T3 V1.6.1, ESP32 Dev Module | Receptora del modo Directo. |
| `GeoCattle_Gateway_1` | Seeed XIAO ESP32S3 con Wio-SX1262 B2B | Repetidor 1. |
| `GeoCattle_Gateway_2` | Seeed XIAO ESP32S3 con Wio-SX1262 B2B | Repetidor 2. |
| `GeoCattle_Base_T3` | LILYGO T3 V1.6.1, ESP32 Dev Module | Base USB del modo Gateways. |

Instala el apoyo de placas ESP32 para Arduino. El collar usa ArduinoJson, LoRa, OneWire, DallasTemperature, TinyGPSPlus, Adafruit GFX, Adafruit SSD1306 y XPowersLib. La receptora directa usa ArduinoJson, LoRa, Adafruit GFX y Adafruit SSD1306. Los repetidores y la base usan ArduinoJson y RadioLib. Para los XIAO selecciona `XIAO_ESP32S3` con USB CDC On Boot habilitado.

El prototipo usa LoRa P2P en 915,5 MHz, SF7, BW125 y CR4/5. Para usar el modo Gateways, conecta solamente la T3 base al capturador USB. Para el modo Directo, conecta la T3 con su sketch correspondiente. Usa el selector de `Iniciar-Captura.cmd` para elegir. Ver [el contrato de integración](../docs/CONTRATO_API.md) y [el arranque](../README.md#desarrollo-local-en-el-puerto-8084).

## Identidad y alta por USB

1. Abre `GeoCattle_Emisor_45s.ino` en Arduino IDE, selecciona **ESP32 Dev Module** y conserva `GEOCATTLE_LEGACY_COLLAR_ID` vacío. Usa **Programa → Exportar binarios compilados** para guardar la compilación común.
2. Carga esa misma compilación en cada T-Beam. Desde Arduino CLI, ejecuta `arduino-cli upload --fqbn esp32:esp32:esp32 --port COMx --input-dir RUTA_BINARIOS` y cambia `COMx` por el puerto de cada unidad. Al arrancar, el ESP32 genera `GC-<12 dígitos hexadecimales>` usando su MAC de fábrica en eFuse. El identificador estable de 15 caracteres cabe en JSON V5 y en los repetidores.
3. Consulta el identificador en la pantalla del collar o envía `GEOCATTLE_IDENTIFY_V1` seguido de salto de línea por USB a 115200 baudios. El descriptor JSON `geocattle_collar` versión 1 entrega `hardware_id`, `transport` e `interval_seconds`. El campo `id` de la trama LoRa lleva el mismo identificador. Incorpora el dispositivo desde el predio correspondiente. [Alta por USB o LoRa](../docs/DESARROLLO_LOCAL.md#incorporar-un-collar-por-usb-o-lora)

Si necesitas conservar el registro histórico `REAL01`, prepara una compilación exclusiva para esa unidad. En Arduino IDE puedes agregar `#define GEOCATTLE_LEGACY_COLLAR_ID "REAL01"` antes del bloque `#ifndef GEOCATTLE_LEGACY_COLLAR_ID`. Conserva el binario común con el alias vacío para todas las unidades nuevas.
