# Prototipo fisico: COM5 -> GeoCattle

> Guía inicial de integración del 22 de octubre de 2026. Los resultados V4 e intervalos
> citados más abajo describen esa prueba histórica. Para el estado actual (JSON V5,
> GPS válido, gráficas y movimiento), consultar [VISUALIZACION_TELEMETRIA.md](VISUALIZACION_TELEMETRIA.md)
> y [DESARROLLO_LOCAL.md](DESARROLLO_LOCAL.md).


Implementacion local del 22 de octubre de 2026. No sustituye el firmware del collar.

## Inicio en este PC

GeoCattle se sirve en http://localhost:8084/#hardware. La cuenta inicial es
`prototipo@geocattle.local`; la contrasena se consulta localmente en el archivo
privado `.runtime/acceso_prototipo.json`. No compartir ni subir ese archivo.

Desde PowerShell normal:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\ruta\GeoCattle\Iniciar-Prototipo.ps1"
```

Este comando utiliza una instancia PostgreSQL 16/PostGIS 3.6.2 preparada dentro
de `.runtime`, en 127.0.0.1:55434. No modifica la instalacion PostgreSQL 18 del
sistema ni necesita el motor Docker para esta ejecucion local. La base es
`geocattle_academic`, APP_ENV=development, SIMULATION_ENABLED=false. No se cargo
la demo de animales sinteticos. Las tres migraciones originales se conservan.

Para iniciar solo el capturador con el usuario de Windows (cuando el entorno
restringido del agente no puede abrir COM5):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\ruta\GeoCattle\Iniciar-Captura-COM5.ps1"
```

Cerrar el Monitor Serie y Plotter de Arduino antes de iniciar. Dejar la ventana
abierta para mantener la captura. No ejecutar dos capturadores del mismo puerto.
Se reintenta conectar cada cinco segundos si se desconecta la placa.

Para Docker se conserva compose.yaml y se agrega compose.usb.yaml, que permite
montar el estado del capturador en la API. El Docker/WSL del usuario estaban
instalados, pero la cuenta restringida del agente recibio acceso denegado a sus
canales de control; no se declara validada una ejecucion con Docker.

## Datos y registro diario

`adapters/lora_usb.py` acepta:

- CSV V4 de 23 campos (21 del collar mas RSSI/SNR).
- CSV V4 de 21 campos, incluido el prefijo `Contenido:` del diagnostico.
- La linea `RSSI: ... dBm | SNR: ... dB` anterior al contenido, durante tres segundos.

Conserva las lineas serie originales, con hora UTC del PC, en
`.runtime/capture/daily/AAAA-MM-DD/serial.jsonl`. El dia se calcula en
America/Santiago. Las observaciones validadas se conservan en
`.runtime/capture/captures.sqlite3`, incluso despues de confirmarlas en PostgreSQL.
SQLite es el archivo intermedio local; la base de la aplicacion sigue siendo
PostgreSQL/PostGIS.

Cada captura se identifica por hardware_id + session_id + seq. La primera
recepcion fija el tiempo de observacion; un duplicado no lo rejuvenece. Un mensaje
con la misma identidad y contenido diferente se rechaza y su linea original queda
en el registro. La API confirma un ID persistido antes de marcarlo como entregado.
Los errores HTTP y las desconexiones conservan la captura con reintentos espaciados.
El proceso no envia ACK al collar: no hay garantia de recuperar paquetes que nunca
llegaron al PC.

Para exportar las observaciones normalizadas de un dia desde la raiz:

```powershell
.\.venv\Scripts\python.exe scripts/export_usb_day.py --day 2026-10-22
```

Produce `telemetry.jsonl` junto al archivo diario. Se puede regenerar desde el
archivo SQLite; no elimina las observaciones. Incluye el estado de entrega e ID
de PostgreSQL. Es posible exportar tambien dias anteriores, cambiando la fecha.

## Hora, sensores y relaciones

El firmware V4 no incluye fecha UTC. Se usa la primera recepcion del PC como hora
aproximada y se marca `quality.time_basis=pc_first_reception` y
`quality.observed_at_estimated=true`. No representa el instante exacto de medicion;
se conserva uptime_ms y gps_age_ms. El reloj del PC debe ser correcto. No se acepta
origen `sim` en este puente fisico ni se inventan coordenadas/temperatura.

El registro inicial crea REAL01 como dispositivo academico, sin bovino inventado.
En `Recepcion de collares` se ven sus muestras aun sin asignacion. Despues, en
`Collares y dispositivos`, se relaciona el dispositivo con un bovino identificado
y su historial de asignaciones. Las nuevas capturas se asociaran segun la fecha
efectiva. Las capturas previas sin asignacion siguen consultables por collar; no
se reescribe telemetria historica inmutable para asignarlas retroactivamente.

Solo posiciones con fix valido se usan para el mapa. Los tres ejes se conservan
en quality.acceleration_g, y la bateria en mV mas porcentaje estimado, presencia
y carga. El receptor USB no manda identidad fisica de gateway: receiver_label
es una etiqueta de conexion, no un EUI de hardware inventado.

El firmware actual anuncia 12-18 segundos de envio. El dispositivo se registra con
30 segundos como ventana de supervision admitida por el modelo existente. Se
conserva el periodo anunciado en quality.period_ms; no se afirma que se envio ni
aplico una configuracion remota. Este prototipo no acredita capacidad para 70
emisores simultaneos.

## Interfaz y comprobaciones

La nueva seccion `Recepcion de collares` filtra por fecha/collar, permite paginar
las muestras y muestra el registro diario, ejes, bateria, GPS y RSSI/SNR. Se exige
sesion y se filtra por predio. El estado USB solo se ofrece a dueno/administrador
con predio activo. Cambiar de predio invalida la informacion anterior de la vista.

Validaciones ejecutadas: siete pruebas nuevas del puente (conversion, datos
ausentes, simulacion rechazada, duplicados, conflicto, recuperacion de cola), siete
pruebas de contrato existentes y cuatro del puente academico. Ingesta real del
backend y deduplicacion comprobadas contra PostgreSQL en transaccion revertida,
sin dejar fixtures en la base operativa. Compilacion TypeScript y Vite comprobadas.
La verificacion fisica tambien se completo: el usuario inicio el capturador en
PowerShell normal, COM5 quedo abierto y REAL01 entrego paquetes V4 que se
conservaron localmente y recibieron IDs de PostgreSQL mediante HTTP 201. Se
compararon los IDs del archivo con la consulta autenticada de telemetria y el
resumen diario. En el corte de verificacion habia ocho muestras reales,
temperatura 17.75 C, ejes ADXL345 presentes, sin fix GPS y sin bateria instalada.
No se afirma visualizacion de posiciones mientras el collar no tenga fix.

Los logs de servicios estan en `.runtime/prototype-api.log`,
`.runtime/prototype-worker.log` y, si se inicio en segundo plano,
`.runtime/prototype-usb.log`. El estado actual de captura esta en
`.runtime/capture/status.json`. Respaldar PostgreSQL con pg_dump; no copiar el
directorio de datos mientras el servidor esta escribiendo. El cierre normal de
PostgreSQL se hace con pg_ctl stop, conservando la base.
