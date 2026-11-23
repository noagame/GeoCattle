/*
GEOCATTLE - RED AUTOMATICA DE PRUEBA
Un collar JSON V5, dos gateways XIAO ESP32S3 + Wio-SX1262 B2B y base T3.
RadioLib 7.8.1 / ArduinoJson 7.x. Sin WiFi ni Bluetooth.
Gateway: seleccionar XIAO_ESP32S3. Base: ESP32 Dev Module.
Mantener GCRed.h y GCTransport.h junto a este .ino.
El EUI viene de eFuse. GeoCattle reserva y configura el nodo por USB.
La cola se pierde al quitar energia. No equivale a almacenamiento en servidor.
Conectar antena antes de alimentar. Prototipo pendiente de prueba RF real.
*/
#define GC_ROOT_T3 0
#include "GCRed.h"
