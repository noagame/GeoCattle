#pragma once
// Copia este archivo como config.h en la misma carpeta y completa los valores.
// config.h queda fuera de Git: contiene la clave de ingesta y las redes WiFi.

// Hasta tres redes. La placa las prueba en orden y rota cada 15 s.
#define GC_WIFI_NETWORKS { \
  {"RED_PRINCIPAL", "CLAVE_FICTICIA"}, \
}

// Origen HTTPS del servidor, sin ruta ni barra final. Para probar contra un PC de la
// misma red se admite http:// con IP privada, p. ej. "http://192.168.1.20:18080".
#define GC_API_URL "https://geocattle.example.com"
// INGEST_KEY del archivo privado .env.pilot del servidor (32 caracteres o más).
#define GC_INGEST_KEY ""
// UUID del predio de producción que recibe las lecturas.
#define GC_FARM_ID ""
// Service token de Cloudflare Access para /api/v1/ingest/receiver-batch (opcional).
#define GC_ACCESS_ID ""
#define GC_ACCESS_SECRET ""
// Nombre de esta receptora en los lotes que llegan a GeoCattle.
#define GC_RECEIVER_NAME "NUBE01"
// 1: sin balizas de otra raíz durante 25 s, actúa como raíz (balizas y ACK). 0: solo escucha.
#define GC_ROOT_FALLBACK 1
