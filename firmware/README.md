# Firmware de GeoCattle

Abre el archivo `.ino` desde su carpeta en Arduino IDE. Cada carpeta incluye los archivos que necesita su sketch.

| Carpeta | Placa | Función |
|---|---|---|
| `GeoCattle_Emisor_45s` | LILYGO T-Beam ESP32 con AXP2101 y SX1276 o LILYGO T3 V1.6.1 con SX1276 | Collar con perfiles de placa. Envía JSON V5 cada 45 s. |
| `GeoCattle_Receptor_JSON_45s` | LILYGO T3 V1.6.1, ESP32 Dev Module | Receptora del modo Directo. |
| `GeoCattle_Gateway` | Seeed XIAO ESP32S3 con Wio-SX1262 B2B | Repetidor. Un mismo binario para todos los gateways; GeoCattle asigna el nodo por USB. |
| `GeoCattle_Base_T3` | LILYGO T3 V1.6.1, ESP32 Dev Module | Base USB del modo Gateways y salida HTTPS por WiFi. |
| `GeoCattle_Nube_T3` | LILYGO T3 V1.6.1 con OLED, ESP32 Dev Module | Receptora WiFi del modo Gateways: escucha la malla, hace de raíz de respaldo sin base, búfer en flash y entrega HTTPS. |

Instala el apoyo de placas ESP32 para Arduino. Ambos perfiles del collar usan ArduinoJson, LoRa, OneWire, DallasTemperature, TinyGPSPlus, Adafruit GFX y Adafruit SSD1306. El perfil T-Beam también requiere XPowersLib. La receptora directa usa ArduinoJson, LoRa, Adafruit GFX y Adafruit SSD1306. La T3 nube usa ArduinoJson, RadioLib 7.8.1, Adafruit GFX y Adafruit SSD1306. Los repetidores y la base usan ArduinoJson y **RadioLib 7.8.1**. RadioLib 8.0 cambió su API y no compila estos sketches: en Arduino IDE instala la versión 7.8.1 desde el Gestor de bibliotecas. Para los XIAO selecciona `XIAO_ESP32S3` con USB CDC On Boot habilitado.

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

## T3 nube por WiFi

`GeoCattle_Nube_T3` convierte una segunda T3 en receptora de producción sin cambiar la base USB. Escucha bus_v1 en 915,5 MHz. Guarda los collares que oye directo (origen 0, igual que la base) y reensambla los lotes de datos de los gateways con las mismas validaciones de la base. Si la misma lectura llega directa y por un gateway, la guarda una vez (collar, sesión y secuencia). Los gateways solo reenvían si oyen balizas de una raíz. Con la base encendida, la T3 nube no transmite. Si pasa 25 s sin oír balizas vigentes de otra raíz (de la base o de un gateway que la sigue), actúa como raíz de respaldo: emite balizas cada 5 s como nodo 0 y responde con ACK los lotes dirigidos al nodo 0, con los estados de la base (0 aceptado, 1 sin espacio, 3 inválido). El ACK confirma la custodia en su cola local, igual que en la base. Al oír otra raíz vuelve a escuchar en silencio. `GC_ROOT_FALLBACK 0` en `config.h` la deja siempre pasiva. Si la base queda fuera del alcance de la T3 nube pero al alcance de los gateways, las dos raíces se alternarían; en ese caso usa `GC_ROOT_FALLBACK 0`.

1. Copia `config.example.h` como `config.h` en la carpeta del sketch y completa hasta tres redes WiFi, el origen HTTPS, la `INGEST_KEY` de `.env.pilot`, el UUID del predio de producción que imprime bootstrap y, si usas Access, el service token. `config.h` queda fuera de Git.
2. En Arduino IDE selecciona **ESP32 Dev Module** y **Partition Scheme → No OTA (2MB APP/2MB SPIFFS)**. La aplicación ocupa unos 1,32 MB y no cabe en el esquema por defecto de 1,25 MB.

```bash
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=no_ota --output-dir .runtime/firmware/nube firmware/GeoCattle_Nube_T3
arduino-cli upload --fqbn esp32:esp32:esp32:PartitionScheme=no_ota --port COMx --input-dir .runtime/firmware/nube firmware/GeoCattle_Nube_T3
```

La primera vez formatea LittleFS y crea la cola en `/cola/`, repartida en archivos de 13 lecturas (un bloque de 4 KB cada uno). LittleFS reescribe un archivo desde el punto que cambia, así que cada escritura o confirmación reescribe solo ese bloque y el desgaste se reparte. Usa hasta el 70 % de los bloques, con tope de 4096 lecturas (unas 51 h de un collar cada 45 s); el resto queda libre para esas copias. La preparación inicial tarda cerca de 40 s; las lecturas de ese lapso esperan en RAM. Cada lectura lleva CRC y cada archivo se cierra tras escribirla. Si encuentra el `/cola.bin` de una versión anterior, lo borra. Al llenarse reemplaza la más antigua. Sale de la cola cuando la API devuelve su ID. Los rechazos permanentes 422 y 409 se descartan y cuentan como rechazados. Las lecturas con 403, como las de un collar aún no aprobado, quedan para reintento. La hora llega por NTP. La placa no entrega hasta sincronizarla. Las lecturas capturadas antes en el mismo arranque se reconstruyen con el uptime, y las de un arranque anterior sin hora se marcan `recovery`. TLS valida el servidor con el paquete de raíces de Mozilla del core, así un cambio de CA de Cloudflare no requiere reprogramar. Para probar contra un PC de la misma red WiFi, `GC_API_URL` admite `http://` solo hacia una IP privada (10/8, 172.16/12 o 192.168/16), con el servidor en producción publicado en ese puerto.

| Línea de la OLED | Contenido |
|---|---|
| 2 y 3 | Estado WiFi con RSSI y red conectada o en prueba. |
| 4 | Nube: `OK hace Ns`, `ERROR HTTP` con su código, sin respuesta, esperando hora o falta de configuración. |
| 5 | Ocupación de la cola en flash; `LLENA` si reemplaza lecturas. |
| 6 | Lecturas capturadas y entregadas desde el arranque. |
| 7 | Último collar, gateway de origen (`G1`, `G2`) o `Dir` si llegó directo, y antigüedad. |
| 8 | Última trama oída de la base (`B`), o `R` si esta T3 actúa como raíz, y de cada gateway. |

El monitor serie a 115200 imprime `# lectura ...` por cada lectura nueva y un resumen `# nube ...` cada 10 s, con `raiz=`, balizas y ACK enviados. No emite sobres `gc_bus`, para que el capturador del PC no la confunda con la base. Una T-Beam tiene la misma flash de 4 MB y no amplía la cola. Para más capacidad, la ranura microSD de la T3 V1.6.1 podría alojarla en una versión futura.

## Base T3 con WiFi y USB

Compila con Arduino-ESP32 3.x, RadioLib 7.8.1 y ArduinoJson 7. Selecciona **No OTA (2MB APP/2MB SPIFFS)**. En Arduino-ESP32 3.3.13 el límite de la aplicación es 2 097 152 bytes y LittleFS monta la partición `spiffs` de 1 966 080 bytes. La actualización del esquema de particiones en una placa existente puede requerir respaldar o agotar el búfer previamente.

```bash
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=no_ota --output-dir .runtime/firmware/base firmware/GeoCattle_Base_T3
arduino-cli upload --fqbn esp32:esp32:esp32:PartitionScheme=no_ota --port COMx --input-dir .runtime/firmware/base firmware/GeoCattle_Base_T3
```

Conecta la T3 al PC y pausa momentáneamente el capturador para liberar el puerto. Ejecuta el aprovisionador con un Python que ya tenga los requisitos de `adapters`. Usa el EUI que devuelve el primer comando y sustituye `CA.pem` por la raíz PEM de confianza de la cadena TLS del dominio público. Proporciona una CA obtenida por un canal confiable y vuelve a provisionar si cambia la raíz. Las claves se leen en consola sin eco y se guardan en la NVS de la T3. Mantén acceso físico controlado a la placa.

```bash
python scripts/provision_base_t3.py --port COMx --status
python scripts/provision_base_t3.py --port COMx --eui EUI_DE_LA_T3 --ca-cert CA.pem --initialize-buffer
python scripts/provision_base_t3.py --port COMx --eui EUI_DE_LA_T3 --time-only
```

Usa `--initialize-buffer` en una placa nueva o cuando autorices formatear una partición que no monta. El firmware rota hasta tres redes cada 15 s mientras no logra conexión. NTP sincroniza la hora por internet. `--time-only` la fija por USB durante una visita offline. Si faltaba hora al capturar, la T3 reconstruye la recepción usando uptime en el mismo arranque o una calibración guardada. Si hubo un reinicio sin calibración, usa la hora de recuperación como aproximación y la API marca esa calidad.

La radio permanece en el bucle del Arduino con watchdog. La escritura LittleFS y la conexión TLS se ejecutan en tareas separadas del otro núcleo. El búfer guarda 256 lecturas con CRC y reemplazo atómico del archivo más antiguo al llenarse. Una lectura sale del búfer después del recibo de la API con su ID persistido. A 45 s llegan 1920 lecturas por collar al día. La capacidad nominal equivale a 3 h 12 min para un collar, 1 h 36 min para dos y unos 19 min para diez. La pérdida de internet no interrumpe el USB. Guarda el registro completo en el PC conectado.

Los comandos `GEOCATTLE_SET_WIFI_V1`, `GEOCATTLE_SET_CLOUD_V1`, `GEOCATTLE_SET_TIME_V1`, `GEOCATTLE_CLOUD_STATUS_V1` y `GEOCATTLE_INIT_CLOUD_BUFFER_V1` requieren el EUI local. Devuelven JSON versionado con prefijo `#GC_CLOUD ` sin secretos. El capturador ignora esas respuestas. [Contrato HTTPS](../docs/CONTRATO_API.md#lotes-https-de-la-receptora-t3)

### Verificación en terreno

1. Con un collar y ambos XIAO activos, compara la identidad collar/sesión/secuencia en la API local y en la nube. Comprueba que llega vía gateway y que un fix ausente conserva las coordenadas nulas.
2. Deshabilita la primera red WiFi y verifica la conexión por una red secundaria. Corta internet y comprueba que los pendientes aumentan en la T3 y que el PC registra normalmente. Reinicia la placa sin internet y verifica el búfer.
3. Mantén el corte hasta superar 256 lecturas. Al reconectar, comprueba que la nube recibe las 256 más recientes y que el registro local contiene también las anteriores. Repite con un corte durante una escritura o confirmación.
4. Prueba NTP y hora USB. Verifica `base_clock` antes y después de un reinicio offline. Comprueba que una CA incorrecta impide la entrega y que Access rechaza un token inválido mientras USB sigue operativo.
