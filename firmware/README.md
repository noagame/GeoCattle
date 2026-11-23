# Firmware de GeoCattle

Abre el archivo `.ino` desde su carpeta en Arduino IDE. Cada carpeta incluye los archivos que necesita su sketch.

| Carpeta | Placa | Función |
|---|---|---|
| `GeoCattle_Emisor_45s` | LILYGO T-Beam ESP32 con AXP2101 y SX1276 o LILYGO T3 V1.6.1 con SX1276 | Collar con perfiles de placa. Envía JSON V5 cada 45 s. |
| `GeoCattle_Receptor_JSON_45s` | LILYGO T3 V1.6.1, ESP32 Dev Module | Receptora del modo Directo. |
| `GeoCattle_Gateway` | Seeed XIAO ESP32S3 con Wio-SX1262 B2B | Repetidor. Un mismo binario para todos los gateways; GeoCattle asigna el nodo por USB. |
| `GeoCattle_Base_T3` | LILYGO T3 V1.6.1, ESP32 Dev Module | Base USB del modo Gateways. |

Instala el apoyo de placas ESP32 para Arduino. Ambos perfiles del collar usan ArduinoJson, LoRa, OneWire, DallasTemperature, TinyGPSPlus, Adafruit GFX y Adafruit SSD1306. El perfil T-Beam también requiere XPowersLib. La receptora directa usa ArduinoJson, LoRa, Adafruit GFX y Adafruit SSD1306. Los repetidores y la base usan ArduinoJson y **RadioLib 7.8.1**. RadioLib 8.0 cambió su API y no compila estos sketches: en Arduino IDE instala la versión 7.8.1 desde el Gestor de bibliotecas. Para los XIAO selecciona `XIAO_ESP32S3` con USB CDC On Boot habilitado.

El prototipo usa LoRa P2P en 915,5 MHz, SF7, BW125 y CR4/5. Para usar el modo Gateways, conecta solamente la T3 base al capturador USB. Para el modo Directo, conecta la T3 con su sketch correspondiente. Usa el selector de `Iniciar-Captura.cmd` para elegir. Ver [el contrato de integración](../docs/CONTRATO_API.md) y [el arranque](../README.md#desarrollo-local-en-el-puerto-8084).

## Compilar el collar por perfil

En Arduino IDE abre `GeoCattle_Emisor_45s.ino` y selecciona **ESP32 Dev Module** para ambas placas. Deja comentado `#define GEOCATTLE_BOARD_T3_V161` para el T-Beam. Descomenta esa línea al principio del sketch para compilar la T3 y vuelve a comentarla al regresar al T-Beam. Usa **Programa → Exportar binarios compilados** si quieres guardar la compilación, o **Subir** para cargarla.

Con Arduino CLI deja comentado el selector en el sketch y ejecuta desde la raíz del repositorio los comandos del perfil correspondiente.

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32 --output-dir ".runtime/firmware/tbeam" firmware/GeoCattle_Emisor_45s
arduino-cli compile --fqbn esp32:esp32:esp32 --build-property "compiler.cpp.extra_flags=-DGEOCATTLE_BOARD_T3_V161" --output-dir ".runtime/firmware/t3" firmware/GeoCattle_Emisor_45s
```

Para cargar la T3, con la antena de 915 MHz conectada y la microSD retirada, reemplaza `COMx` por el puerto de esa unidad.

```powershell
arduino-cli upload --fqbn esp32:esp32:esp32 --port COMx --input-dir ".runtime/firmware/t3" firmware/GeoCattle_Emisor_45s
```

Una T3 con el sketch de collar deja de estar disponible como receptora directa. Usa otra placa con el sketch de receptora para el modo Directo. En el modo Gateways la captura USB usa otra T3 con el sketch de base.

## Conexiones para el collar T3 V1.6.1

| Elemento | Conexión |
|---|---|
| Radio SX1276 integrada | SCK GPIO5, MISO GPIO19, MOSI GPIO27, CS GPIO18, RST GPIO23, DIO0 GPIO26. GPIO33 y GPIO32 quedan reservados para DIO1 y DIO2. |
| OLED SSD1306 integrada | SDA GPIO21, SCL GPIO22, dirección 0x3C, sin GPIO de reset. |
| ADXL345 opcional | SDA GPIO21 y SCL GPIO22 en el mismo bus que la OLED. VCC a 3V3 y GND común. Dirección 0x53 o 0x1D. |
| DS18B20 opcional | DAT a GPIO4, VDD a 3V3 y GND común. Conecta una resistencia de 4,7 kΩ entre DAT y 3V3. |
| GPS ATGM336H opcional | VCC a 3V3, GND común y TX del módulo a GPIO34 (RX del ESP32, solo entrada). UART NMEA a 9600 baudios. Deja libre el RX del módulo. |
| Batería | Terminal de batería medido en GPIO35 mediante el divisor interno de 100 kΩ / 100 kΩ. |
| LED de usuario y microSD | LED en GPIO25. La microSD reserva CS GPIO13, SCK GPIO14, MOSI GPIO15 y MISO GPIO2. |

GPIO4 admite la línea bidireccional 1-Wire y está libre en esta placa. El pull-up deja intactos los pines de arranque y los del lector microSD. GPIO34 carece de pull-up interno. Puedes añadir una resistencia de 10 kΩ a 3V3 cerca de la T3 para mantener el nivel de reposo de RX si desconectas el GPS. El firmware acepta sentencias NMEA con prefijos `$GN`, `$GP` y `$BD`, y no envía comandos UBX. Si no llegan sentencias, el diagnóstico muestra `SIN DATOS UART`. Mientras no haya fix, las coordenadas son `null`. Los sensores ausentes mantienen sus mediciones nulas y activan sus bits de diagnóstico. [Guía oficial de LilyGO](https://github.com/Xinyuan-LilyGO/LilyGo-LoRa-Series/blob/master/docs/en/t3_v161_sx1276/t3_v161_sx1276_hw.md) · [Pinout](https://github.com/Xinyuan-LilyGO/LilyGo-LoRa-Series/blob/master/assets/image/lora32_v1.6.1_pinmap.jpg) · [Configuración del fabricante](https://github.com/Xinyuan-LilyGO/LilyGo-LoRa-Series/blob/master/examples/Factory/utilities.h)

La T3 promedia 16 muestras ADC y multiplica por dos la lectura en milivoltios. Envía voltaje y porcentaje estimado si el resultado está entre 2500 y 4350 mV. Fuera de ese rango, ambos se envían como `-1`. El cargador puede mantener el terminal cerca de 4,2 V con USB aunque el conector de batería esté vacío. Por eso `presente`, `cargando` y `USB` siempre valen `-1` en JSON V5. La pantalla identifica el perfil T3 y muestra la lectura ADC con la fuente como desconocida.

## Identidad y alta por USB

1. Compila el perfil correspondiente con `GEOCATTLE_LEGACY_COLLAR_ID` vacío. Las unidades de la misma placa pueden compartir esa compilación.
2. Carga la compilación en cada unidad de la placa correspondiente. Al arrancar, el ESP32 genera `GC-<12 dígitos hexadecimales>` usando su MAC de fábrica en eFuse. El identificador estable de 15 caracteres cabe en JSON V5 y en los repetidores.
3. Consulta el identificador en la pantalla del collar o envía `GEOCATTLE_IDENTIFY_V1` seguido de salto de línea por USB a 115200 baudios. El descriptor JSON `geocattle_collar` versión 1 entrega `hardware_id`, `transport` e `interval_seconds`. El campo `id` de la trama LoRa lleva el mismo identificador. Incorpora el dispositivo desde el predio correspondiente. [Alta por USB o LoRa](../docs/DESARROLLO_LOCAL.md#incorporar-un-collar-por-usb-o-lora)

Si necesitas conservar el registro histórico `REAL01`, prepara una compilación exclusiva para esa unidad. En Arduino IDE puedes agregar `#define GEOCATTLE_LEGACY_COLLAR_ID "REAL01"` antes del bloque `#ifndef GEOCATTLE_LEGACY_COLLAR_ID`. Conserva el binario común con el alias vacío para todas las unidades nuevas.

## Gateways con nodo asignado por GeoCattle

Todos los gateways usan el mismo sketch `GeoCattle_Gateway`. Cada placa deriva su `gateway_eui` de la eFuse del ESP32-S3 y guarda su número de nodo de radio en la memoria NVS. No hay que compilar una versión por gateway.

1. Compila y carga `GeoCattle_Gateway` con la placa **XIAO_ESP32S3** y **USB CDC On Boot** habilitado. Con Arduino CLI: `arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 firmware/GeoCattle_Gateway` y luego `arduino-cli upload` con el puerto de la placa.
2. Una placa sin nodo escucha la radio sin retransmitir y muestra en el monitor serie `# Gateway sin número de nodo: regístralo en GeoCattle por USB`. Así no choca con otro gateway.
3. Regístrala desde **Gateways instalados → Detectar gateway por USB** o con `Registrar-Gateway-USB.cmd`. GeoCattle reserva un nodo libre del predio y lo envía con `GEOCATTLE_SET_NODE_V1 <eui> <nodo>`. La placa solo acepta el comando con su propio EUI, guarda el nodo, responde y se reinicia. El alta termina cuando la placa confirma.

`GEOCATTLE_IDENTIFY_V1` responde `{"type":"geocattle_gateway","version":1,"gateway_eui":"…","node_id":1|2|null,"provisioned":…,"firmware":"…"}`. El protocolo bus_v1 admite dos repetidores (nodos 1 y 2), por lo que un predio puede vincular como máximo dos gateways. La base T3 (`GeoCattle_Base_T3`) sigue siendo el nodo 0 y no cambia.
