/*
  GEOCATTLE - RECEPTOR LILYGO T3 V1.6.1
  ESP32 + SX1276 + OLED integrada

  RADIO INTERNA:
    SCK:   GPIO5
    MISO:  GPIO19
    MOSI:  GPIO27
    CS:    GPIO18
    RESET: GPIO23
    DIO0:  GPIO26

  OLED:
    SDA: GPIO21
    SCL: GPIO22

  CONFIGURACION LORA:
    915.5 MHz
    SF7
    BW125 kHz
    CR4/5
    Sync word 0x12
    CRC activado

  Recibe JSON V5 del collar.

  Salida USB para GeoCattle:
    {
      "packet": { JSON original del collar },
      "radio": {
        "rssi_dbm": -50,
        "snr_db": 9.5
      }
    }

  La bateria mostrada corresponde al collar emisor.

  La pantalla muestra el ultimo paquete recibido.
  El almacenamiento historico lo realiza GeoCattle.

  El receptor continua funcionando si no detecta OLED.
*/

#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <LoRa.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============================================================
// CONFIGURACION
// ============================================================

const long FRECUENCIA = 915500000L;

constexpr bool PANTALLA_ACTIVA = true;

constexpr uint32_t PERIODO_PANTALLA_MS = 1000;
constexpr uint32_t DURACION_PAGINA_MS = 5000;

const int OLED_SDA = 21;
const int OLED_SCL = 22;

const int LORA_SCK = 5;
const int LORA_MISO = 19;
const int LORA_MOSI = 27;
const int LORA_CS = 18;
const int LORA_RST = 23;
const int LORA_DIO0 = 26;

// ============================================================
// OBJETOS Y ESTADO
// ============================================================

Adafruit_SSD1306 pantalla(
  128, 64, &Wire, -1, 100000, 100000
);

JsonDocument ultimoPaquete;

bool pantallaOK = false;
bool hayDatos = false;

uint32_t totalRecibidos = 0;
uint32_t paquetesInvalidos = 0;

uint32_t ultimaRecepcion = 0;
uint32_t ultimaPantalla = 0;

int ultimoRSSI = 0;
float ultimoSNR = 0;

// ============================================================
// FUNCIONES GENERALES
// ============================================================

String numero(
  JsonVariantConst dato,
  unsigned int decimales = 2
) {
  if (dato.isNull()) {
    return "--";
  }

  return String(dato.as<double>(), decimales);
}

String textoMovimiento() {
  int flags = ultimoPaquete["f"].as<int>();

  if (flags & 4) {
    return "SIN ACELEROMETRO";
  }

  int estado = ultimoPaquete["m"][0].as<int>();

  if (estado == 1) {
    return "EN MOVIMIENTO";
  }

  if (estado == 0) {
    return "EN REPOSO";
  }

  return "CLASIFICANDO";
}

String motivoEnvio() {
  int motivo = ultimoPaquete["e"].as<int>();

  if (motivo == 0) {
    return "Envio: arranque";
  }

  if (motivo == 2) {
    return "Envio: inicio mov.";
  }

  return "Envio: periodico";
}

bool paqueteTienePosicion() {
  return
    !ultimoPaquete["g"][0].isNull() &&
    !ultimoPaquete["g"][1].isNull();
}

void linea(uint8_t fila, const String& texto) {
  if (!pantallaOK || !PANTALLA_ACTIVA) {
    return;
  }

  pantalla.setCursor(0, 12 + fila * 10);
  pantalla.print(texto.substring(0, 21));
}

// ============================================================
// PANTALLA
// ============================================================

void iniciarPantalla() {
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(100000);
  Wire.setTimeOut(50);

  for (uint8_t direccion = 0x3C;
       direccion <= 0x3D;
       direccion++) {

    Wire.beginTransmission(direccion);

    if (Wire.endTransmission() != 0) {
      continue;
    }

    pantallaOK = pantalla.begin(
      SSD1306_SWITCHCAPVCC,
      direccion,
      false,
      false
    );

    if (pantallaOK) {
      Serial.printf(
        "# OLED detectada: 0x%02X\n",
        direccion
      );

      break;
    }
  }

  if (!pantallaOK) {
    Serial.println(
      "# OLED no detectada. Recepcion USB continua."
    );

    return;
  }

  pantalla.setTextSize(1);
  pantalla.setTextColor(SSD1306_WHITE);
  pantalla.setTextWrap(false);

  if (!PANTALLA_ACTIVA) {
    pantalla.ssd1306_command(SSD1306_DISPLAYOFF);
    return;
  }

  pantalla.ssd1306_command(SSD1306_DISPLAYON);

  pantalla.clearDisplay();
  pantalla.setCursor(0, 0);
  pantalla.println("GEOCATTLE RECEPTOR");
  pantalla.println();
  pantalla.println("T3 V1.6.1 SX1276");
  pantalla.println("JSON V5");
  pantalla.display();
}

void mostrarErrorRadio() {
  Serial.println("# ERROR: radio SX1276 no detectada.");

  if (pantallaOK && PANTALLA_ACTIVA) {
    pantalla.clearDisplay();
    pantalla.setCursor(0, 0);

    pantalla.println("ERROR RADIO");
    pantalla.println();
    pantalla.println("Revisar placa:");
    pantalla.println("T3 V1.6.1 SX1276");

    pantalla.display();
  }

  while (true) {
    delay(1000);
  }
}

// ============================================================
// RADIO
// ============================================================

void iniciarRadio() {
  SPI.begin(
    LORA_SCK,
    LORA_MISO,
    LORA_MOSI,
    LORA_CS
  );

  LoRa.setPins(
    LORA_CS,
    LORA_RST,
    LORA_DIO0
  );

  if (!LoRa.begin(FRECUENCIA)) {
    mostrarErrorRadio();
  }

  LoRa.setSpreadingFactor(7);
  LoRa.setSignalBandwidth(125000);
  LoRa.setCodingRate4(5);
  LoRa.setPreambleLength(8);
  LoRa.setSyncWord(0x12);
  LoRa.enableCrc();

  LoRa.receive();

  Serial.println("# RADIO SX1276 OK");
  Serial.println("# 915.5MHz / SF7 / BW125 / CR4/5");
  Serial.println("# Esperando JSON V5 del collar.");
}

// ============================================================
// VALIDACION ESTRUCTURAL DEL JSON
// ============================================================

bool estructuraValida(JsonDocument& paquete) {
  if (!paquete.is<JsonObject>()) {
    return false;
  }

  if (
    !paquete["v"].is<int>() ||
    paquete["v"].as<int>() != 5
  ) {
    return false;
  }

  if (
    !paquete["id"].is<const char*>() ||
    !paquete["s"].is<const char*>()
  ) {
    return false;
  }

  const char* id = paquete["id"].as<const char*>();
  const char* sesion = paquete["s"].as<const char*>();

  if (
    strlen(id) == 0 ||
    strlen(id) > 16 ||
    strlen(sesion) != 16
  ) {
    return false;
  }

  if (
    !paquete["q"].is<uint32_t>() ||
    !paquete["u"].is<uint32_t>()
  ) {
    return false;
  }

  if (
    !paquete["g"].is<JsonArray>() ||
    paquete["g"].size() != 5
  ) {
    return false;
  }

  if (
    !paquete["a"].is<JsonArray>() ||
    paquete["a"].size() != 3
  ) {
    return false;
  }

  if (
    !paquete["m"].is<JsonArray>() ||
    paquete["m"].size() != 2
  ) {
    return false;
  }

  if (
    !paquete["b"].is<JsonArray>() ||
    paquete["b"].size() != 5
  ) {
    return false;
  }

  if (
    !paquete["p"].is<uint32_t>() ||
    !paquete["f"].is<int>() ||
    !paquete["e"].is<int>()
  ) {
    return false;
  }

  uint32_t periodo = paquete["p"].as<uint32_t>();
  int movimiento = paquete["m"][0].as<int>();
  int motivo = paquete["e"].as<int>();

  if (periodo < 30000 || periodo > 45000) {
    return false;
  }

  if (movimiento < -1 || movimiento > 1) {
    return false;
  }

  if (motivo < 0 || motivo > 2) {
    return false;
  }

  // La validacion completa de rangos y coherencia
  // tambien se realiza en el capturador de GeoCattle.
  return true;
}

// ============================================================
// RECEPCION Y ENVIO AL PC
// ============================================================

void recibirPaquete() {
  int longitudAnunciada = LoRa.parsePacket();

  if (longitudAnunciada <= 0) {
    return;
  }

  char buffer[256];
  size_t recibidos = 0;

  while (LoRa.available()) {
    char c = (char)LoRa.read();

    if (recibidos < sizeof(buffer) - 1) {
      buffer[recibidos++] = c;
    }
  }

  buffer[recibidos] = '\0';

  int rssi = LoRa.packetRssi();
  float snr = LoRa.packetSnr();

  if (
    longitudAnunciada > 255 ||
    recibidos != (size_t)longitudAnunciada
  ) {
    paquetesInvalidos++;

    Serial.println(
      "# Paquete descartado: longitud incorrecta."
    );

    LoRa.receive();
    return;
  }

  JsonDocument paquete;

  DeserializationError error = deserializeJson(
    paquete,
    buffer,
    recibidos
  );

  if (error) {
    paquetesInvalidos++;

    Serial.print("# JSON invalido: ");
    Serial.println(error.c_str());

    LoRa.receive();
    return;
  }

  if (!estructuraValida(paquete)) {
    paquetesInvalidos++;

    Serial.println(
      "# Paquete descartado: estructura o version."
    );

    LoRa.receive();
    return;
  }

  /*
    Se conserva el JSON original dentro de "packet".

    RSSI y SNR son medidas del receptor.
    Se agregan al sobre USB, fuera del paquete original.
  */

  JsonDocument sobre;

  sobre["packet"] = paquete;
  sobre["radio"]["rssi_dbm"] = rssi;
  sobre["radio"]["snr_db"] = snr;

  if (sobre.overflowed()) {
    paquetesInvalidos++;

    Serial.println(
      "# Error de memoria al preparar salida USB."
    );

    LoRa.receive();
    return;
  }

  // Una linea JSON completa por paquete.
  // Este formato es compatible con GeoCattle.
  serializeJson(sobre, Serial);
  Serial.println();

  ultimoPaquete = paquete;

  ultimoRSSI = rssi;
  ultimoSNR = snr;

  totalRecibidos++;
  ultimaRecepcion = millis();
  hayDatos = true;

  LoRa.receive();
}

// ============================================================
// VISUALIZACION
// ============================================================

void mostrarPantalla(uint32_t ahora) {
  if (!pantallaOK || !PANTALLA_ACTIVA) {
    return;
  }

  if (
    ahora - ultimaPantalla <
      PERIODO_PANTALLA_MS
  ) {
    return;
  }

  ultimaPantalla = ahora;

  pantalla.clearDisplay();
  pantalla.setCursor(0, 0);

  if (!hayDatos) {
    pantalla.println("GEOCATTLE RECEPTOR");

    linea(0, "Esperando collar...");
    linea(1, "915.5MHz SF7 BW125");
    linea(2, "USB: 115200 baudios");

    linea(
      3,
      "Invalidos: " + String(paquetesInvalidos)
    );

    linea(4, "Formato: JSON V5");

    pantalla.display();
    return;
  }

  String id = ultimoPaquete["id"].as<String>();
  uint32_t secuencia = ultimoPaquete["q"].as<uint32_t>();

  String titulo =
    id + " #" + String(secuencia);

  pantalla.print(titulo.substring(0, 21));

  uint8_t pagina =
    (ahora / DURACION_PAGINA_MS) % 4;

  if (pagina == 0) {
    // Temperatura y clasificacion de movimiento.

    linea(
      0,
      "T: " + numero(ultimoPaquete["t"], 2) + " C"
    );

    linea(1, textoMovimiento());

    linea(
      2,
      "RMS: " +
      numero(ultimoPaquete["m"][1], 3) +
      " g"
    );

    linea(3, motivoEnvio());

  } else if (pagina == 1) {
    // Posicion contenida en el ultimo paquete.

    linea(
      0,
      paqueteTienePosicion()
        ? "GPS TX: FIX VALIDO"
        : "GPS TX: SIN FIX"
    );

    linea(
      1,
      "Lat: " + numero(ultimoPaquete["g"][0], 6)
    );

    linea(
      2,
      "Lon: " + numero(ultimoPaquete["g"][1], 6)
    );

    int usados = ultimoPaquete["g"][3].as<int>();

    linea(
      3,
      "Usa:" + String(usados) +
      " HDOP:" + numero(ultimoPaquete["g"][4], 1)
    );

  } else if (pagina == 2) {
    // Bateria del collar emisor.

    int mv = ultimoPaquete["b"][0].as<int>();
    int porcentaje = ultimoPaquete["b"][1].as<int>();
    int presente = ultimoPaquete["b"][2].as<int>();
    int cargando = ultimoPaquete["b"][3].as<int>();
    int usb = ultimoPaquete["b"][4].as<int>();

    if (presente == 0) {
      linea(0, "Collar: sin bateria");
      linea(1, "Voltaje: --");

    } else if (mv >= 0) {
      linea(
        0,
        "Bateria: " + String(mv) + " mV"
      );

      linea(
        1,
        porcentaje >= 0
          ? "Carga estimada: ~" +
            String(porcentaje) + "%"
          : "Carga estimada: --"
      );

    } else {
      linea(0, "Bateria: sin lectura");
      linea(1, "Carga estimada: --");
    }

    linea(
      2,
      usb == 1
        ? "USB en collar: SI"
        : usb == 0
          ? "USB en collar: NO"
          : "USB en collar: --"
    );

    linea(
      3,
      cargando == 1
        ? "Estado: cargando"
        : cargando == 0
          ? "Estado: no cargando"
          : "Estado carga: --"
    );

  } else {
    // Aceleracion y calidad del enlace.

    linea(
      0,
      "X: " + numero(ultimoPaquete["a"][0], 3) + " g"
    );

    linea(
      1,
      "Y: " + numero(ultimoPaquete["a"][1], 3) + " g"
    );

    linea(
      2,
      "Z: " + numero(ultimoPaquete["a"][2], 3) + " g"
    );

    linea(
      3,
      "RSSI:" + String(ultimoRSSI) +
      " SNR:" + String(ultimoSNR, 1)
    );
  }

  linea(
    4,
    "RX hace " +
    String((ahora - ultimaRecepcion) / 1000UL) +
    "s / Total:" + String(totalRecibidos)
  );

  pantalla.display();
}

// ============================================================
// INICIO
// ============================================================

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println();
  Serial.println("# GEOCATTLE RECEPTOR T3 V1.6.1");
  Serial.println("# Protocolo JSON V5");
  Serial.println("# OLED SDA21 / SCL22");
  Serial.println("# Bateria mostrada: collar emisor");

  iniciarPantalla();
  iniciarRadio();

  Serial.println("# Receptor listo.");
}

// ============================================================
// BUCLE PRINCIPAL
// ============================================================

void loop() {
  recibirPaquete();
  mostrarPantalla(millis());

  delay(2);
}