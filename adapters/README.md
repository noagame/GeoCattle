# Adaptador académico

El receptor ESP32/XBee debe entregar una línea JSON por captura usando el contrato lógico del backend. El puente conserva el instante del nodo, sesión, secuencia e identidad del hardware; no calcula posiciones ni sustituye datos faltantes. JSON por serial es una decisión del adaptador académico, no el codec binario final de LoRaWAN.

```bash
# Desde geocattle-saas, con backend y dispositivo registrado:
python3 adapters/academic_bridge.py --env-file .env < capturas.ndjson

# USB/serial requiere pyserial:
uv pip install --python backend/.venv/bin/python -r adapters/requirements.txt
backend/.venv/bin/python adapters/academic_bridge.py --port /dev/ttyUSB0 --env-file .env

# Recuperar cola tras restablecer API:
python3 adapters/academic_bridge.py --env-file .env --retry-only
```

`INGEST_KEY` se lee del entorno/configuración privada y no se imprime. El ACK `{persisted:true,id,session_id,seq}` se emite por serial/stdout después de la respuesta de escritura del backend. El firmware debe conservar y reenviar una captura hasta recibir ese ACK, además del acuse del enlace. Se limita la cola a 10.000 mensajes; una captura rechazada no recibe ACK. Las capturas que reciben error permanente quedan en la tabla `queue` con `status=failed` para revisión. No se borran ni atribuyen a otro animal automáticamente.

La adquisición real, firmware Zigbee/XBee, pines, calibración y formato entregado por el receptor deben validarse en banco. El adaptador no acredita que el hardware esté conectado ni que un mensaje atravesó radio. Referencia API serial: [pySerial](https://pyserial.readthedocs.io/en/latest/shortintro.html).
