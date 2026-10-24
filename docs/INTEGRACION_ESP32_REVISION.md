# Revisión ESP32 → GeoCattle

> Esta es la revision inicial del 21 de octubre. La implementacion y la prueba
> fisica posteriores de COM5, archivo persistente, API y PostgreSQL se documentan
> en [USB_COM5.md](USB_COM5.md). Los bloqueos de esta revision deben leerse en su
> contexto historico, no como el estado actual de la integracion.

Fecha: 21-10-2026. Repositorio clonado de https://github.com/noagame/GeoCattle.git.
Commit revisado: `2689c0a1e5515cf0ac57b5a24547408f335fc3f7`.
Ruta: `C:\ruta\GeoCattle`.

## Resultado

La aplicación dispone de ingestión, PostgreSQL/PostGIS, historial y mapa. Los códigos LILYGO entregados anteriormente NO son compatibles directamente con el adaptador del repositorio. Se necesita convertir el CSV y resolver la hora de captura. Esta revisión valida el contrato en software; no acredita recepción serial, persistencia en PostgreSQL ni visualización real en el navegador.

No se alteraron el firmware, la base de datos, los servicios ni las credenciales. No se inició el seed de 70 animales simulados. Los ejemplos de las pruebas son ficticios y no se publicaron en la API.

## Flujo previsto

Sensores/GPS → ESP32 collar → LoRa punto a punto → LILYGO receptor → USB serial 115200 → adaptador CSV/JSON en PC → POST `/api/v1/ingest/telemetry` con `X-Ingest-Key` → tabla `telemetry` → API de animales/historial → React/Leaflet.

El PC puede alojar tanto el adaptador como los servicios. El receptor actual no es un concentrador LoRaWAN; debe registrarse este transporte como `academic`, no `lorawan`. ChirpStack no decodifica automáticamente las tramas P2P actuales.

## Qué entrega el firmware actual

Comparado con los perfiles `GeoCattle_Bateria_4_Placas` preparados en esta conversación, no con una captura física nueva. V4 entrega por USB 23 campos:

```text
version,id,session,seq,source,uptime_ms,gps_fix,gps_age_ms,lat,lon,temp_c,ax_g,ay_g,az_g,activity,flags,period_ms,battery_mv,battery_pct_est,battery_present,battery_charging,rssi,snr
```

El collar envía los primeros 21 y el receptor añade RSSI/SNR. V3 anterior tiene 19 campos en USB, sin los cuatro de batería. Las líneas que comienzan con `#` son diagnósticos. `nan` representa una medición ausente; -1 representa estado de batería desconocido. El logger `recibir_bateria.py` anterior guarda JSONL local, pero su JSON tampoco coincide directamente con `TelemetryIn`.

## Correspondencia de campos

| Firmware | API/almacenamiento propuesto | Observación |
|---|---|---|
| versión radio 3/4 | `quality.wire_protocol_version` | `schema_version` de la API debe ser 1 |
| id REAL01/02/03 | `hardware_id` | Registrar cada ID, sin asignarlo a todos los animales |
| session, seq | `session_id`, `seq` | Preservar para deduplicación |
| source=device | `source=academic` | `device` es rechazado por la API |
| source=sim | `source=sim` | Solo entorno de simulación; nunca mezclar como lectura real |
| uptime_ms | `quality.uptime_ms` | No es fecha UTC |
| gps_fix | `gnss_valid` booleano | Sin fix: latitud/longitud nulas, no cero |
| lat/lon | `latitude` / `longitude` | Grados WGS84, no invertir coordenadas |
| gps_age_ms | `quality.gps_age_ms` | Antigüedad del fix, no reloj de captura |
| temp_c | `surface_temperature_c` | Ausente → null; API admite -60 a 100 °C |
| ax/ay/az | `quality.acceleration_g` | No existen tres columnas ni panel dedicado actual |
| activity=nan | `activity_index=null` | No convertir un eje en un índice sin algoritmo definido |
| battery_mv | `battery_mv` | -1 → null; se visualiza en mV |
| porcentaje, presencia, carga | campos en `quality` | Se conservan como metadatos; UI específica pendiente |
| flags, period_ms | campos en `quality` | No confirman una configuración remota aplicada |
| RSSI/SNR | `quality.radio` inicialmente | Para panel de gateway: usar `receptions` con EUI registrado |
| fecha de captura | `observed_at` UTC obligatoria | FALTA en el mensaje actual |

Los campos extra de primer nivel son rechazados (`extra=forbid`). `quality` es JSONB persistente y permite conservar los datos adicionales sin cambiar inmediatamente el esquema SQL. Las claves propuestas de `quality` son una convención nueva; la interfaz aún no tiene widgets para aceleración o estado de carga.

## Bloqueos encontrados

1. **Formato:** `adapters/academic_bridge.py` solo recibe NDJSON del contrato API. No recibe el CSV actual. Hay que añadir un decodificador antes de su cola persistente; no basta cambiar extensión a un archivo.
2. **Hora:** `observed_at` es obligatorio y participa en asignación histórica, vigencia y alertas. Ni millis() ni gps_age_ms permiten reconstruir UTC por sí solos. Recomendación: transmitir fecha/hora UTC validada desde el GPS integrado y definir el comportamiento antes de sincronizar. Si se elige usar hora del PC para una demostración, debe marcarse explícitamente como aproximada y revisarse la semántica del backend; no sustituirla silenciosamente. Aún no se implementó ninguna de estas alternativas.
3. **Entorno:** `compose.yaml` inicia por defecto `simulation`. `domain.ingest` rechaza hardware real en ese entorno. Se necesita un entorno piloto y un predio correspondiente, con configuración y volumen propios. No etiquetar lecturas reales como `sim` para evitar el rechazo.
4. **Identidad:** dar de alta REAL01/02/03 como dispositivos académicos y asignarlos a animales reales de prueba antes de las capturas. Sin asignación, la telemetría puede persistir sin asociarse al animal ni actualizar su ficha.
5. **Intervalo:** firmware transmite aleatoriamente cada 12–18 s; DeviceIn/ConfigIn admiten como mínimo 30 s. Hay que acordar el intervalo y alinear firmware, configuración registrada y cálculo de vigencia. No fingir que se aplicó una configuración; el firmware actual no procesa órdenes descendentes.
6. **ACK:** el puente devuelve ACK al confirmar escritura en backend, pero el receptor y los emisores actuales no lo procesan ni retransmiten por él. No existe garantía de entrega de extremo a extremo. El buffer del PC solo protege capturas que llegaron al PC.
7. **Gateway:** el firmware no envía identidad del receptor. Para `telemetry_receptions`, el adaptador debe añadir un EUI estable, registrado en el mismo predio, junto a RSSI/SNR. La API ignora gateways desconocidos o ajenos al predio; no inventar un EUI de hardware.

## Visualización ya disponible y lo pendiente

`frontend/src/PagesAnimals.tsx` muestra posición, trayectoria, temperatura superficial, índice de actividad, batería en mV y antigüedad. La API entrega `quality`, pero no hay presentación específica de los ejes ADXL345 ni del porcentaje/cargando. Estos pueden conservarse en JSONB y añadirse después a la ficha. No se puede considerar que los tres ejes ya se muestran por existir una tarjeta de actividad.

El historial se obtiene de la API; el navegador no debe recibir la contraseña de PostgreSQL ni `INGEST_KEY`. La asociación debe pasar por dispositivos/asignaciones, no por inserciones directas desde el puerto serial a tablas de animales.

## Comprobaciones reproducibles

Desde la raíz del repositorio, usando Python con Pydantic 2:

```powershell
python qa/test_esp32_contract.py
python qa/test_academic_bridge.py
```

Se agregaron siete pruebas del esquema real: propuesta válida, sin fix/batería, rechazo de hora ausente, rechazo de origen `device`, versión radio distinta de API, ejes fuera de primer nivel y límite de intervalo. Las cuatro pruebas existentes del puente ejercitan cola, reintentos, ACK y rechazo con servidor HTTP local de prueba. No son una prueba de PostgreSQL ni de radio.

Resultado ejecutado: **7/7 pruebas de contrato y 4/4 pruebas del puente aprobadas**, con Python del entorno y Pydantic 2.14.1. `git diff --check` sin errores.

Las pruebas del puente fallaron inicialmente al limpiar archivos en Windows: el contexto de transacción de sqlite3 no cerraba la conexión. Se corrigió `Spool.connection()` para conservar commit/rollback y cerrar explícitamente en `finally`. Después pasaron las cuatro pruebas, incluida recuperación tras error HTTP. Esta modificación es local; no se hizo commit ni push.

## Siguiente implementación

1. Resolver UTC de captura y el intervalo; actualizar el protocolo y el firmware conservando lectura de versiones anteriores.
2. Implementar el adaptador CSV validado, con cola, conservación del mensaje original e identidad del receptor; reutilizar las garantías del puente existente.
3. Preparar piloto local PostgreSQL/PostGIS/API/frontend, registrar predio, gateway, collares y asignaciones.
4. Prueba física: capturar USB → publicar → comprobar id persistido → consultar historial → confirmar mapa y batería en navegador. Desconectar API para verificar recuperación y duplicados.
5. Añadir widgets de aceleración/batería estimada y luego evaluar escalabilidad por separado; una demo con tres emisores no acredita capacidad para 70.

Esta entrega contiene la descarga y revisión con pruebas de contrato, no una integración operativa de extremo a extremo.
