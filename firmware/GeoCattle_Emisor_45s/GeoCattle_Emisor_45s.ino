/*
  GEOCATTLE - EMISOR T-BEAM CLASICA
  ESP32 + AXP2101 + SX1276 + GPS u-blox integrado

  CONEXIONES ACTUALES:
    OLED SDA:   GPIO21
    OLED SCL:   GPIO22
    ADXL SDA:   GPIO25
    ADXL SCL:   GPIO14
    DS18 DAT:   GPIO13

  CONEXIONES INTERNAS:
    GPS RX ESP32: GPIO34 <- TX del GPS
    GPS TX ESP32: GPIO12 -> RX del GPS
    LoRa SCK/MISO/MOSI: 5/19/27
    LoRa CS/RST/DIO0:   18/23/26

  PROTOCOLO:
    JSON V5, compatible con el receptor preparado anteriormente.

  MOVIMIENTO:
    - Se resta la gravedad lenta.
    - Se calcula RMS de aceleracion dinamica.
    - Movimiento: >= 0.12 g durante 4 ventanas.
    - Reposo: <= 0.06 g durante 20 ventanas.
    - Cada ventana dura aproximadamente un segundo.
    - Sin sensor o antes de clasificar: desconocido.

  GPS:
    - Alimentacion continua durante el diagnostico.
    - UART a 9600, velocidad comprobada en esta placa.
    - Solicita mensajes GSV al u-blox para ver satelites y C/N0.
    - No realiza restauracion de fabrica.
    - No guarda configuraciones mediante CFG-CFG.

  TX OK confirma finalizacion local del envio.
  No confirma recepcion del paquete.
*/

#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <LoRa.h>
#include <ArduinoJson.h>

#include <OneWire.h>
#include <DallasTemperature.h>
#include <TinyGPSPlus.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include <esp_system.h>
#include <math.h>

#define XPOWERS_CHIP_AXP2101
#include <XPowersLib.h>

// ============================================================
// CONFIGURACION
// ============================================================

// Define GEOCATTLE_LEGACY_COLLAR_ID como "REAL01" al actualizar solo el collar histórico.
#ifndef GEOCATTLE_LEGACY_COLLAR_ID
#define GEOCATTLE_LEGACY_COLLAR_ID ""
#endif
// La red de repetidores y JSON V5 admiten hasta 16 caracteres.
char COLLAR_ID[sizeof("GC-FFFFFFFFFFFF")] = {};

const long FRECUENCIA = 915500000L;

// Pantalla activa para demostracion.
// Cambiar a false para apagarla.
constexpr bool PANTALLA_ACTIVA = true;

// Imprime GGA, RMC y GSV por el monitor serie.
// Mantener true mientras se diagnostica el GPS.
constexpr bool MOSTRAR_NMEA = true;

// Solicita GSV al GPS u-blox mediante el GPIO12 interno.
constexpr bool SOLICITAR_GSV = true;

// Umbrales iniciales. Ajustar con observacion real del animal.
constexpr float UMBRAL_MOVIMIENTO_G = 0.12f;
constexpr float UMBRAL_REPOSO_G = 0.06f;

constexpr uint8_t SEGUNDOS_CONFIRMAR_MOVIMIENTO = 4;
constexpr uint8_t SEGUNDOS_CONFIRMAR_REPOSO = 20;

constexpr uint32_t PERIODO_ACELEROMETRO_MS = 40;
constexpr uint32_t PERIODO_TEMPERATURA_MS = 5000;
constexpr uint32_t PERIODO_BATERIA_MS = 5000;
constexpr uint32_t PERIODO_PANTALLA_MS = 1000;

// Separacion minima de 45 segundos, tambien ante movimiento.
constexpr uint32_t MINIMO_ENTRE_ENVIOS_MS = 45000UL;

void inicializarIdentidadCollar() {
  constexpr char alias[] = GEOCATTLE_LEGACY_COLLAR_ID;
  static_assert(sizeof(alias) <= sizeof(COLLAR_ID), "Identificador histórico demasiado largo");
  if (alias[0]) {
    snprintf(COLLAR_ID, sizeof(COLLAR_ID), "%s", alias);
  } else {
    snprintf(COLLAR_ID, sizeof(COLLAR_ID), "GC-%012llX",
             (unsigned long long)(ESP.getEfuseMac() & 0xFFFFFFFFFFFFULL));
  }
}

void atenderIdentificacionUSB() {
  static char comando[32];
  static size_t longitud = 0;
  static bool excedido = false;
  for (uint8_t i = 0; i < 32 && Serial.available(); ++i) {
    const char caracter = static_cast<char>(Serial.read());
    if (caracter == '\n') {
      comando[longitud] = '\0';
      if (!excedido && strcmp(comando, "GEOCATTLE_IDENTIFY_V1") == 0) {
        Serial.printf("{\"type\":\"geocattle_collar\",\"version\":1,\"hardware_id\":\"%s\","
                      "\"transport\":\"academic\",\"interval_seconds\":%lu}\n",
                      COLLAR_ID, (unsigned long)(MINIMO_ENTRE_ENVIOS_MS / 1000));
      }
      longitud = 0;
      excedido = false;
    } else if (caracter != '\r') {
      if (longitud < sizeof(comando) - 1) comando[longitud++] = caracter;
      else excedido = true;
    }
  }
}

const int PIN_TEMPERATURA = 13;

const int OLED_SDA = 21;
const int OLED_SCL = 22;

const int ADXL_SDA = 25;
const int ADXL_SCL = 14;

const int PIN_GPS_RX = 34;
const int PIN_GPS_TX = 12;

// ============================================================
// OBJETOS
// ============================================================

XPowersPMU pmu;

Adafruit_SSD1306 pantalla(
  128, 64, &Wire, -1, 100000, 100000
);

TwoWire busADXL(1);

OneWire oneWire(PIN_TEMPERATURA);
DallasTemperature sensorTemperatura(&oneWire);

HardwareSerial puertoGPS(1);
TinyGPSPlus gps;

// ============================================================
// ESTADO GENERAL
// ============================================================

bool pmuOK = false;
bool pantallaOK = false;
bool acelerometroOK = false;

uint8_t direccionADXL = 0x53;

float temperatura = NAN;
float ax = NAN;
float ay = NAN;
float az = NAN;

char sesion[17];
uint32_t secuencia = 0;

String estadoEnvio = "Esperando";

bool huboEnvio = false;
bool eventoMovimientoPendiente = false;

uint32_t ultimoEnvio = 0;
uint32_t intervaloEnvio = 45000UL;

bool esperandoReintentoTX = false;
uint32_t ultimoIntentoTX = 0;

uint32_t ultimaAceleracion = 0;
uint32_t ultimaPantalla = 0;
uint32_t ultimaBateria = 0;
uint32_t ultimoReintentoADXL = 0;

// ============================================================
// TEMPERATURA
// ============================================================

bool conversionTemperaturaPendiente = false;

uint32_t inicioConversionTemperatura = 0;
uint32_t ultimaSolicitudTemperatura = 0;

// ============================================================
// BATERIA
// ============================================================

int bateriaMV = -1;
int bateriaPct = -1;
int bateriaPresente = -1;
int bateriaCargando = -1;
int usbPresente = -1;

// ============================================================
// MOVIMIENTO
// ============================================================

// -1: desconocido / esperando clasificacion.
//  0: reposo.
//  1: movimiento.
int estadoMovimiento = -1;

bool gravedadInicializada = false;

float gravedadX = 0;
float gravedadY = 0;
float gravedadZ = 0;

float energiaVentana = 0;
float rmsMovimiento = NAN;

uint16_t muestrasVentana = 0;
uint32_t inicioVentana = 0;

uint8_t ventanasMovimiento = 0;
uint8_t ventanasReposo = 0;

// ============================================================
// DIAGNOSTICO GPS
// ============================================================

uint32_t bytesGPS = 0;
uint32_t ultimoByteGPS = 0;
uint32_t ultimoDiagnosticoGPS = 0;

char bufferNMEA[160];
size_t longitudNMEA = 0;

int satelitesVisibles = -1;
int mejorCN0 = -1;
int calidadGGA = -1;

uint32_t ultimoGSV = 0;
uint32_t ultimoGGA = 0;
uint32_t mensajesGSV = 0;

uint8_t intentosSolicitarGSV = 0;
uint32_t ultimaSolicitudGSV = 0;

// ============================================================
// FUNCIONES GENERALES
// ============================================================

String valor(double numero, unsigned int decimales = 2) {
  if (!isfinite(numero)) {
    return "--";
  }

  return String(numero, decimales);
}

bool respondeI2C(uint8_t direccion) {
  Wire.beginTransmission(direccion);
  return Wire.endTransmission() == 0;
}

const char* textoMovimiento() {
  if (!acelerometroOK) {
    return "SIN ACELEROMETRO";
  }

  if (estadoMovimiento == 1) {
    return "EN MOVIMIENTO";
  }

  if (estadoMovimiento == 0) {
    return "EN REPOSO";
  }

  return "CLASIFICANDO";
}

// ============================================================
// ENERGIA AXP2101
// ============================================================

bool iniciarEnergia() {
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(100000);
  Wire.setTimeOut(50);

  pmuOK = pmu.begin(
    Wire,
    0x34,
    OLED_SDA,
    OLED_SCL
  );

  if (!pmuOK) {
    Serial.println("# ERROR: AXP2101 no identificado.");
    return false;
  }

  // Alimenta el ESP32 y los 3V3 externos.
  // Mantener este canal.
  pmu.setProtectedChannel(XPOWERS_DCDC1);

  bool radioVoltajeOK = pmu.setALDO2Voltage(3300);
  bool radioEncendidoOK = pmu.enableALDO2();

  bool gpsVoltajeOK = pmu.setALDO3Voltage(3300);
  bool gpsEncendidoOK = pmu.enableALDO3();

  // Respaldo RTC del GPS, siguiendo el esquema del T-Beam.
  pmu.setButtonBatteryChargeVoltage(3300);
  pmu.enableButtonBatteryCharge();

  pmu.enableBattDetection();
  pmu.enableBattVoltageMeasure();

  // Se conservan los demas canales y ajustes de carga.
  // Durante este diagnostico no se reduce la CPU
  // ni se aplica suspension profunda.

  delay(300);

  Serial.println("# PMU AXP2101 OK");

  Serial.printf(
    "# LoRa ALDO2: %s\n",
    radioVoltajeOK && radioEncendidoOK ? "OK" : "ERROR"
  );

  Serial.printf(
    "# GPS ALDO3: %s\n",
    gpsVoltajeOK && gpsEncendidoOK ? "OK" : "ERROR"
  );

  return radioVoltajeOK &&
         radioEncendidoOK &&
         gpsVoltajeOK &&
         gpsEncendidoOK;
}

int estimarPorcentaje(int mv) {
  const int curva[] = {
    3000, 3650, 3700, 3740, 3760, 3795,
    3840, 3910, 3980, 4070, 4150
  };

  if (mv <= curva[0]) return 0;
  if (mv >= curva[10]) return 100;

  for (int i = 0; i < 10; i++) {
    if (mv <= curva[i + 1]) {
      return i * 10 +
        (mv - curva[i]) * 10 /
        (curva[i + 1] - curva[i]);
    }
  }

  return -1;
}

void leerBateria() {
  bateriaMV = -1;
  bateriaPct = -1;
  bateriaPresente = -1;
  bateriaCargando = -1;
  usbPresente = -1;

  if (!pmuOK || !respondeI2C(0x34)) {
    return;
  }

  usbPresente = pmu.isVbusIn() ? 1 : 0;
  bateriaPresente = pmu.isBatteryConnect() ? 1 : 0;

  if (bateriaPresente == 0) {
    bateriaCargando = 0;
    return;
  }

  bateriaCargando = pmu.isCharging() ? 1 : 0;

  int lectura = pmu.getBattVoltage();

  if (lectura >= 2500 && lectura <= 4350) {
    bateriaMV = lectura;
    bateriaPct = estimarPorcentaje(lectura);
  }
}

// ============================================================
// PANTALLA
// ============================================================

void iniciarPantalla() {
  for (uint8_t direccion = 0x3C;
       direccion <= 0x3D;
       direccion++) {

    if (!respondeI2C(direccion)) {
      continue;
    }

    pantallaOK = pantalla.begin(
      SSD1306_SWITCHCAPVCC,
      direccion,
      false,
      false
    );

    if (pantallaOK) break;
  }

  if (!pantallaOK) {
    Serial.println("# OLED no detectada.");
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
  pantalla.println("GEOCATTLE T-BEAM");
  pantalla.println("AXP2101 / JSON V5");
  pantalla.display();
}

void linea(uint8_t fila, const String& texto) {
  if (!pantallaOK || !PANTALLA_ACTIVA) return;

  pantalla.setCursor(0, 12 + fila * 10);
  pantalla.print(texto.substring(0, 21));
}

void detenerConError(const char* mensaje) {
  Serial.print("# ERROR: ");
  Serial.println(mensaje);

  if (pantallaOK && PANTALLA_ACTIVA) {
    pantalla.clearDisplay();
    pantalla.setCursor(0, 0);
    pantalla.println(mensaje);
    pantalla.display();
  }

  while (true) {
    atenderIdentificacionUSB();
    delay(25);
  }
}

// ============================================================
// ADXL345
// ============================================================

bool escribirRegistroADXL(uint8_t registro, uint8_t dato) {
  busADXL.beginTransmission(direccionADXL);
  busADXL.write(registro);
  busADXL.write(dato);

  return busADXL.endTransmission() == 0;
}

int leerRegistroADXL(uint8_t registro) {
  busADXL.beginTransmission(direccionADXL);
  busADXL.write(registro);

  if (busADXL.endTransmission(false) != 0) {
    return -1;
  }

  if (busADXL.requestFrom(
        direccionADXL,
        (uint8_t)1
      ) != 1) {
    return -1;
  }

  return busADXL.read();
}

void reiniciarClasificacion() {
  gravedadInicializada = false;

  estadoMovimiento = -1;
  rmsMovimiento = NAN;

  ventanasMovimiento = 0;
  ventanasReposo = 0;

  energiaVentana = 0;
  muestrasVentana = 0;
  inicioVentana = millis();

  eventoMovimientoPendiente = false;
}

bool iniciarAcelerometro() {
  direccionADXL = 0x53;

  if (leerRegistroADXL(0x00) != 0xE5) {
    direccionADXL = 0x1D;

    if (leerRegistroADXL(0x00) != 0xE5) {
      return false;
    }
  }

  reiniciarClasificacion();

  // Standby durante la configuracion.
  if (!escribirRegistroADXL(0x2D, 0x00)) return false;

  // Resolucion completa, rango +/-8 g.
  if (!escribirRegistroADXL(0x31, 0x0A)) return false;

  // Muestreo a 25 Hz en modo normal.
  if (!escribirRegistroADXL(0x2C, 0x08)) return false;

  return escribirRegistroADXL(0x2D, 0x08);
}

void leerAcelerometro(uint32_t ahora) {
  if (!acelerometroOK) return;

  busADXL.beginTransmission(direccionADXL);
  busADXL.write(0x32);

  bool lecturaOK =
    busADXL.endTransmission(false) == 0;

  if (lecturaOK) {
    lecturaOK =
      busADXL.requestFrom(
        direccionADXL,
        (uint8_t)6
      ) == 6;
  }

  if (!lecturaOK) {
    ax = ay = az = NAN;
    acelerometroOK = false;
    reiniciarClasificacion();
    return;
  }

  uint8_t datos[6];

  for (int i = 0; i < 6; i++) {
    datos[i] = busADXL.read();
  }

  int16_t x = (int16_t)(
    ((uint16_t)datos[1] << 8) | datos[0]
  );

  int16_t y = (int16_t)(
    ((uint16_t)datos[3] << 8) | datos[2]
  );

  int16_t z = (int16_t)(
    ((uint16_t)datos[5] << 8) | datos[4]
  );

  ax = x * 0.0039f;
  ay = y * 0.0039f;
  az = z * 0.0039f;

  if (!gravedadInicializada) {
    gravedadX = ax;
    gravedadY = ay;
    gravedadZ = az;

    gravedadInicializada = true;
    inicioVentana = ahora;
  }

  // Estimacion lenta de la gravedad.
  constexpr float ALFA = 0.04f;

  gravedadX += ALFA * (ax - gravedadX);
  gravedadY += ALFA * (ay - gravedadY);
  gravedadZ += ALFA * (az - gravedadZ);

  float dx = ax - gravedadX;
  float dy = ay - gravedadY;
  float dz = az - gravedadZ;

  energiaVentana += dx * dx + dy * dy + dz * dz;
  muestrasVentana++;

  uint32_t duracion = ahora - inicioVentana;

  if (duracion < 1000) {
    return;
  }

  if (muestrasVentana >= 18 && duracion <= 1600) {
    rmsMovimiento = sqrtf(
      energiaVentana / muestrasVentana
    );

    if (rmsMovimiento >= UMBRAL_MOVIMIENTO_G) {
      if (ventanasMovimiento < 255) {
        ventanasMovimiento++;
      }

      ventanasReposo = 0;

    } else if (rmsMovimiento <= UMBRAL_REPOSO_G) {
      if (ventanasReposo < 255) {
        ventanasReposo++;
      }

      ventanasMovimiento = 0;

    } else {
      // Banda intermedia: conservar el estado anterior.
      ventanasMovimiento = 0;
      ventanasReposo = 0;
    }

    if (
      ventanasMovimiento >=
        SEGUNDOS_CONFIRMAR_MOVIMIENTO &&
      estadoMovimiento != 1
    ) {
      estadoMovimiento = 1;
      eventoMovimientoPendiente = true;

      Serial.println("# MOVIMIENTO: inicio confirmado");
    }

    if (
      ventanasReposo >= SEGUNDOS_CONFIRMAR_REPOSO &&
      estadoMovimiento != 0
    ) {
      estadoMovimiento = 0;
      eventoMovimientoPendiente = false;

      Serial.println("# MOVIMIENTO: reposo confirmado");
    }

  } else {
    // Una pausa breve de TX no debe crear un evento falso.
    ventanasMovimiento = 0;
    ventanasReposo = 0;

    if (duracion > 1600) {
      estadoMovimiento = -1;
      rmsMovimiento = NAN;
    }
  }

  energiaVentana = 0;
  muestrasVentana = 0;
  inicioVentana = ahora;
}

// ============================================================
// TEMPERATURA ASINCRONA
// ============================================================

void atenderTemperatura(uint32_t ahora) {
  if (
    conversionTemperaturaPendiente &&
    ahora - inicioConversionTemperatura >= 800
  ) {
    float lectura =
      sensorTemperatura.getTempCByIndex(0);

    if (
      lectura == DEVICE_DISCONNECTED_C ||
      !isfinite(lectura) ||
      lectura < -55.0f ||
      lectura > 100.0f
    ) {
      temperatura = NAN;
    } else {
      temperatura = lectura;
    }

    conversionTemperaturaPendiente = false;
  }

  if (
    !conversionTemperaturaPendiente &&
    ahora - ultimaSolicitudTemperatura >=
      PERIODO_TEMPERATURA_MS
  ) {
    sensorTemperatura.requestTemperatures();

    inicioConversionTemperatura = ahora;
    ultimaSolicitudTemperatura = ahora;
    conversionTemperaturaPendiente = true;
  }
}

// ============================================================
// GPS: LECTURA Y ANALISIS DE NMEA
// ============================================================

int hexadecimal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;

  return -1;
}

bool checksumNMEAValido(const String& texto) {
  if (!texto.startsWith("$")) return false;

  int estrella = texto.indexOf('*');

  if (
    estrella < 1 ||
    estrella + 2 >= (int)texto.length()
  ) {
    return false;
  }

  int alto = hexadecimal(texto[estrella + 1]);
  int bajo = hexadecimal(texto[estrella + 2]);

  if (alto < 0 || bajo < 0) return false;

  uint8_t calculado = 0;

  for (int i = 1; i < estrella; i++) {
    calculado ^= (uint8_t)texto[i];
  }

  return calculado == (uint8_t)((alto << 4) | bajo);
}

String campoNMEA(const String& texto, uint8_t indice) {
  int inicio = 0;

  for (uint8_t i = 0; i < indice; i++) {
    int coma = texto.indexOf(',', inicio);

    if (coma < 0) return "";

    inicio = coma + 1;
  }

  int fin = inicio;

  while (
    fin < (int)texto.length() &&
    texto[fin] != ',' &&
    texto[fin] != '*'
  ) {
    fin++;
  }

  return texto.substring(inicio, fin);
}

void analizarLineaGPS(const String& texto) {
  if (!checksumNMEAValido(texto)) return;

  String tipo = campoNMEA(texto, 0);

  bool esGGA =
    tipo == "$GPGGA" || tipo == "$GNGGA";

  bool esRMC =
    tipo == "$GPRMC" || tipo == "$GNRMC";

  bool esGSV =
    tipo == "$GPGSV" || tipo == "$GNGSV";

  if (
    MOSTRAR_NMEA &&
    (esGGA || esRMC || esGSV)
  ) {
    Serial.print("# NMEA ");
    Serial.println(texto);
  }

  if (esGGA) {
    String calidad = campoNMEA(texto, 6);

    calidadGGA =
      calidad.length() ? calidad.toInt() : -1;

    ultimoGGA = millis();
  }

  if (esGSV) {
    mensajesGSV++;
    ultimoGSV = millis();

    int numeroMensaje = campoNMEA(texto, 2).toInt();

    String visibles = campoNMEA(texto, 3);

    if (visibles.length()) {
      satelitesVisibles = constrain(
        visibles.toInt(), 0L, 99L
      );
    }

    if (numeroMensaje == 1) {
      mejorCN0 = -1;
    }

    // Cada GSV contiene hasta cuatro satelites.
    // Sus campos C/N0 son 7, 11, 15 y 19.
    for (uint8_t campo = 7; campo <= 19; campo += 4) {
      String senal = campoNMEA(texto, campo);

      if (!senal.length()) continue;

      int cn0 = senal.toInt();

      if (cn0 >= 0 && cn0 <= 99 && cn0 > mejorCN0) {
        mejorCN0 = cn0;
      }
    }
  }
}

void procesarGPS() {
  while (puertoGPS.available()) {
    char c = (char)puertoGPS.read();

    bytesGPS++;
    ultimoByteGPS = millis();

    gps.encode(c);

    if (c == '$') {
      longitudNMEA = 0;
      bufferNMEA[longitudNMEA++] = c;

    } else if (c == '\n') {
      if (longitudNMEA > 0) {
        bufferNMEA[longitudNMEA] = '\0';
        analizarLineaGPS(String(bufferNMEA));
      }

      longitudNMEA = 0;

    } else if (c != '\r' && longitudNMEA > 0) {
      if (longitudNMEA < sizeof(bufferNMEA) - 1) {
        bufferNMEA[longitudNMEA++] = c;
      } else {
        longitudNMEA = 0;
      }
    }
  }
}

void solicitarMensajesGSV(uint32_t ahora) {
  if (!SOLICITAR_GSV) return;

  // Si ya llegan GSV, no hace falta configurar nada.
  if (mensajesGSV > 0) return;

  if (gps.passedChecksum() < 2) return;
  if (intentosSolicitarGSV >= 3) return;

  if (ahora - ultimaSolicitudGSV < 10000) {
    return;
  }

  ultimaSolicitudGSV = ahora;
  intentosSolicitarGSV++;

  // UBX-CFG-MSG:
  // clase NMEA 0xF0, mensaje GSV 0x03, frecuencia 1.
  // Se configura el puerto actual. No se guarda en flash.
  uint8_t mensaje[] = {
    0xB5, 0x62,
    0x06, 0x01,
    0x03, 0x00,
    0xF0, 0x03, 0x01,
    0x00, 0x00
  };

  uint8_t ckA = 0;
  uint8_t ckB = 0;

  for (size_t i = 2; i < sizeof(mensaje) - 2; i++) {
    ckA += mensaje[i];
    ckB += ckA;
  }

  mensaje[sizeof(mensaje) - 2] = ckA;
  mensaje[sizeof(mensaje) - 1] = ckB;

  puertoGPS.write(mensaje, sizeof(mensaje));

  Serial.printf(
    "# GPS: solicitud GSV enviada, intento %u.\n",
    (unsigned int)intentosSolicitarGSV
  );

  // La llegada posterior de GSV confirma que se recibe
  // esa salida. Enviar el comando no equivale a un ACK.
}

bool posicionValida() {
  if (
    !gps.location.isValid() ||
    gps.location.age() >= 5000
  ) {
    return false;
  }

  // No reutilizar una posicion reciente si el GGA
  // actual informa que se perdio la solucion.
  if (
    ultimoGGA != 0 &&
    millis() - ultimoGGA < 5000 &&
    calidadGGA == 0
  ) {
    return false;
  }

  return true;
}

int satelitesUsados() {
  if (
    gps.satellites.isValid() &&
    gps.satellites.age() < 10000
  ) {
    return (int)gps.satellites.value();
  }

  return -1;
}

int visiblesActuales() {
  if (
    mensajesGSV == 0 ||
    millis() - ultimoGSV >= 15000
  ) {
    return -1;
  }

  return satelitesVisibles;
}

int cn0Actual() {
  if (visiblesActuales() < 0) return -1;

  return mejorCN0;
}

double hdopActual() {
  if (
    gps.hdop.isValid() &&
    gps.hdop.age() < 10000
  ) {
    return gps.hdop.hdop();
  }

  return NAN;
}

const char* estadoGPS() {
  if (
    bytesGPS == 0 ||
    millis() - ultimoByteGPS > 10000
  ) {
    return "SIN DATOS UART";
  }

  if (gps.passedChecksum() == 0) {
    return "NMEA SIN VALIDAR";
  }

  if (posicionValida()) {
    return "FIX VALIDO";
  }

  if (visiblesActuales() == 0) {
    return "SIN SAT VISIBLES";
  }

  if (visiblesActuales() > 0) {
    return "SAT VISTOS SIN FIX";
  }

  return "SIN FIX / SIN GSV";
}

void diagnosticarGPS(uint32_t ahora) {
  if (ahora - ultimoDiagnosticoGPS < 5000) {
    return;
  }

  ultimoDiagnosticoGPS = ahora;

  Serial.printf(
    "# GPS estado=%s bytes=%lu validas=%lu "
    "errores=%lu usados=%d visibles=%d "
    "CN0max=%d HDOP=%.2f calidadGGA=%d "
    "ALDO3=%d configurado_mV=%u\n",
    estadoGPS(),
    (unsigned long)bytesGPS,
    (unsigned long)gps.passedChecksum(),
    (unsigned long)gps.failedChecksum(),
    satelitesUsados(),
    visiblesActuales(),
    cn0Actual(),
    isfinite(hdopActual()) ? hdopActual() : -1.0,
    calidadGGA,
    pmu.isEnableALDO3() ? 1 : 0,
    (unsigned int)pmu.getALDO3Voltage()
  );

  // configurado_mV es el ajuste del regulador.
  // No es una medicion fisica del voltaje en el GPS.
}

// ============================================================
// RADIO
// ============================================================

bool iniciarRadio() {
  SPI.begin(5, 19, 27, 18);
  LoRa.setPins(18, 23, 26);

  if (!LoRa.begin(FRECUENCIA)) {
    return false;
  }

  LoRa.setSpreadingFactor(7);
  LoRa.setSignalBandwidth(125000);
  LoRa.setCodingRate4(5);
  LoRa.setSyncWord(0x12);
  LoRa.setPreambleLength(8);
  LoRa.enableCrc();

  // Pruebas cercanas.
  LoRa.setTxPower(2);

  LoRa.sleep();
  return true;
}

void agregarNumero(
  JsonArray arreglo,
  float numero,
  unsigned int decimales = 3
) {
  if (isfinite(numero)) {
    arreglo.add(serialized(String(numero, decimales)));
  } else {
    arreglo.add(nullptr);
  }
}

// ============================================================
// ENVIO JSON V5
// ============================================================

void transmitir(uint8_t motivo) {
  if (
    esperandoReintentoTX &&
    millis() - ultimoIntentoTX < 5000
  ) {
    return;
  }

  ultimoIntentoTX = millis();
  esperandoReintentoTX = true;

  procesarGPS();
  leerBateria();

  bool fix = posicionValida();

  JsonDocument documento;

  documento["v"] = 5;
  documento["id"] = COLLAR_ID;
  documento["s"] = sesion;
  documento["q"] = ++secuencia;
  documento["u"] = millis();

  // g = latitud, longitud, edad, satelites usados, HDOP
  JsonArray posicion = documento["g"].to<JsonArray>();

  if (fix) {
    posicion.add(
      serialized(String(gps.location.lat(), 6))
    );

    posicion.add(
      serialized(String(gps.location.lng(), 6))
    );
  } else {
    posicion.add(nullptr);
    posicion.add(nullptr);
  }

  if (gps.location.isValid()) {
    posicion.add(gps.location.age());
  } else {
    posicion.add(-1);
  }

  posicion.add(satelitesUsados());

  double hdop = hdopActual();

  if (isfinite(hdop) && hdop <= 999.99) {
    posicion.add(serialized(String(hdop, 2)));
  } else {
    posicion.add(nullptr);
  }

  if (isfinite(temperatura)) {
    documento["t"] =
      serialized(String(temperatura, 2));
  } else {
    documento["t"] = nullptr;
  }

  JsonArray aceleracion =
    documento["a"].to<JsonArray>();

  agregarNumero(aceleracion, ax);
  agregarNumero(aceleracion, ay);
  agregarNumero(aceleracion, az);

  // m = estado, RMS de aceleracion dinamica en g
  JsonArray movimiento =
    documento["m"].to<JsonArray>();

  movimiento.add(estadoMovimiento);
  agregarNumero(movimiento, rmsMovimiento);

  // b = mV, porcentaje, presente, cargando, USB
  JsonArray bateria =
    documento["b"].to<JsonArray>();

  bateria.add(bateriaMV);
  bateria.add(bateriaPct);
  bateria.add(bateriaPresente);
  bateria.add(bateriaCargando);
  bateria.add(usbPresente);

  intervaloEnvio = 45000UL;

  documento["p"] = intervaloEnvio;

  bool aceleracionValida =
    isfinite(ax) && isfinite(ay) && isfinite(az);

  uint8_t flags =
    (fix ? 0 : 1) |
    (isfinite(temperatura) ? 0 : 2) |
    (aceleracionValida ? 0 : 4);

  documento["f"] = flags;

  // 0: arranque; 1: periodico; 2: inicio de movimiento.
  documento["e"] = motivo;

  JsonArray diagnostico =
    documento["d"].to<JsonArray>();

  diagnostico.add(bytesGPS);
  diagnostico.add(gps.passedChecksum());
  diagnostico.add(gps.failedChecksum());

  if (measureJson(documento) > 255) {
    documento.remove("d");
  }

  size_t longitud = measureJson(documento);

  if (documento.overflowed() || longitud > 255) {
    estadoEnvio = "ERROR JSON largo";
    Serial.println("# ERROR: JSON no cabe en LoRa.");
    return;
  }

  char paquete[256];

  serializeJson(
    documento,
    paquete,
    sizeof(paquete)
  );

  LoRa.idle();

  bool envioOK = false;

  if (LoRa.beginPacket() == 1) {
    size_t escritos = LoRa.write(
      (const uint8_t*)paquete,
      longitud
    );

    int resultado = LoRa.endPacket();

    envioOK =
      escritos == longitud && resultado == 1;
  }

  LoRa.sleep();
  procesarGPS();

  if (!envioOK) {
    estadoEnvio = "ERROR TX";
    Serial.println("# ERROR: envio LoRa.");
    return;
  }

  ultimoEnvio = millis();
  huboEnvio = true;

  esperandoReintentoTX = false;
  eventoMovimientoPendiente = false;

  estadoEnvio = "TX terminado";

  // Esta linea contiene exactamente el JSON enviado.
  Serial.println(paquete);
}

// ============================================================
// VISUALIZACION DE DATOS ACTUALES
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

  pantalla.print(COLLAR_ID);
  pantalla.print(" TX#");
  pantalla.print(secuencia);

  uint8_t pagina = (ahora / 5000UL) % 3;

  if (pagina == 0) {
    linea(0, "T: " + valor(temperatura, 2) + " C");

    linea(1, textoMovimiento());

    linea(
      2,
      "RMS: " + valor(rmsMovimiento, 3) + " g"
    );

    linea(
      3,
      "X:" + valor(ax, 2) + " Y:" + valor(ay, 2)
    );

    linea(4, "Z:" + valor(az, 2) + " g");

  } else if (pagina == 1) {
    linea(0, String("GPS ") + estadoGPS());

    linea(
      1,
      "Usa:" + String(satelitesUsados()) +
      " Ve:" + String(visiblesActuales())
    );

    linea(
      2,
      "CN0:" + String(cn0Actual()) +
      " H:" + valor(hdopActual(), 1)
    );

    linea(
      3,
      posicionValida()
        ? "Lat:" + valor(gps.location.lat(), 6)
        : "Lat: --"
    );

    linea(
      4,
      posicionValida()
        ? "Lon:" + valor(gps.location.lng(), 6)
        : "Lon: --"
    );

  } else {
    if (bateriaPresente == 0) {
      linea(0, "USB / Sin bateria");

    } else if (bateriaMV >= 0) {
      linea(
        0,
        "Bat:~" + String(bateriaPct) +
        "% " + String(bateriaMV) + "mV"
      );

    } else {
      linea(0, "Bateria: sin lectura");
    }

    linea(
      1,
      bateriaCargando == 1
        ? "Estado: cargando"
        : usbPresente == 1
          ? "USB conectado"
          : "Fuente: bateria"
    );

    linea(
      2,
      "NMEA:" + String(gps.passedChecksum()) +
      " E:" + String(gps.failedChecksum())
    );

    linea(
      3,
      huboEnvio
        ? "TX hace " +
          String((ahora - ultimoEnvio) / 1000UL) +
          " s"
        : "Esperando primer TX"
    );

    linea(4, estadoEnvio);
  }

  pantalla.display();
}

// ============================================================
// INICIO
// ============================================================

void setup() {
  Serial.begin(115200);
  inicializarIdentidadCollar();
  delay(500);

  Serial.println();
  Serial.println("# GEOCATTLE T-BEAM AXP2101");
  Serial.println("# OLED/PMU SDA21 SCL22");
  Serial.println("# ADXL345 SDA25 SCL14");
  Serial.println("# DS18B20 DAT13");
  Serial.println("# GPS interno RX34 / TX12");

  bool energiaOK = iniciarEnergia();

  iniciarPantalla();

  if (!energiaOK) {
    detenerConError("ERROR PMU AXP2101");
  }

  snprintf(
    sesion,
    sizeof(sesion),
    "%08lX%08lX",
    (unsigned long)esp_random(),
    (unsigned long)esp_random()
  );

  // GPIO12 es una conexion interna al RX del GPS.
  // No hay que agregar un cable externo.
  puertoGPS.setRxBufferSize(4096);

  puertoGPS.begin(
    9600,
    SERIAL_8N1,
    PIN_GPS_RX,
    SOLICITAR_GSV ? PIN_GPS_TX : -1
  );

  sensorTemperatura.begin();
  sensorTemperatura.setResolution(12);
  sensorTemperatura.setWaitForConversion(false);
  sensorTemperatura.requestTemperatures();

  inicioConversionTemperatura = millis();
  ultimaSolicitudTemperatura = millis();
  conversionTemperaturaPendiente = true;

  Serial.printf(
    "# DS18B20 detectados: %u\n",
    (unsigned int)sensorTemperatura.getDeviceCount()
  );

  busADXL.begin(
    ADXL_SDA,
    ADXL_SCL,
    100000
  );

  busADXL.setTimeOut(50);

  acelerometroOK = iniciarAcelerometro();

  Serial.println(
    acelerometroOK
      ? "# ADXL345 OK"
      : "# ADXL345 no detectado"
  );

  leerBateria();

  if (!iniciarRadio()) {
    detenerConError("ERROR LORA SX1276");
  }

  Serial.println("# LoRa 915.5MHz SF7 BW125 CR4/5");
  Serial.println("# Envio periodico cada 45 segundos.");
  Serial.println("# Evento al iniciar movimiento.");
  Serial.println("# GPS continuo durante diagnostico.");
}

// ============================================================
// BUCLE PRINCIPAL
// ============================================================

void loop() {
  atenderIdentificacionUSB();
  procesarGPS();

  uint32_t ahora = millis();

  solicitarMensajesGSV(ahora);
  atenderTemperatura(ahora);

  if (
    ahora - ultimaAceleracion >=
      PERIODO_ACELEROMETRO_MS
  ) {
    ultimaAceleracion = ahora;
    leerAcelerometro(ahora);
  }

  if (
    !acelerometroOK &&
    ahora - ultimoReintentoADXL >= 10000
  ) {
    ultimoReintentoADXL = ahora;
    acelerometroOK = iniciarAcelerometro();
  }

  if (
    ahora - ultimaBateria >=
      PERIODO_BATERIA_MS
  ) {
    ultimaBateria = ahora;
    leerBateria();
  }

  if (!huboEnvio && ahora >= 3000) {
    transmitir(0);

  } else if (
    eventoMovimientoPendiente &&
    estadoMovimiento == 1 &&
    ahora - ultimoEnvio >= MINIMO_ENTRE_ENVIOS_MS
  ) {
    transmitir(2);

  } else if (
    huboEnvio &&
    ahora - ultimoEnvio >= intervaloEnvio
  ) {
    transmitir(1);
  }

  diagnosticarGPS(millis());
  mostrarPantalla(millis());

  delay(1);
}
