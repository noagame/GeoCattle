#pragma once

#include <HTTPClient.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <atomic>
#include <esp_timer.h>
#include <stddef.h>
#include <sys/time.h>

namespace gccloud {
constexpr size_t CAPACITY = 256;
constexpr size_t POST_SIZE = 8;
constexpr size_t COMMAND_SIZE = 6144;
constexpr int64_t FIRST_EPOCH = 1704067200;  // 2024-01-01 UTC.
constexpr char VERSION[] = "base-t3-cloud-1";
constexpr char BATCH_PATH[] = "/api/v1/ingest/receiver-batch";

struct Capture {
  uint64_t seq = 0;
  uint64_t boot = 0;
  int64_t uptime = 0;
  int64_t epoch = 0;
  uint32_t delayMs = 0;
  int16_t rssi10 = 0, snr10 = 0;
  uint8_t origin = 0, hops = 0, path = 0;
  uint16_t len = 0;
  char packet[255]{};
  uint32_t crc = 0;
};
struct Command { char text[COMMAND_SIZE]; };
struct Reply { char text[256]; };
struct ClockAnchor { uint64_t boot = 0; int64_t offset = 0; };

QueueHandle_t incoming = nullptr, commands = nullptr, replies = nullptr;
SemaphoreHandle_t fsLock = nullptr;
std::atomic<bool> enabled{false};
std::atomic<uint32_t> dropped{0}, persisted{0}, delivered{0};
std::atomic<bool> storageError{false};
uint64_t slots[CAPACITY]{};
uint64_t nextSeq = 1, stationBoot = 0;
bool mounted = false;  // All filesystem state is accessed under fsLock.
int64_t lastCaptureEpoch = 0;

int64_t epochMs() {
  timeval now{};
  gettimeofday(&now, nullptr);
  return now.tv_sec >= FIRST_EPOCH ? int64_t(now.tv_sec) * 1000 + now.tv_usec / 1000 : 0;
}

String isoTime(int64_t epoch) {
  const time_t seconds = epoch / 1000;
  tm utc{};
  gmtime_r(&seconds, &utc);
  char iso[32];
  strftime(iso, sizeof(iso), "%Y-%m-%dT%H:%M:%SZ", &utc);
  return String(iso);
}

void slotPath(size_t slot, char (&path)[16]) {
  snprintf(path, sizeof(path), "/q%03u", unsigned(slot));
}

uint32_t checksum(const Capture& item) {
  return gc::crc32(reinterpret_cast<const uint8_t*>(&item), offsetof(Capture, crc));
}

bool loadSlot(size_t slot, Capture& item) {
  char path[16];
  slotPath(slot, path);
  File file = LittleFS.open(path, FILE_READ);
  return file && file.size() == sizeof(item) &&
         file.read(reinterpret_cast<uint8_t*>(&item), sizeof(item)) == sizeof(item) &&
         item.seq && item.seq % CAPACITY == slot && item.len && item.len <= sizeof(item.packet) &&
         item.crc == checksum(item);
}

void recoverQueue() {
  if (LittleFS.exists("/pending")) LittleFS.remove("/pending");
  for (size_t slot = 0; slot < CAPACITY; ++slot) {
    Capture item{};
    if (!loadSlot(slot, item)) continue;
    slots[slot] = item.seq;
    if (item.seq >= nextSeq) nextSeq = item.seq + 1;
    if (item.epoch > lastCaptureEpoch) lastCaptureEpoch = item.epoch;
  }
}

bool writeCapture(Capture item) {
  // Prefer an empty slot. When all slots are occupied replace the oldest
  // atomically, so a power cut leaves the old or the new validated record.
  if (!mounted) return false;
  const size_t firstSlot = nextSeq % CAPACITY;
  size_t chosen = firstSlot;
  for (size_t offset = 0; offset < CAPACITY; ++offset) {
    const size_t slot = (firstSlot + offset) % CAPACITY;
    if (!slots[slot]) {
      chosen = slot;
      break;
    }
    if (slots[slot] < slots[chosen]) chosen = slot;
  }
  item.seq = nextSeq + (chosen + CAPACITY - firstSlot) % CAPACITY;
  const size_t slot = item.seq % CAPACITY;
  char path[16];
  slotPath(slot, path);
  item.crc = checksum(item);
  File staging = LittleFS.open("/pending", FILE_WRITE);
  if (!staging) return false;
  const bool written = staging.write(reinterpret_cast<const uint8_t*>(&item), sizeof(item)) == sizeof(item);
  staging.flush();
  staging.close();
  if (!written || !LittleFS.rename("/pending", path)) return false;
  if (slots[slot]) ++dropped;
  slots[slot] = item.seq;
  nextSeq = item.seq + 1;
  if (item.epoch > lastCaptureEpoch) lastCaptureEpoch = item.epoch;
  ++persisted;
  return true;
}

bool offer(const Record& record) {
  if (!enabled || !incoming) return false;
  Capture item{};
  item.boot = stationBoot;
  item.uptime = esp_timer_get_time() / 1000;
  item.epoch = epochMs();
  item.delayMs = record.age;
  item.rssi10 = record.rssi10;
  item.snr10 = record.snr10;
  item.origin = record.origin;
  item.hops = record.hops;
  item.path = record.path;
  item.len = record.len;
  memcpy(item.packet, record.raw, record.len);
  if (xQueueSend(incoming, &item, 0) == pdTRUE) return true;
  ++dropped;
  return false;
}

void storageTask(void*) {
  xSemaphoreTake(fsLock, portMAX_DELAY);
  mounted = LittleFS.begin(false);
  if (mounted) recoverQueue();
  xSemaphoreGive(fsLock);
  Capture item{};
  for (;;) {
    if (xQueueReceive(incoming, &item, portMAX_DELAY) != pdTRUE) continue;
    xSemaphoreTake(fsLock, portMAX_DELAY);
    const bool written = writeCapture(item);
    xSemaphoreGive(fsLock);
    storageError = !written;
    if (!written) ++dropped;
    vTaskDelay(1);
  }
}

String boardEui() {
  char identity[13];
  snprintf(identity, sizeof(identity), "%012llX", (unsigned long long)ESP.getEfuseMac());
  return String(identity);
}

void respond(const char* action, bool ok) {
  Reply response{};
  xSemaphoreTake(fsLock, portMAX_DELAY);
  unsigned pending = 0;
  for (auto seq : slots) pending += seq != 0;
  const bool ready = mounted;
  xSemaphoreGive(fsLock);
  snprintf(response.text, sizeof(response.text),
           "#GC_CLOUD {\"version\":1,\"action\":\"%s\",\"ok\":%s,\"eui\":\"%s\","
           "\"firmware\":\"%s\",\"buffer_ready\":%s,\"pending\":%u,\"wifi\":%s}",
           action, ok ? "true" : "false", boardEui().c_str(), VERSION,
           ready ? "true" : "false", pending, WiFi.status() == WL_CONNECTED ? "true" : "false");
  xQueueOverwrite(replies, &response);
}

bool validWifi(JsonDocument& wifi) {
  if (!wifi.is<JsonArray>() || wifi.size() > 3) return false;
  for (JsonObjectConst network : wifi.as<JsonArrayConst>()) {
    const char* ssid = network["ssid"];
    const char* password = network["password"];
    if (!ssid || !strlen(ssid) || strlen(ssid) > 32 || !password || strlen(password) > 63) return false;
  }
  return true;
}

bool validCloud(JsonDocument& cloud) {
  const String url = cloud["url"] | "";
  const String key = cloud["key"] | "";
  const String farm = cloud["farm"] | "";
  const String ca = cloud["ca"] | "";
  const String accessId = cloud["access_id"] | "";
  const String accessSecret = cloud["access_secret"] | "";
  if (!url.startsWith("https://") || url.length() <= 8 || url.length() > 200 ||
      url.indexOf('/', 8) >= 0 || url.indexOf('@') >= 0 || url.indexOf('?') >= 0 ||
      url.indexOf('#') >= 0 || url.indexOf('\\') >= 0 || url.indexOf(' ') >= 0 ||
      key.length() < 32 || key.length() > 120 || farm.length() != 36 ||
      !ca.startsWith("-----BEGIN CERTIFICATE-----") || ca.length() > 3900 ||
      bool(accessId.length()) != bool(accessSecret.length()) || accessId.length() > 200 ||
      accessSecret.length() > 512) return false;
  for (auto field : {key, farm, accessId, accessSecret})
    if (field.indexOf('\r') >= 0 || field.indexOf('\n') >= 0) return false;
  return true;
}

bool pendingCaptures() {
  if (uxQueueMessagesWaiting(incoming)) return true;
  bool pending = false;
  xSemaphoreTake(fsLock, portMAX_DELAY);
  for (auto seq : slots) pending |= seq != 0;
  xSemaphoreGive(fsLock);
  return pending;
}

// Returns true if WiFi or HTTPS settings changed.
bool handleCommand(Command& input, Preferences& nvs, JsonDocument& wifi, JsonDocument& cloud) {
  char* action = input.text;
  char* identity = strchr(action, ' ');
  if (identity) *identity++ = 0;
  if (strcmp(action, "GEOCATTLE_CLOUD_IDENTIFY_V1") == 0) {
    respond("identify", true);
    return false;
  }
  char* value = identity ? strchr(identity, ' ') : nullptr;
  if (value) *value++ = 0;
  if (!identity || boardEui() != identity) {
    respond("identity", false);
    return false;
  }
  if (strcmp(action, "GEOCATTLE_CLOUD_STATUS_V1") == 0) {
    respond("status", true);
  } else if (strcmp(action, "GEOCATTLE_INIT_CLOUD_BUFFER_V1") == 0) {
    xSemaphoreTake(fsLock, portMAX_DELAY);
    if (!mounted) {
      mounted = LittleFS.begin(true);
      if (mounted) recoverQueue();
    }
    const bool ok = mounted;
    xSemaphoreGive(fsLock);
    if (ok) storageError = false;
    respond("buffer", ok);
  } else if (strcmp(action, "GEOCATTLE_SET_TIME_V1") == 0) {
    const int64_t timestamp = value ? strtoll(value, nullptr, 10) : 0;
    const timeval timeValue{time_t(timestamp), 0};
    const bool ok = timestamp >= FIRST_EPOCH && timestamp < 4102444800LL &&
                    settimeofday(&timeValue, nullptr) == 0;
    respond("time", ok);
  } else if (strcmp(action, "GEOCATTLE_SET_WIFI_V1") == 0) {
    JsonDocument proposed;
    const bool ok = value && !deserializeJson(proposed, static_cast<const char*>(value)) &&
                    validWifi(proposed) && nvs.putString("wifi", value) == strlen(value);
    if (ok) wifi = proposed;
    respond("wifi", ok);
    return ok;
  } else if (strcmp(action, "GEOCATTLE_SET_CLOUD_V1") == 0) {
    JsonDocument proposed;
    bool ok = value && !deserializeJson(proposed, static_cast<const char*>(value)) && validCloud(proposed);
    if (ok && enabled) {
      const String oldUrl = cloud["url"] | "";
      const String oldFarm = cloud["farm"] | "";
      const String newUrl = proposed["url"] | "";
      const String newFarm = proposed["farm"] | "";
      // Freeze enqueue while testing a change of destination.
      if (oldUrl != newUrl || oldFarm != newFarm) {
        enabled = false;
        ok = !pendingCaptures();
      }
    }
    if (ok) ok = nvs.putString("cloud", value) == strlen(value);
    if (ok) cloud = proposed;
    enabled = validCloud(cloud);
    respond("cloud", ok);
    return ok;
  }
  return false;
}

String busLine(const Capture& item) {
  char header[110], radioFields[190];
  snprintf(header, sizeof(header),
           "{\"gc_bus\":1,\"receiver\":\"BASE01\",\"batch\":\"%08lX-%lu\",\"readings\":[{\"packet\":",
           (unsigned long)uint32_t(item.boot), (unsigned long)uint32_t(item.seq));
  snprintf(radioFields, sizeof(radioFields),
           ",\"radio\":{\"rssi_dbm\":%.1f,\"snr_db\":%.1f},\"transport\":{\"delay_ms\":%lu,"
           "\"origin_gateway\":%u,\"hops\":%u,\"path\":%u}}]}",
           item.rssi10 / 10.0, item.snr10 / 10.0, (unsigned long)item.delayMs, item.origin, item.hops, item.path);
  String line(header);
  line.concat(item.packet, item.len);
  line += radioFields;
  return line;
}

size_t pack(JsonArray output, uint64_t (&refs)[POST_SIZE], uint64_t& cursor, int64_t now,
            const ClockAnchor& previous) {
  size_t count = 0;
  xSemaphoreTake(fsLock, portMAX_DELAY);
  while (mounted && count < POST_SIZE) {
    size_t chosen = CAPACITY;
    for (size_t slot = 0; slot < CAPACITY; ++slot)
      if (slots[slot] > cursor && (chosen == CAPACITY || slots[slot] < slots[chosen])) chosen = slot;
    if (chosen == CAPACITY) {
      cursor = 0;  // Resume older unconfirmed records on the next transmission.
      break;
    }
    cursor = slots[chosen];
    Capture item{};
    if (!loadSlot(chosen, item)) {
      storageError = true;
      continue;
    }
    const bool sameBoot = item.boot == stationBoot;
    const bool calibrated = previous.boot && item.boot == previous.boot;
    const int64_t estimate = sameBoot ? now - (esp_timer_get_time() / 1000 - item.uptime) :
                             calibrated ? previous.offset + item.uptime : now;
    const int64_t received = item.epoch ? item.epoch : estimate;
    JsonObject record = output.add<JsonObject>();
    refs[count++] = item.seq;
    record["ref"] = item.seq;
    record["line"] = busLine(item);
    record["received_at"] = isoTime(received);
    record["clock"] = item.epoch ? "synced" : sameBoot || calibrated ? "reconstructed" : "recovery";
  }
  xSemaphoreGive(fsLock);
  return count;
}

bool confirm(uint64_t reference) {
  xSemaphoreTake(fsLock, portMAX_DELAY);
  const size_t slot = reference % CAPACITY;
  char path[16];
  slotPath(slot, path);
  const bool replaced = slots[slot] != reference;
  const bool removed = !replaced && LittleFS.remove(path);
  if (removed) {
    slots[slot] = 0;
    ++delivered;
  }
  xSemaphoreGive(fsLock);
  return replaced || removed;
}

void addStatus(JsonObject status, int64_t now, const String& error) {
  unsigned pending = 0;
  xSemaphoreTake(fsLock, portMAX_DELAY);
  for (auto seq : slots) pending += seq != 0;
  const bool ready = mounted;
  const auto last = lastCaptureEpoch;
  xSemaphoreGive(fsLock);
  status["connected"] = WiFi.status() == WL_CONNECTED;
  status["wifi_ssid"] = WiFi.SSID();
  status["wifi_rssi_dbm"] = constrain(WiFi.RSSI(), -127, 0);
  status["firmware"] = VERSION;
  status["buffer_capacity"] = ready ? CAPACITY : 0;
  status["captured"] = persisted.load();
  status["pending"] = pending;
  status["delivered"] = delivered.load();
  status["dropped"] = dropped.load();
  status["updated_at"] = isoTime(now);
  if (last) status["last_capture"] = isoTime(last);
  if (!ready || storageError) status["error"] = "Error de almacenamiento LittleFS";
  else if (error.length()) status["error"] = error;
}

bool upload(HTTPClient& http, uint64_t& cursor, String& error, bool& hasBacklog,
            const ClockAnchor& previous) {
  const int64_t now = epochMs();
  JsonDocument request;
  request["version"] = 1;
  addStatus(request["status"].to<JsonObject>(), now, error);
  JsonArray records = request["records"].to<JsonArray>();
  uint64_t refs[POST_SIZE]{};
  const size_t count = pack(records, refs, cursor, now, previous);
  hasBacklog = count == POST_SIZE;
  String data;
  serializeJson(request, data);
  const int code = http.POST(data);
  if (code != 200) {
    error = String("Entrega HTTP ") + code;
    return false;
  }
  JsonDocument response;
  if (deserializeJson(response, http.getString()) || !response["records"].is<JsonArray>()) {
    error = "Confirmación de API inválida";
    return false;
  }
  unsigned committed = 0;
  for (JsonObjectConst receipt : response["records"].as<JsonArrayConst>()) {
    const uint64_t ref = receipt["ref"] | uint64_t(0);
    const auto ids = receipt["ids"].as<JsonArrayConst>();
    if (ids.size() != 1 || !ids[0].is<const char*>() || !strlen(ids[0].as<const char*>())) continue;
    for (size_t i = 0; i < count; ++i) {
      if (refs[i] == ref && confirm(ref)) {
        refs[i] = 0;
        ++committed;
        break;
      }
    }
  }
  error = committed == count ? "" : "Lecturas pendientes sin confirmación";
  return committed == count;
}

void networkTask(void*) {
  Preferences nvs;
  nvs.begin("gc-cloud-v1", false);
  ClockAnchor previous{};
  if (nvs.getBytesLength("clock") == sizeof(previous)) nvs.getBytes("clock", &previous, sizeof(previous));
  bool anchored = false;
  JsonDocument wifi, cloud;
  deserializeJson(wifi, nvs.getString("wifi", "[]"));
  deserializeJson(cloud, nvs.getString("cloud", "{}"));
  enabled = validCloud(cloud);
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFiClientSecure client;
  client.setHandshakeTimeout(5);
  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(5000);
  http.setReuse(true);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  http.setUserAgent("GeoCattle-Base-T3/1");
  bool begun = false, online = false;
  size_t candidate = 0;
  uint64_t cursor = 0;
  uint32_t wifiAt = 0, nextPost = 0, retryMs = 5000;
  String ca, error;
  Command request{};
  for (;;) {
    if (xQueueReceive(commands, &request, pdMS_TO_TICKS(100)) == pdTRUE) {
      if (handleCommand(request, nvs, wifi, cloud)) {
        http.end();
        client.stop();
        begun = false;
        online = false;
        WiFi.disconnect();
        candidate = 0;
        wifiAt = millis();
        retryMs = 5000;
      }
      memset(&request, 0, sizeof(request));
    }
    const uint32_t now = millis();
    const int64_t wall = epochMs();
    if (!anchored && wall) {
      const ClockAnchor anchor{stationBoot, wall - esp_timer_get_time() / 1000};
      anchored = nvs.putBytes("clock", &anchor, sizeof(anchor)) == sizeof(anchor);
    }
    const bool connected = WiFi.status() == WL_CONNECTED;
    if (!connected) {
      if (online) {
        http.end();
        client.stop();
        begun = false;
        online = false;
        wifiAt = now;
      }
      if (wifi.size() && int32_t(now - wifiAt) >= 0) {
        WiFi.disconnect();
        const JsonObjectConst network = wifi[candidate % wifi.size()];
        const char* ssid = network["ssid"];
        const char* password = network["password"];
        WiFi.begin(ssid, password);
        ++candidate;
        wifiAt = now + 15000;
      }
      continue;
    }
    if (!online) {
      configTime(0, 0, "time.cloudflare.com", "pool.ntp.org");
      online = true;
      nextPost = now;
    }
    if (!enabled || !wall || int32_t(now - nextPost) < 0) continue;
    if (!begun) {
      ca = cloud["ca"] | "";
      client.setCACert(ca.c_str());
      const String origin = cloud["url"] | "";
      begun = http.begin(client, origin + BATCH_PATH);
      if (!begun) {
        nextPost = now + 15000;
        continue;
      }
    }
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Ingest-Key", String(cloud["key"] | ""));
    http.addHeader("X-Farm-ID", String(cloud["farm"] | ""));
    const char* accessId = cloud["access_id"] | "";
    if (*accessId) {
      http.addHeader("CF-Access-Client-Id", String(accessId));
      http.addHeader("CF-Access-Client-Secret", String(cloud["access_secret"] | ""));
    }
    bool backlog = false;
    if (upload(http, cursor, error, backlog, previous)) {
      retryMs = 5000;
      nextPost = millis() + (backlog ? 1000 : 15000);
    } else {
      http.end();
      client.stop();
      begun = false;
      nextPost = millis() + retryMs;
      retryMs = min(retryMs * 2, uint32_t(60000));
    }
  }
}

void begin(uint32_t boot) {
  stationBoot = (uint64_t(esp_random()) << 32) | boot;
  incoming = xQueueCreate(32, sizeof(Capture));
  commands = xQueueCreate(1, sizeof(Command));
  replies = xQueueCreate(1, sizeof(Reply));
  fsLock = xSemaphoreCreateMutex();
  if (!incoming || !commands || !replies || !fsLock) return;
  if (xTaskCreatePinnedToCore(storageTask, "gc-storage", 4096, nullptr, 2, nullptr, 0) != pdPASS) return;
  xTaskCreatePinnedToCore(networkTask, "gc-network", 16384, nullptr, 1, nullptr, 0);
}

void submit(const char* text) {
  if (!commands || strncmp(text, "GEOCATTLE_", 10) != 0) return;
  // One producer. The serial loop can immediately go back to handling LoRa.
  static Command command{};
  strlcpy(command.text, text, sizeof(command.text));
  xQueueSend(commands, &command, 0);
  memset(&command, 0, sizeof(command));
}

void printReply() {
  Reply reply{};
  if (replies && xQueueReceive(replies, &reply, 0) == pdTRUE) Serial.println(reply.text);
}
}  // namespace gccloud
