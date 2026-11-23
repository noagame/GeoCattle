#pragma once
#include <Arduino.h>
#include <Preferences.h>

class GatewayUsb {
  Preferences preferences;
  char eui[17] = {};
  char line[80] = {};
  size_t used = 0;
  uint8_t node = 0;
  bool overflow = false;
  bool storage = false;

  void identify() {
    Serial.printf("{\"type\":\"geocattle_gateway\",\"version\":1,\"gateway_eui\":\"%s\",\"node_id\":", eui);
    if (node) Serial.print(node); else Serial.print("null");
    Serial.printf(",\"provisioned\":%s,\"firmware\":\"gateway-bus-v1.1\"}\n", node ? "true" : "false");
  }

  void handle() {
    if (!strcmp(line, "GEOCATTLE_IDENTIFY_V1")) { identify(); return; }
    const char prefix[] = "GEOCATTLE_SET_NODE_V1 ";
    if (strncmp(line, prefix, sizeof(prefix)-1)) return;
    const char* arguments = line + sizeof(prefix)-1;
    if (strlen(arguments) != 18 || strncmp(arguments, eui, 16) || arguments[16] != ' ' ||
        (arguments[17] != '1' && arguments[17] != '2')) return;
    const uint8_t assigned = arguments[17] - '0';
    const bool changed = assigned != node;
    if (changed && (!storage || preferences.putUChar("node", assigned) != sizeof(uint8_t))) {
      Serial.println("{\"type\":\"geocattle_gateway_error\",\"version\":1,\"error\":\"nvs\"}");
      return;
    }
    Serial.printf("{\"type\":\"geocattle_gateway_node\",\"version\":1,\"gateway_eui\":\"%s\",\"node_id\":%u,\"provisioned\":true}\n", eui, assigned);
    if (changed) {
      Serial.flush();
      delay(250);
      ESP.restart();
    }
  }

public:
  uint8_t begin() {
    uint64_t mac = ESP.getEfuseMac();
    snprintf(eui, sizeof(eui), "%02x%02xfffe%02x%02x%02x%02x",
             unsigned((mac & 255) ^ 2), unsigned((mac >> 8) & 255), unsigned((mac >> 16) & 255),
             unsigned((mac >> 24) & 255), unsigned((mac >> 32) & 255), unsigned((mac >> 40) & 255));
    storage = preferences.begin("gc-gateway", false);
    if (storage) node = preferences.getUChar("node", 0);
    if (node != 1 && node != 2) node = 0;
    return node;
  }

  void poll() {
    while (Serial.available()) {
      const char value = char(Serial.read());
      if (value == '\r') continue;
      if (value == '\n') {
        line[used] = '\0';
        if (!overflow) handle();
        used = 0;
        overflow = false;
      } else if (used < sizeof(line)-1 && value != '\0') {
        line[used++] = value;
      } else {
        overflow = true;
      }
    }
  }
};

GatewayUsb gatewayUsb;
