/*
  GEOCATTLE - RECEPTORA NUBE T3 V1.6.1
  ESP32 + SX1276 + OLED SSD1306.
  RadioLib 7.8.1, ArduinoJson 7.x, Adafruit SSD1306, Arduino-ESP32 3.x o 4.x.
  Placa: ESP32 Dev Module. Esquema de particiones recomendado: No OTA (2MB APP/2MB SPIFFS).
  Monitor serie: 115200.

  Escucha bus_v1 sin alterar la malla de la T3 base USB (nodo 0). Si no oye
  ninguna raíz durante 25 s (GC_ROOT_FALLBACK), hace de raíz de respaldo: emite
  balizas y confirma con ACK los lotes dirigidos al nodo 0. Al oír otra raíz
  vuelve a escuchar en silencio.
  Guarda los collares que oye directo y los lotes que reenvían los gateways
  (una sola vez si llegan por ambos caminos) en LittleFS y los sube por HTTPS a
  /api/v1/ingest/receiver-batch. Si WiFi o el servidor fallan, conserva las
  lecturas más recientes hasta la capacidad de la flash.

  Los gateways necesitan balizas de una raíz (la base o esta T3) para reenviar.
  Copia config.example.h como config.h y completa WiFi, servidor y predio.
  Conectar antena antes de alimentar.
*/

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <RadioLib.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <NetworkClientSecure.h>
#include <WiFi.h>
#include <atomic>
#include <ctype.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <math.h>
#include <sys/time.h>

#if __has_include("config.h")
#include "config.h"
#else
#error "Copia config.example.h como config.h y completa los valores"
#endif
#ifndef GC_ROOT_FALLBACK
#define GC_ROOT_FALLBACK 1
#endif

constexpr char FIRMWARE[] = "nube-t3-2";

// Identidad de una lectura (antes de las funciones por los prototipos de Arduino).
struct Key {
  char collar[17] = {};
  char session[17] = {};
  uint32_t q = 0;
};

// ---------------------------------------------------------------- bus_v1
namespace gc {
constexpr size_t HEADER_SIZE = 26;
constexpr size_t MAX_RF = 255;
constexpr size_t CHUNK = MAX_RF - HEADER_SIZE;
constexpr size_t MAX_BATCH = 1100;
constexpr uint32_t REASSEMBLY_TTL_MS = 15000;
constexpr uint8_t BROADCAST = 255;

enum Kind : uint8_t { Beacon = 1, Data = 2, Ack = 3 };
enum ReassemblyResult : uint8_t { Invalid, Incomplete, Complete };

struct Header {
  uint8_t kind = 0, src = 0, dst = 0;
  uint32_t boot = 0, number = 0;
  uint8_t index = 0, parts = 0;
  uint16_t total = 0;
  uint32_t checksum = 0, elapsed_ms = 0;
};

constexpr uint16_t read16(const uint8_t* p) {
  return uint16_t(p[0]) | uint16_t(uint16_t(p[1]) << 8);
}
constexpr void write16(uint8_t* p, uint16_t v) {
  p[0] = uint8_t(v);
  p[1] = uint8_t(v >> 8);
}
constexpr void write32(uint8_t* p, uint32_t v) {
  for (size_t i = 0; i < 4; ++i) p[i] = uint8_t(v >> (8 * i));
}
constexpr uint32_t read32(const uint8_t* p) {
  return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
         (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
constexpr uint32_t crc32(const uint8_t* data, size_t length) {
  uint32_t crc = 0xFFFFFFFFUL;
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320UL : 0UL);
  }
  return crc ^ 0xFFFFFFFFUL;
}
constexpr uint8_t partCount(uint16_t total) {
  return (total == 0 || total > MAX_BATCH)
             ? 0 : uint8_t((total + CHUNK - 1) / CHUNK);
}
constexpr size_t expectedDataPartLen(uint16_t total, uint8_t index) {
  const uint8_t parts = partCount(total);
  if (!parts || index >= parts) return 0;
  const size_t remaining = size_t(total) - size_t(index) * CHUNK;
  return remaining < CHUNK ? remaining : CHUNK;
}
constexpr bool validHeader(const Header& h) {
  if (h.src > 2) return false;
  if (h.kind == Beacon)
    return h.dst == BROADCAST && h.index == 0 &&
           h.parts == 1 && h.total == 14;
  if (h.kind == Data)
    return h.src >= 1 && h.dst <= 2 && h.dst != h.src &&
           h.parts == partCount(h.total) && h.parts != 0 &&
           h.index < h.parts;
  if (h.kind == Ack)
    return h.dst >= 1 && h.dst <= 2 && h.dst != h.src &&
           h.total == 0 && h.parts == 0 && h.index <= 3;
  return false;
}
constexpr bool decodeHeader(const uint8_t* frame, size_t length, Header& result) {
  if (!frame || length < HEADER_SIZE ||
      frame[0] != 'G' || frame[1] != 'C' || frame[2] != 1) return false;
  Header h{};
  h.kind = frame[3]; h.src = frame[4]; h.dst = frame[5];
  h.boot = read32(frame + 6);
  h.number = read32(frame + 10);
  h.index = frame[14]; h.parts = frame[15];
  h.total = read16(frame + 16);
  h.checksum = read32(frame + 18);
  h.elapsed_ms = read32(frame + 22);
  if (!validHeader(h)) return false;
  result = h;
  return true;
}

constexpr bool encodeHeader(const Header& h, uint8_t* out, size_t capacity) {
  if (!out || capacity < HEADER_SIZE || !validHeader(h)) return false;
  out[0] = 'G'; out[1] = 'C'; out[2] = 1; out[3] = h.kind;
  out[4] = h.src; out[5] = h.dst;
  write32(out + 6, h.boot); write32(out + 10, h.number);
  out[14] = h.index; out[15] = h.parts;
  write16(out + 16, h.total); write32(out + 18, h.checksum);
  write32(out + 22, h.elapsed_ms);
  return true;
}

class Reassembly {
 public:
  ReassemblyResult ingest(const Header& h, const uint8_t* payload,
                          size_t length, uint32_t now) {
    expire(now);
    if (h.kind != Data || !validHeader(h) || !payload ||
        length != expectedDataPartLen(h.total, h.index)) return Invalid;

    int index = -1;
    for (int i = 0; i < 2; ++i) {
      if (slots_[i].used && sameKey(slots_[i].header, h)) { index = i; break; }
    }
    if (completed_ >= 0 && index != completed_) return Invalid;
    if (index >= 0 &&
        (slots_[index].header.total != h.total ||
         slots_[index].header.parts != h.parts ||
         slots_[index].header.checksum != h.checksum)) {
      release(index);
      return Invalid;
    }
    if (index < 0) {
      for (int i = 0; i < 2; ++i) {
        if (!slots_[i].used) { index = i; break; }
      }
      if (index < 0) return Invalid;
      slots_[index].used = true;
      slots_[index].header = h;
      slots_[index].first = now;
      slots_[index].mask = 0;
      slots_[index].maxElapsed = h.elapsed_ms;
    }

    Slot& slot = slots_[index];
    const size_t offset = size_t(h.index) * CHUNK;
    const uint8_t bit = uint8_t(1U << h.index);
    if (slot.mask & bit) {
      if (memcmp(slot.data + offset, payload, length) != 0) {
        release(index);
        return Invalid;
      }
    } else {
      memcpy(slot.data + offset, payload, length);
      slot.mask = uint8_t(slot.mask | bit);
    }
    if (h.elapsed_ms > slot.maxElapsed) slot.maxElapsed = h.elapsed_ms;
    if (slot.mask != uint8_t((1U << h.parts) - 1U)) return Incomplete;
    if (crc32(slot.data, slot.header.total) != slot.header.checksum) {
      release(index);
      return Invalid;
    }
    completed_ = index;
    return Complete;
  }
  const uint8_t* completedData() const {
    return completed_ < 0 ? nullptr : slots_[completed_].data;
  }
  size_t completedSize() const {
    return completed_ < 0 ? 0 : slots_[completed_].header.total;
  }
  uint32_t completedElapsed() const {
    return completed_ < 0 ? 0 : slots_[completed_].maxElapsed;
  }
  void clearCompleted() {
    if (completed_ >= 0) release(completed_);
  }
  void expire(uint32_t now) {
    for (int i = 0; i < 2; ++i) {
      if (slots_[i].used && i != completed_ &&
          uint32_t(now - slots_[i].first) >= REASSEMBLY_TTL_MS) release(i);
    }
  }

 private:
  struct Slot {
    bool used = false;
    Header header{};
    uint32_t first = 0, maxElapsed = 0;
    uint8_t mask = 0;
    uint8_t data[MAX_BATCH] = {};
  };
  Slot slots_[2]{};
  int completed_ = -1;

  static bool sameKey(const Header& a, const Header& b) {
    return a.src == b.src && a.dst == b.dst &&
           a.boot == b.boot && a.number == b.number;
  }
  void release(int i) {
    slots_[i].used = false;
    slots_[i].mask = 0;
    if (completed_ == i) completed_ = -1;
  }
};
}  // namespace gc

// ---------------------------------------------------------------- tiempo
constexpr int64_t FIRST_EPOCH = 1704067200;  // 2024-01-01 UTC.

int64_t epochMs() {
  timeval now{};
  gettimeofday(&now, nullptr);
  return now.tv_sec >= FIRST_EPOCH ? int64_t(now.tv_sec) * 1000 + now.tv_usec / 1000 : 0;
}
int64_t uptimeMs() { return esp_timer_get_time() / 1000; }
String isoTime(int64_t epoch) {
  const time_t seconds = epoch / 1000;
  tm utc{};
  gmtime_r(&seconds, &utc);
  char iso[32];
  strftime(iso, sizeof(iso), "%Y-%m-%dT%H:%M:%SZ", &utc);
  return String(iso);
}

// ---------------------------------------------------------------- memoria
namespace store {
constexpr size_t MAX_CAPACITY = 4096;  // Tope de buffer_capacity en la API.
// LittleFS reescribe un archivo desde el punto modificado hasta el final, así que
// la cola se reparte en archivos de 13 lecturas (un bloque de 4 KB cada uno):
// cada cambio reescribe solo ese bloque y LittleFS reparte el desgaste.
constexpr size_t PER_FILE = 13;
constexpr char DIR_PATH[] = "/cola";
constexpr char OLD_PATH[] = "/cola.bin";  // Formato anterior de un solo archivo.

struct __attribute__((packed)) Capture {
  uint32_t seq = 0;
  uint32_t boot = 0;
  int64_t uptime = 0;   // ms desde el arranque que capturó.
  int64_t epoch = 0;    // ms UTC; 0 si aún no había hora.
  uint32_t delayMs = 0; // Antigüedad de la lectura al capturarla.
  int16_t rssi10 = 0, snr10 = 0;
  uint8_t origin = 0, hops = 0, path = 0, reserved = 0;
  uint16_t len = 0;
  uint8_t packet[255] = {};
  uint32_t crc = 0;
};
constexpr size_t RECORD = sizeof(Capture);

QueueHandle_t incoming = nullptr;
SemaphoreHandle_t lock = nullptr;
uint32_t seqs[MAX_CAPACITY]{};  // Protegido por lock. 0 = vacío.
uint32_t nextSeq = 1;           // Protegido por lock.
int64_t lastCapture = 0;        // Protegido por lock.
std::atomic<uint32_t> capacity{0}, pending{0}, captured{0}, delivered{0};
std::atomic<uint32_t> overwritten{0}, rejected{0}, lost{0};
std::atomic<bool> ready{false}, failed{false}, preparing{true};

uint32_t checksum(const Capture& item) {
  return gc::crc32(reinterpret_cast<const uint8_t*>(&item), offsetof(Capture, crc));
}
String chunkPath(size_t slot) {
  char path[24];
  snprintf(path, sizeof(path), "%s/%03u.bin", DIR_PATH, unsigned(slot / PER_FILE));
  return String(path);
}
bool valid(const Capture& item, size_t slot) {
  return item.seq && item.seq % capacity == slot && item.len &&
         item.len <= sizeof(item.packet) && item.crc == checksum(item);
}
// Escribe bytes dentro del archivo de la ranura; close() deja el bloque confirmado.
bool writeAt(size_t slot, size_t offset, const void* data, size_t size) {
  File f = LittleFS.open(chunkPath(slot), "r+");
  if (!f) return false;
  const bool ok = f.seek((slot % PER_FILE) * RECORD + offset) &&
                  f.write(static_cast<const uint8_t*>(data), size) == size;
  f.close();
  return ok;
}
bool readSlot(size_t slot, Capture& item) {
  File f = LittleFS.open(chunkPath(slot), FILE_READ);
  if (!f) return false;
  const bool ok = f.seek((slot % PER_FILE) * RECORD) &&
                  f.read(reinterpret_cast<uint8_t*>(&item), RECORD) == RECORD;
  f.close();
  return ok && valid(item, slot);
}
bool prepareFile() {
  if (!LittleFS.begin(true)) return false;
  if (LittleFS.exists(OLD_PATH)) LittleFS.remove(OLD_PATH);
  if (!LittleFS.exists(DIR_PATH) && !LittleFS.mkdir(DIR_PATH)) return false;
  // Hasta el 70 % de los bloques; el resto queda para la copia al escribir.
  const size_t files = min((MAX_CAPACITY + PER_FILE - 1) / PER_FILE,
                           size_t(LittleFS.totalBytes()) / 4096 * 70 / 100);
  const size_t cap = min(MAX_CAPACITY, files * PER_FILE);
  if (cap < 64) return false;
  capacity = cap;
  const size_t bytes = PER_FILE * RECORD;
  static uint8_t zeros[PER_FILE * RECORD];
  uint32_t count = 0;
  for (size_t chunk = 0; chunk < files; ++chunk) {
    const String path = chunkPath(chunk * PER_FILE);
    File f = LittleFS.open(path, FILE_READ);
    const bool sized = f && f.size() == bytes;
    if (f) f.close();
    if (!sized) {
      File created = LittleFS.open(path, FILE_WRITE);
      const bool ok = created && created.write(zeros, bytes) == bytes;
      if (created) created.close();
      if (!ok) return false;
      vTaskDelay(1);
      continue;
    }
    for (size_t slot = chunk * PER_FILE; slot < min(cap, (chunk + 1) * PER_FILE); ++slot) {
      Capture item{};
      if (readSlot(slot, item)) {
        seqs[slot] = item.seq;
        ++count;
        if (item.seq >= nextSeq) nextSeq = item.seq + 1;
        if (item.epoch > lastCapture) lastCapture = item.epoch;
      }
    }
    vTaskDelay(1);
  }
  pending = count;
  return true;
}
bool write(Capture& item) {
  const uint32_t cap = capacity;
  const size_t slot = nextSeq % cap;
  item.seq = nextSeq;
  item.crc = checksum(item);
  const bool replacing = seqs[slot] != 0;
  if (!writeAt(slot, 0, &item, RECORD)) {
    if (replacing) { seqs[slot] = 0; --pending; ++lost; }
    return false;
  }
  if (replacing) ++overwritten;  // Lleno: se reemplaza la lectura más antigua.
  else ++pending;
  seqs[slot] = nextSeq++;
  if (item.epoch > lastCapture) lastCapture = item.epoch;
  ++captured;
  return true;
}
void storageTask(void*) {
  xSemaphoreTake(lock, portMAX_DELAY);
  ready = prepareFile();
  xSemaphoreGive(lock);
  failed = !ready;
  preparing = false;
  Capture item{};
  for (;;) {
    if (xQueueReceive(incoming, &item, portMAX_DELAY) != pdTRUE) continue;
    if (!ready) { ++lost; continue; }
    xSemaphoreTake(lock, portMAX_DELAY);
    const bool ok = write(item);
    xSemaphoreGive(lock);
    failed = !ok;
    if (!ok) ++lost;
  }
}
// Marca una lectura como entregada (seq = 0 en su ranura). Requiere lock.
void removeLocked(uint32_t seq) {
  const size_t slot = seq % capacity;
  if (seqs[slot] != seq) return;  // Ya fue reemplazada.
  const uint32_t zero = 0;
  if (writeAt(slot, 0, &zero, sizeof(zero))) {
    seqs[slot] = 0;
    --pending;
  } else {
    failed = true;
  }
}
bool offer(const Capture& item) {
  if (incoming && xQueueSend(incoming, &item, 0) == pdTRUE) return true;
  ++lost;
  return false;
}
void begin() {
  incoming = xQueueCreate(16, sizeof(Capture));
  lock = xSemaphoreCreateMutex();
  if (incoming && lock)
    xTaskCreatePinnedToCore(storageTask, "gc-store", 6144, nullptr, 2, nullptr, 0);
}
}  // namespace store

// ---------------------------------------------------------------- red
namespace net {
struct Wifi { const char* ssid; const char* password; };
const Wifi NETWORKS[] = GC_WIFI_NETWORKS;
constexpr size_t NETWORK_COUNT = sizeof(NETWORKS) / sizeof(NETWORKS[0]);
constexpr size_t POST_SIZE = 8;
constexpr char BATCH_PATH[] = "/api/v1/ingest/receiver-batch";

struct View {
  bool configured = false, wifi = false, clock = false;
  char ssid[33] = {};
  int rssi = 0, http = 0;
  uint32_t okAt = 0;
};
portMUX_TYPE viewMux = portMUX_INITIALIZER_UNLOCKED;
View view;

View snapshot() {
  portENTER_CRITICAL(&viewMux);
  View copy = view;
  portEXIT_CRITICAL(&viewMux);
  return copy;
}
void publish(const View& next) {
  portENTER_CRITICAL(&viewMux);
  view = next;
  portEXIT_CRITICAL(&viewMux);
}
// http:// solo hacia una IP privada (10/8, 172.16/12, 192.168/16): pruebas en la red local.
bool localHttp() {
  if (strncmp(GC_API_URL, "http://", 7) != 0) return false;
  const char* host = GC_API_URL + 7;
  if (!strncmp(host, "10.", 3) || !strncmp(host, "192.168.", 8)) return true;
  const int second = strncmp(host, "172.", 4) == 0 ? atoi(host + 4) : 0;
  return second >= 16 && second <= 31;
}
bool configured() {
  const bool https = strncmp(GC_API_URL, "https://", 8) == 0 && strlen(GC_API_URL) > 8;
  return (https || localHttp()) &&
         !strstr(GC_API_URL, "example.com") && strlen(GC_INGEST_KEY) >= 32 &&
         strlen(GC_FARM_ID) == 36 && NETWORK_COUNT > 0;
}

String busLine(const store::Capture& item) {
  char header[128], tail[200];
  snprintf(header, sizeof(header),
           "{\"gc_bus\":1,\"receiver\":\"%s\",\"batch\":\"%08lX-%lu\",\"readings\":[{\"packet\":",
           GC_RECEIVER_NAME, (unsigned long)item.boot, (unsigned long)item.seq);
  snprintf(tail, sizeof(tail),
           ",\"radio\":{\"rssi_dbm\":%.1f,\"snr_db\":%.1f},\"transport\":{\"delay_ms\":%lu,"
           "\"origin_gateway\":%u,\"hops\":%u,\"path\":%u}}]}",
           item.rssi10 / 10.0, item.snr10 / 10.0, (unsigned long)item.delayMs,
           item.origin, item.hops, item.path);
  String line(header);
  line.concat(reinterpret_cast<const char*>(item.packet), item.len);
  line += tail;
  return line;
}

// Agrega hasta ocho lecturas pendientes posteriores a cursor, en orden.
size_t pack(JsonArray output, uint32_t (&refs)[POST_SIZE], uint32_t& cursor,
            int64_t now, uint32_t boot) {
  size_t count = 0;
  xSemaphoreTake(store::lock, portMAX_DELAY);
  const uint32_t cap = store::capacity;
  if (store::ready && cap) {
    const uint32_t newest = store::nextSeq;
    uint32_t seq = newest > cap ? newest - cap : 1;
    if (cursor >= seq) seq = cursor + 1;
    for (; seq < newest && count < POST_SIZE; ++seq) {
      const size_t slot = seq % cap;
      if (store::seqs[slot] != seq) continue;
      store::Capture item{};
      if (!store::readSlot(slot, item)) {
        store::seqs[slot] = 0;
        --store::pending;
        ++store::lost;
        continue;
      }
      cursor = seq;
      const bool sameBoot = item.boot == boot;
      const int64_t received = item.epoch ? item.epoch :
                               sameBoot ? now - (uptimeMs() - item.uptime) : now;
      JsonObject record = output.add<JsonObject>();
      refs[count++] = seq;
      record["ref"] = seq;
      record["line"] = busLine(item);
      record["received_at"] = isoTime(received);
      record["clock"] = item.epoch ? "synced" : sameBoot ? "reconstructed" : "recovery";
    }
    if (count < POST_SIZE) cursor = 0;  // Vuelve a las no confirmadas en la próxima ronda.
  }
  xSemaphoreGive(store::lock);
  return count;
}

void addStatus(JsonObject status, int64_t now, const String& error) {
  xSemaphoreTake(store::lock, portMAX_DELAY);
  const int64_t last = store::lastCapture;
  xSemaphoreGive(store::lock);
  status["connected"] = WiFi.status() == WL_CONNECTED;
  status["wifi_ssid"] = WiFi.SSID();
  status["wifi_rssi_dbm"] = constrain(WiFi.RSSI(), -127, 0);
  status["firmware"] = FIRMWARE;
  status["buffer_capacity"] = store::ready ? store::capacity.load() : 0;
  status["captured"] = store::captured.load();
  status["pending"] = store::pending.load();
  status["delivered"] = store::delivered.load();
  status["dropped"] = store::overwritten.load() + store::rejected.load() + store::lost.load();
  status["updated_at"] = isoTime(now);
  if (last) status["last_capture"] = isoTime(last);
  if (!store::ready || store::failed) status["error"] = "Error de almacenamiento LittleFS";
  else if (error.length()) status["error"] = error;
}

// Devuelve el código HTTP (o negativo si no hubo respuesta). backlog indica
// que quedaron más lecturas para enviar de inmediato.
int upload(HTTPClient& http, uint32_t& cursor, String& error, bool& backlog, uint32_t boot) {
  const int64_t now = epochMs();
  JsonDocument request;
  request["version"] = 1;
  addStatus(request["status"].to<JsonObject>(), now, error);
  JsonArray records = request["records"].to<JsonArray>();
  uint32_t refs[POST_SIZE]{};
  const size_t count = pack(records, refs, cursor, now, boot);
  backlog = count == POST_SIZE;
  String body;
  serializeJson(request, body);
  request.clear();
  const int code = http.POST(body);
  if (code != 200) {
    error = code > 0 ? String("Entrega HTTP ") + code : String("Servidor sin respuesta");
    return code;
  }
  JsonDocument response;
  if (deserializeJson(response, http.getString()) || !response["records"].is<JsonArray>()) {
    error = "Confirmacion de API invalida";
    return -1;
  }
  unsigned kept = 0;
  xSemaphoreTake(store::lock, portMAX_DELAY);
  for (JsonObjectConst receipt : response["records"].as<JsonArrayConst>()) {
    const uint32_t ref = receipt["ref"] | uint32_t(0);
    bool mine = false;
    for (size_t i = 0; i < count; ++i) mine |= ref && refs[i] == ref;
    if (!mine) continue;
    const auto ids = receipt["ids"].as<JsonArrayConst>();
    const int rejectedCode = receipt["error"] | 0;
    if (ids.size() >= 1) {
      store::removeLocked(ref);
      ++store::delivered;
    } else if (rejectedCode == 422 || rejectedCode == 409) {
      store::removeLocked(ref);  // Rechazo permanente: no bloquea la cola.
      ++store::rejected;
    } else {
      ++kept;  // 403 u otro: se reintenta (p. ej. collar aún no aprobado).
    }
  }
  xSemaphoreGive(store::lock);
  error = kept ? String(kept) + " lecturas en espera de autorizacion" : String();
  return code;
}

void networkTask(void* arg) {
  const uint32_t boot = uint32_t(uintptr_t(arg));
  View state;
  state.configured = configured();
  publish(state);
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  NetworkClientSecure secure;
  secure.useBuiltinCACertBundle();
  NetworkClient plain;
  NetworkClient& client = localHttp() ? plain : secure;
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(8000);
  http.setReuse(true);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.setUserAgent("GeoCattle-Nube-T3/1");
  bool begun = false, online = false;
  size_t candidate = 0;
  uint32_t cursor = 0, wifiAt = 0, nextPost = 0, retryMs = 5000;
  String error;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(100));
    const uint32_t now = millis();
    const bool connected = WiFi.status() == WL_CONNECTED;
    state.wifi = connected;
    state.clock = epochMs() != 0;
    if (connected) {
      strlcpy(state.ssid, WiFi.SSID().c_str(), sizeof(state.ssid));
      state.rssi = WiFi.RSSI();
    }
    publish(state);
    if (!connected) {
      if (online) {
        http.end();
        client.stop();
        begun = online = false;
        wifiAt = now;
      }
      if (NETWORK_COUNT && int32_t(now - wifiAt) >= 0) {
        const Wifi& network = NETWORKS[candidate++ % NETWORK_COUNT];
        WiFi.disconnect();
        WiFi.begin(network.ssid, network.password);
        strlcpy(state.ssid, network.ssid, sizeof(state.ssid));
        wifiAt = now + 15000;
      }
      continue;
    }
    if (!online) {
      configTime(0, 0, "time.cloudflare.com", "pool.ntp.org");
      online = true;
      nextPost = now;
    }
    if (!state.configured || !state.clock || store::preparing || int32_t(now - nextPost) < 0) continue;
    if (!begun) {
      begun = http.begin(client, String(GC_API_URL) + BATCH_PATH);
      if (!begun) {
        nextPost = now + 15000;
        continue;
      }
    }
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Ingest-Key", GC_INGEST_KEY);
    http.addHeader("X-Farm-ID", GC_FARM_ID);
    if (strlen(GC_ACCESS_ID)) {
      http.addHeader("CF-Access-Client-Id", GC_ACCESS_ID);
      http.addHeader("CF-Access-Client-Secret", GC_ACCESS_SECRET);
    }
    bool backlog = false;
    const int code = upload(http, cursor, error, backlog, boot);
    state.http = code;
    if (code == 200) {
      state.okAt = millis();
      retryMs = 5000;
      nextPost = millis() + (backlog ? 1000 : store::pending ? 5000 : 15000);
    } else {
      http.end();
      client.stop();
      begun = false;
      cursor = 0;  // Reintenta desde la lectura más antigua.
      nextPost = millis() + retryMs;
      retryMs = min(retryMs * 2, uint32_t(60000));
    }
    publish(state);
  }
}
void begin(uint32_t boot) {
  xTaskCreatePinnedToCore(networkTask, "gc-net", 16384,
                          reinterpret_cast<void*>(uintptr_t(boot)), 1, nullptr, 0);
}
}  // namespace net

// ---------------------------------------------------------------- radio
SX1276 radio = new Module(18, 26, 23, RADIOLIB_NC, SPI,
                         SPISettings(2000000, MSBFIRST, SPI_MODE0));
Adafruit_SSD1306 screen(128, 64, &Wire, -1);

constexpr uint32_t MAX_DELAY = 1800000;
constexpr size_t MAX_RECORDS = 4, RECORD_HEADER = 13, SEEN_SIZE = 512;

Key seen[SEEN_SIZE];
size_t nextSeen = 0;

gc::Reassembly assembly;
uint8_t rxFrame[gc::MAX_RF];
volatile bool rxReady = false, irqEnabled = false;
bool listening = false, screenReady = false;
uint32_t bootId = 0, lastRxAttempt = 0, lastScreen = 0, lastState = 0;
uint32_t frames = 0, readings = 0, duplicates = 0, direct = 0, invalid = 0;
uint32_t heardAt[3] = {};
// Raíz de respaldo: activa solo tras 25 s sin pruebas de otra raíz.
constexpr uint32_t ROOT_QUIET_MS = 25000, ROOT_LEASE_MS = 20000, BEACON_MS = 5000;
bool rootActive = false;
uint32_t quietSince = 0, rootSequence = 0, lastBeacon = 0, beacons = 0, acks = 0;
uint8_t txFrame[gc::MAX_RF];
char lastCollar[17] = {};
uint8_t lastOrigin = 0;
uint32_t lastReadingAt = 0;

uint8_t bits(uint8_t value) {
  uint8_t n = 0;
  for (; value; value >>= 1) n += value & 1;
  return n;
}
bool sameKey(const Key& a, const Key& b) {
  return a.q == b.q && strcmp(a.collar, b.collar) == 0 && strcmp(a.session, b.session) == 0;
}
bool alreadySeen(const Key& key) {
  for (const auto& item : seen)
    if (item.collar[0] && sameKey(item, key)) return true;
  return false;
}
void remember(const Key& key) {
  seen[nextSeen] = key;
  nextSeen = (nextSeen + 1) % SEEN_SIZE;
}

// Misma validación JSON V5 que la T3 base.
bool parseIdentity(const uint8_t* raw, size_t len, Key& key) {
  if (!len || len > 255) return false;
  JsonDocument d;
  if (deserializeJson(d, raw, len)) return false;
  if (!d.is<JsonObject>() || !d["v"].is<int>() || d["v"].as<int>() != 5 ||
      !d["id"].is<const char*>() || !d["s"].is<const char*>() ||
      !d["q"].is<uint32_t>() || !d["u"].is<uint32_t>() || !d["p"].is<uint32_t>() ||
      !d["g"].is<JsonArray>() || d["g"].size() != 5 ||
      !d["a"].is<JsonArray>() || d["a"].size() != 3 ||
      !d["m"].is<JsonArray>() || d["m"].size() != 2 ||
      !d["b"].is<JsonArray>() || d["b"].size() != 5 ||
      !d["f"].is<int>() || !d["e"].is<int>() ||
      d.as<JsonObjectConst>()["t"].isUnbound()) return false;
  const uint32_t period = d["p"];
  if (period < 30000 || period > 45000) return false;
  const char* id = d["id"];
  const char* session = d["s"];
  const size_t size = strlen(id);
  if (size < 1 || size > 16 || strlen(session) != 16) return false;
  for (size_t i = 0; i < size; i++) {
    const unsigned char c = id[i];
    if (!isalnum(c) && c != '_' && c != '-') return false;
  }
  for (size_t i = 0; i < 16; i++)
    if (!isxdigit(static_cast<unsigned char>(session[i]))) return false;
  strlcpy(key.collar, id, sizeof(key.collar));
  strlcpy(key.session, session, sizeof(key.session));
  key.q = d["q"];
  return true;
}

// Guarda una lectura nueva; la misma lectura oída directa y por gateway se guarda una vez.
// En un namespace para que Arduino no genere su prototipo antes de store::Capture.
namespace rx {
// false solo si la cola de escritura está llena (el gateway debe reintentar).
bool keep(store::Capture& r, const Key& key, uint32_t now) {
  if (alreadySeen(key)) { ++duplicates; return true; }
  r.boot = bootId;
  r.uptime = uptimeMs();
  r.epoch = epochMs();
  if (!store::offer(r)) return false;
  remember(key);
  ++readings;
  strlcpy(lastCollar, key.collar, sizeof(lastCollar));
  lastOrigin = r.origin;
  lastReadingAt = now;
  Serial.printf("# lectura %s q=%lu %s%u saltos=%u retardo=%lums\n", key.collar,
                (unsigned long)key.q, r.origin ? "gateway=" : "directa nodo=", r.origin, r.hops,
                (unsigned long)r.delayMs);
  return true;
}
}  // namespace rx

// Toma un lote de gateway completo con las reglas de la T3 base.
// Devuelve el estado de ACK de la base: 0 aceptado, 1 sin espacio, 3 inválido.
uint8_t takeBatch(const uint8_t* bytes, size_t len, uint32_t elapsed, uint32_t now) {
  if (!len || bytes[0] < 1 || bytes[0] > MAX_RECORDS || elapsed > MAX_DELAY) {
    ++invalid;
    return 3;
  }
  store::Capture items[MAX_RECORDS];
  Key keys[MAX_RECORDS];
  const uint8_t count = bytes[0];
  size_t pos = 1;
  for (uint8_t i = 0; i < count; i++) {
    if (pos + RECORD_HEADER > len) { ++invalid; return 3; }
    auto& r = items[i];
    r.len = gc::read16(bytes + pos);
    const uint32_t age = gc::read32(bytes + pos + 2);
    r.origin = bytes[pos + 6];
    r.path = bytes[pos + 7];
    r.hops = bytes[pos + 8];
    r.rssi10 = int16_t(gc::read16(bytes + pos + 9));
    r.snr10 = int16_t(gc::read16(bytes + pos + 11));
    pos += RECORD_HEADER;
    if (!r.len || r.len > 255 || pos + r.len > len || age > MAX_DELAY - elapsed ||
        r.origin < 1 || r.origin > 2 || (r.path & ~6U) || !(r.path & (1U << r.origin)) ||
        r.hops != bits(r.path) || r.hops < 1 || r.hops > 2 ||
        r.rssi10 < -2000 || r.rssi10 > 200 || r.snr10 < -1000 || r.snr10 > 1000) {
      ++invalid;
      return 3;
    }
    memcpy(r.packet, bytes + pos, r.len);
    pos += r.len;
    if (!parseIdentity(r.packet, r.len, keys[i])) { ++invalid; return 3; }
    r.delayMs = age + elapsed;
  }
  if (pos != len) { ++invalid; return 3; }

  bool full = false;
  for (uint8_t i = 0; i < count; i++) {
    bool repeated = false;
    for (uint8_t j = 0; j < i; j++) repeated |= sameKey(keys[i], keys[j]);
    if (repeated) ++duplicates;
    else full |= !rx::keep(items[i], keys[i], now);
  }
  return full ? 1 : 0;
}

// Collar oído directo, como receiveRaw de la T3 base: origen 0, sin saltos.
void takeDirect(const uint8_t* raw, size_t len, float rssi, float snr, uint32_t now) {
  store::Capture r{};
  Key key;
  if (!len || len > 255 || !isfinite(rssi) || !isfinite(snr) ||
      !parseIdentity(raw, len, key)) {
    ++invalid;
    return;
  }
  r.len = len;
  memcpy(r.packet, raw, len);
  r.rssi10 = int16_t(constrain(lroundf(rssi * 10), -2000L, 200L));
  r.snr10 = int16_t(constrain(lroundf(snr * 10), -1000L, 1000L));
  ++direct;
  rx::keep(r, key, now);
}

void IRAM_ATTR onReceive() {
  if (irqEnabled) rxReady = true;
}
void receiveAgain() {
  irqEnabled = false;
  rxReady = false;
  lastRxAttempt = millis();
  irqEnabled = true;
  listening = radio.startReceive() == RADIOLIB_ERR_NONE;
  if (!listening) irqEnabled = false;
}
bool sendFrame(const gc::Header& h, const uint8_t* data, size_t len) {
  if (len + gc::HEADER_SIZE > gc::MAX_RF || !gc::encodeHeader(h, txFrame, sizeof(txFrame)))
    return false;
  if (len) memcpy(txFrame + gc::HEADER_SIZE, data, len);
  irqEnabled = false;
  rxReady = false;
  listening = false;
  const bool ok = radio.transmit(txFrame, gc::HEADER_SIZE + len) == RADIOLIB_ERR_NONE;
  receiveAgain();
  return ok;
}
// Baliza de raíz igual a la de la T3 base: época = boot, rango 0, camino vacío.
void sendBeacon(uint32_t now) {
  uint8_t data[14];
  gc::write32(data, bootId);
  gc::write32(data + 4, ++rootSequence);
  gc::write32(data + 8, 0);
  data[12] = 0;
  data[13] = 0;
  gc::Header h{};
  h.kind = gc::Beacon; h.src = 0; h.dst = gc::BROADCAST; h.boot = bootId;
  h.number = rootSequence; h.parts = 1; h.total = sizeof(data);
  h.checksum = gc::crc32(data, sizeof(data));
  if (sendFrame(h, data, sizeof(data))) ++beacons;
  lastBeacon = now;
}
void sendAck(const gc::Header& data, uint8_t status) {
  gc::Header h{};
  h.kind = gc::Ack; h.src = 0; h.dst = data.src; h.boot = data.boot;
  h.number = data.number; h.checksum = data.checksum; h.index = status;
  delay(5 + esp_random() % 20);
  if (sendFrame(h, nullptr, 0)) ++acks;
}
// Otra raíz a la vista: baliza vigente de una época ajena (del nodo 0 o de un gateway que la sigue).
void watchRoot(const gc::Header& h, const uint8_t* data, size_t len, uint32_t now) {
  if (h.kind != gc::Beacon || len != 14 || gc::crc32(data, len) != h.checksum) return;
  const uint32_t epoch = gc::read32(data), age = gc::read32(data + 8);
  if (!epoch || epoch == bootId || age >= ROOT_LEASE_MS) return;
  quietSince = now;
  if (rootActive) {
    rootActive = false;
    Serial.printf("# otra raiz %08lX a la vista: vuelvo a solo escuchar\n", (unsigned long)epoch);
  }
}
void rootTick(uint32_t now) {
  if (!GC_ROOT_FALLBACK || !listening) return;
  if (!rootActive && now - quietSince >= ROOT_QUIET_MS) {
    rootActive = true;
    lastBeacon = now - BEACON_MS;
    Serial.printf("# sin base T3: raiz de respaldo boot=%08lX\n", (unsigned long)bootId);
  }
  if (rootActive && now - lastBeacon >= BEACON_MS) sendBeacon(now);
}

void handleFrame() {
  irqEnabled = false;
  rxReady = false;
  listening = false;
  if (radio.standby() != RADIOLIB_ERR_NONE) { ++invalid; receiveAgain(); return; }
  const size_t len = radio.getPacketLength();
  if (!len || len > sizeof(rxFrame)) { ++invalid; receiveAgain(); return; }
  const int16_t result = radio.readData(rxFrame, len);
  const float rssi = radio.getRSSI(), snr = radio.getSNR();
  receiveAgain();
  if (result != RADIOLIB_ERR_NONE) { ++invalid; return; }
  ++frames;
  const uint32_t now = millis();
  if (rxFrame[0] == '{') { takeDirect(rxFrame, len, rssi, snr, now); return; }
  gc::Header h{};
  if (!gc::decodeHeader(rxFrame, len, h)) return;
  heardAt[h.src] = now ? now : 1;
  const uint8_t* data = rxFrame + gc::HEADER_SIZE;
  const size_t size = len - gc::HEADER_SIZE;
  watchRoot(h, data, size, now);
  if (h.kind != gc::Data) return;
  const auto assembled = assembly.ingest(h, data, size, now);
  if (assembled == gc::Invalid) { ++invalid; return; }
  if (assembled != gc::Complete) return;
  const uint8_t status = takeBatch(assembly.completedData(), assembly.completedSize(),
                                   assembly.completedElapsed(), now);
  assembly.clearCompleted();
  // Como la base: el ACK confirma custodia en la cola local, no la entrega al servidor.
  if (rootActive && h.dst == 0) sendAck(h, status);
}

// ---------------------------------------------------------------- pantalla
String ago(uint32_t at, uint32_t now) {
  if (!at) return "--";
  const uint32_t s = (now - at) / 1000;
  if (s < 100) return String(s) + "s";
  if (s < 6000) return String(s / 60) + "m";
  return ">99m";
}
void startScreen() {
  Wire.begin(21, 22);
  Wire.setClock(400000);
  Wire.setTimeOut(50);
  for (uint8_t address : {uint8_t(0x3C), uint8_t(0x3D)}) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0 && screen.begin(SSD1306_SWITCHCAPVCC, address)) {
      screenReady = true;
      break;
    }
  }
  if (!screenReady) return;
  screen.clearDisplay();
  screen.setTextColor(SSD1306_WHITE);
  screen.setTextSize(1);
  screen.setCursor(0, 0);
  screen.println("GeoCattle NUBE T3");
  screen.println("Iniciando...");
  screen.display();
}
void drawScreen(uint32_t now) {
  if (!screenReady) return;
  const net::View v = net::snapshot();
  char line[24];
  screen.clearDisplay();
  screen.setCursor(0, 0);
  screen.println("GeoCattle NUBE T3");
  if (v.wifi) snprintf(line, sizeof(line), "WiFi OK %ddBm", v.rssi);
  else snprintf(line, sizeof(line), "WiFi buscando...");
  screen.println(line);
  snprintf(line, sizeof(line), "%.21s", v.ssid[0] ? v.ssid : "(sin redes)");
  screen.println(line);
  if (!v.configured) snprintf(line, sizeof(line), "Nube: falta config");
  else if (!v.wifi) snprintf(line, sizeof(line), "Nube: sin WiFi");
  else if (!v.clock) snprintf(line, sizeof(line), "Nube: esperando hora");
  else if (v.http == 200) snprintf(line, sizeof(line), "Nube OK hace %s", ago(v.okAt, now).c_str());
  else if (v.http > 0) snprintf(line, sizeof(line), "Nube ERROR HTTP %d", v.http);
  else if (v.http < 0) snprintf(line, sizeof(line), "Nube sin respuesta");
  else snprintf(line, sizeof(line), "Nube conectando...");
  screen.println(line);
  if (store::preparing) snprintf(line, sizeof(line), "Memoria preparando");
  else if (!store::ready || store::failed) snprintf(line, sizeof(line), "Memoria ERROR");
  else snprintf(line, sizeof(line), "Cola %lu/%lu%s", (unsigned long)store::pending.load(),
                (unsigned long)store::capacity.load(),
                store::pending >= store::capacity ? " LLENA" : "");
  screen.println(line);
  snprintf(line, sizeof(line), "Rx %lu Env %lu", (unsigned long)store::captured.load(),
           (unsigned long)store::delivered.load());
  screen.println(line);
  if (lastCollar[0] && lastOrigin) snprintf(line, sizeof(line), "%.11s G%u %s", lastCollar, lastOrigin,
                                            ago(lastReadingAt, now).c_str());
  else if (lastCollar[0]) snprintf(line, sizeof(line), "%.11s Dir %s", lastCollar,
                                   ago(lastReadingAt, now).c_str());
  else snprintf(line, sizeof(line), "Sin lecturas aun");
  screen.println(line);
  snprintf(line, sizeof(line), "%s%s G1 %s G2 %s", rootActive ? "R" : "B",
           rootActive ? "" : ago(heardAt[0], now).c_str(),
           ago(heardAt[1], now).c_str(), ago(heardAt[2], now).c_str());
  screen.println(line);
  screen.display();
}

void critical(int16_t result, const char* text) {
  if (result == RADIOLIB_ERR_NONE) return;
  if (screenReady) {
    screen.clearDisplay();
    screen.setCursor(0, 0);
    screen.printf("ERROR %s\n%d", text, result);
    screen.display();
  }
  while (true) {
    Serial.printf("# ERROR %s: %d\n", text, result);
    delay(3000);
  }
}

void setup() {
  Serial.begin(115200);
  delay(600);
  bootId = esp_random();
  if (!bootId) bootId = 1;
  startScreen();
  store::begin();
  net::begin(bootId);

  SPI.begin(5, 19, 27, 18);
  ConfigLoRa_t config;
  config.frequency = 915.5;
  config.bandwidth = 125;
  config.spreadingFactor = 7;
  config.codingRate = 5;
  config.syncWord = 0x12;
  config.power = 10;
  config.preambleLength = 8;
  critical(radio.begin(config), "iniciar radio");
  critical(radio.setCRC(true), "CRC");
  critical(radio.explicitHeader(), "cabecera explicita");
  critical(radio.invertIQ(false), "IQ");
  radio.setPacketReceivedAction(onReceive);
  receiveAgain();
  quietSince = millis();
  enableLoopWDT();
  Serial.printf("# GEOCATTLE NUBE boot=%08lX raiz de respaldo=%s; 915.5 MHz; config=%s\n",
                (unsigned long)bootId, GC_ROOT_FALLBACK ? "si" : "no",
                net::configured() ? "completa" : "incompleta");
}

void loop() {
  uint32_t now = millis();
  if (!listening && now - lastRxAttempt >= 1000) receiveAgain();
  if (listening && rxReady) handleFrame();
  now = millis();
  if (!rxReady) rootTick(now);
  now = millis();
  if (!rxReady && now - lastScreen >= 1000) {
    lastScreen = now;
    drawScreen(now);
  }
  if (now - lastState >= 10000) {
    lastState = now;
    const net::View v = net::snapshot();
    Serial.printf("# nube wifi=%s http=%d cola=%lu/%lu capturadas=%lu enviadas=%lu "
                  "rechazadas=%lu sobrescritas=%lu perdidas=%lu tramas=%lu directas=%lu "
                  "duplicadas=%lu invalidas=%lu raiz=%s balizas=%lu acks=%lu\n",
                  v.wifi ? "si" : "no", v.http, (unsigned long)store::pending.load(),
                  (unsigned long)store::capacity.load(), (unsigned long)store::captured.load(),
                  (unsigned long)store::delivered.load(), (unsigned long)store::rejected.load(),
                  (unsigned long)store::overwritten.load(), (unsigned long)store::lost.load(),
                  (unsigned long)frames, (unsigned long)direct, (unsigned long)duplicates,
                  (unsigned long)invalid, rootActive ? "si" : "no", (unsigned long)beacons,
                  (unsigned long)acks);
  }
  delay(1);
}
