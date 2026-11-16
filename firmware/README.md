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

El prototipo usa LoRa P2P en 915,5 MHz, SF7, BW125 y CR4/5. Para usar el modo Gateways, conecta solamente la T3 base al capturador USB. Para el modo Directo, conecta la T3 con su sketch correspondiente. Usa el selector de `Iniciar-Captura.cmd` para elegir. Ver [el contrato de integración](../docs/CONTRATO_API.md) y [el arranque](../README.md#cómo-levantar-geocattle).
