# Adaptador académico

El receptor ESP32/XBee debe entregar una línea JSON por captura usando el contrato lógico del backend. El puente conserva el instante del nodo, sesión, secuencia e identidad del hardware; no calcula posiciones ni sustituye datos faltantes. JSON por serial es una decisión del adaptador académico, no el codec binario final de LoRaWAN.

```bash
# Desde la raíz, con el backend físico activo:
python3 adapters/academic_bridge.py --env-file .env < capturas.ndjson

# USB/serial requiere pyserial:
uv pip install --python backend/.venv/bin/python -r adapters/requirements.txt
backend/.venv/bin/python adapters/academic_bridge.py --port /dev/ttyUSB0 --env-file .env

# Recuperar cola tras restablecer API:
python3 adapters/academic_bridge.py --env-file .env --retry-only
```

`INGEST_KEY` se lee del entorno o de la configuración privada. Cuando hay más de un predio físico activo, configura `INGEST_FARM_ID` con el UUID del predio de captura. El puente emite el ACK `{persisted:true,id,session_id,seq}` por serial o stdout después de la escritura en el backend. Si el collar está pendiente de alta, el ACK incluye `status:"candidate"` y el ID del candidato. El firmware conserva y reenvía la captura hasta que llega el ACK de persistencia, además del acuse del enlace. La cola admite 10.000 mensajes. Los errores permanentes conservan la captura en `queue` con `status=failed` para revisión.

La adquisición real, firmware Zigbee/XBee, pines, calibración y formato entregado por el receptor deben validarse en banco. El adaptador no acredita que el hardware esté conectado ni que un mensaje atravesó radio. Referencia API serial: [pySerial](https://pyserial.readthedocs.io/en/latest/shortintro.html).
