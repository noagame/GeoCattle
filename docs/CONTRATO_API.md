# Contrato de integración GeoCattle V1

Base `/api/v1`. Fechas ISO 8601 UTC y UUID textuales. GeoJSON WGS84 `[longitud, latitud]`. API protegida con sesión HttpOnly (cookie `geocattle_session`); encabezado `X-CSRF-Token` para escrituras de usuarios. Ingestión separada mediante `X-Ingest-Key`. Roles `owner`, `operator`, `viewer`. Predio se obtiene de la sesión, nunca del cuerpo enviado por el cliente.

## Sesión

- `POST /auth/login` `{username,password}` → `{user:{id,username,role,farm_id},csrf_token}` y cookie.
- `GET /auth/me` → misma estructura.
- `POST /auth/logout` → 204.

## Consultas

- `GET /dashboard` → `{farm:{id,name,environment},summary:{total,normal,warning,critical,unknown,active_events},animals:Animal[],events:Event[],sectors:Sector[]}`.
- `GET /animals?q=&sector_id=&limit=100&offset=0` → `{items:Animal[],total}`.
- `GET /animals/{id}` → Animal, ampliado con `collar_assignment` y `pasture_assignment` actuales (o `null`); el listado y dashboard no incorporan estos detalles adicionales.
- `GET /animals/{id}/assignments?limit=50&offset=0` → `{items:Association[],total}`; máximo 200 por petición, orden de inicio descendente y alcance por predio.
- `GET /animals/{id}/history?start=&end=&limit=500&offset=0` → `{items:Telemetry[],total}` (orden captura).
- `GET /devices` → `{items:Device[],total}`.
- `GET /sectors` → `{items:Sector[],total}`.
- `GET /geofences` → `{items:Geofence[],total}`.
- `GET /events?condition=&attention=&limit=100&offset=0` → `{items:Event[],total}`.
- `GET /audit?limit=100&offset=0` → `{items:Audit[],total}`.
- `GET /notifications` → `{items:Notification[],total}`.
- `GET /settings` → objeto de reglas versionado.
- `GET /maintenance?device_id=&limit=100&offset=0` → `{items:[{id,device_id,device_name,battery_id,kind,at,responsible_id,responsible_name,result}],total}`.
- `GET /reports` → indicadores locales medidos sin afirmar SLA de campo.
- `GET /reports/telemetry.csv` → exportación autorizada de lecturas.
- `GET /health` sin sesión → estado sin datos del predio.

## Escrituras

- `POST /animals` `{diio,name,orientation:"meat"|"milk",sector_id?}` → Animal.
- `PATCH /animals/{id}` `{name?,orientation?,sector_id?,enabled?}` → Animal.
- `POST /devices` `{hardware_id,dev_eui?,name,transport:"academic"|"lorawan",interval_seconds:300}` → Device.
- `POST /assignments` `{animal_id,device_id,effective_at?,replace:false}` → asignación. `replace:true` cierra explícitamente la anterior.
- `POST /sectors` `{name}` → Sector.
- `POST /geofences` `{sector_id,name,geometry:GeoJSONPolygon,expected_version:0,confirm_impact:true}` → Geofence (inicial expected_version 0; cambios conservan versiones).
- `POST /pasture-assignments` `{animal_id,geofence_id,effective_at?}` → asignación.
- `POST /events/{id}/actions` `{action:"acknowledge"|"review"|"conclude"|"reopen",note}` → Event. Atención y condición independientes.
- `POST /devices/{id}/config` `{interval_seconds,expected_version}` → configuración solicitada pendiente. Confirmar aplicación mediante telemetría `config_version`.
- `PATCH /devices/{id}` `{enabled:boolean}` → habilitación/retiro explícito auditable.
- `POST /maintenance` `{device_id,battery_id?,kind:"inspection"|"recharge"|"replacement"|"retirement",at?,result}` → registro; responsable de la sesión.
- `PUT /settings` `{expected_version,battery_low_mv,temperature_high_c?,activity_low_threshold?,activity_window_minutes,proximity_meters,temperature_enabled,activity_enabled,proximity_enabled}` → reglas; sensores preventivos deshabilitados por defecto fuera de simulación.
- `POST /simulation/scenarios` `{scenario:"normal"|"escape"|"return"|"low_battery"|"no_fix"|"timeout",animal_id?}` → resultado. Sólo entorno simulation, identifica origen `sim`.

## Objetos

Animal: `{id,diio,name,orientation,enabled,sector_id,sector_name,device_id,device_name,status:"normal"|"warning"|"critical"|"unknown",position_status:"fresh"|"stale"|"unknown",communication_status:"recent"|"absent"|"unknown",geofence_status:"inside"|"outside"|"pending"|"unknown",last_telemetry:Telemetry|null,last_position:Telemetry|null,position_age_seconds:number|null,active_events:number}`.

Telemetry: `{id,device_id,animal_id,session_id,seq,observed_at,received_at,longitude:number|null,latitude:number|null,gnss_valid:boolean,surface_temperature_c:number|null,activity_index:number|null,battery_mv:number|null,source:"sim"|"academic"|"lorawan",quality:{},config_version?}`. Contrato de ingesta incluye `hardware_id` en lugar de device_id/animal_id; animal se resuelve mediante asociación histórica. `observed_at` con zona horaria obligatoria. Unique hardware/session/seq. Sin fix, lat/lon nulos; paquete tardío no rejuvenece estado ni recepción efectiva de comunicación.

Device: `{id,hardware_id,dev_eui,name,transport,enabled,interval_seconds,config_version,pending_config:{version,interval_seconds,status}|null,animal_id?,last_received_at?}`.

Sector: `{id,name}`. Geofence: `{id,sector_id,name,version,active,geometry,created_at}`. Event: `{id,animal_id,animal_name,diio,device_id,type,severity,condition:"active"|"resolved",attention:"pending"|"acknowledged"|"in_review"|"concluded",opened_at,resolved_at,detail,actions:[]}`.

Errores `{detail:string}` con 401 sin sesión, 403 permisos/CSRF/predio, 409 conflicto versión/identidad/asociación, 422 validación. Las pantallas mantienen el estado anterior si falla una escritura.


## Asociación actual e historial por animal

`collar_assignment`: `{id,device_id,valid_from,valid_to}` o `null`.

`pasture_assignment`: `{id,geofence_id,geofence_name,geofence_version,sector_id,sector_name,valid_from,valid_to}` o `null`.

`Association`: `{id,kind:"collar"|"pasture",valid_from,valid_to,active,assigned_by,assigned_by_name,device_id,device_name,hardware_id,geofence_id,geofence_name,geofence_version,sector_id,sector_name}`. Los campos de la otra clase de asociación son `null`. El acceso requiere sesión y animal del predio autorizado; las lecturas conservan su asignación histórica.

Cambiar de sector manualmente contradiciendo una asignación de pastoreo vigente devuelve 409; se debe asignar la nueva zona. Las nuevas geocercas y asignaciones exigen sector activo. Un reemplazo de collar no puede recortar lecturas ya persistidas de la asociación anterior. El cierre de eventos por reasignación conserva evidencia y atención, y no representa recuperación física del sensor.

## Captura radio JSON V5

El protocolo de radio se convierte al contrato de ingestión anterior mediante
`adapters/lora_json.py` y `adapters/lora_usb.py`. Es diferente de `schema_version`
de la API. Se conserva compatibilidad con CSV V4.

| Campo radio | Significado / destino |
|---|---|
| `v` | Versión 5 del protocolo físico |
| `id`, `s`, `q` | Identificador de collar, sesión de 16 caracteres hexadecimales y secuencia |
| `u` | Tiempo encendido en ms → `quality.uptime_ms` |
| `g` | `[latitud, longitud, edad_ms, satélites_usados, HDOP]` |
| `t` | Temperatura del sensor en °C |
| `a` | `[x,y,z]` en g → `quality.acceleration_g` |
| `m` | `[estado,RMS_g]`, estado -1 desconocido, 0 reposo, 1 movimiento |
| `b` | `[mV,porcentaje_estimado,presente,cargando,USB]` |
| `p` | Intervalo anunciado, entre 30000 y 40000 ms |
| `f` | Bits: 1 sin posición GPS, 2 sin temperatura, 4 sin acelerómetro |
| `e` | Motivo: 0 inicio, 1 periódico, 2 inicio de movimiento |
| `d` | Opcional: `[bytes_NMEA,sentencias_válidas,errores_checksum]` |

El receptor entrega una línea JSON con el sobre
`{"packet": objetoV5, "radio": {"rssi_dbm": numero, "snr_db": numero}}`.
El objeto de radio no supera 255 bytes. Las mediciones ausentes se transmiten
como `null`; en estados y contadores opcionales se utiliza -1 para desconocido.
El decodificador valida tipos, rangos, consistencia de flags y estados de batería.
Un fix válido requiere ambas coordenadas y edad menor de 5000 ms; no se inventa
una posición cuando no hay fix. Los satélites visibles y C/N₀ no se transmiten
en esta versión.

La identidad de deduplicación es collar/sesión/secuencia. El puente conserva la
hora de primera recepción del PC porque el paquete no aporta fecha UTC GPS;
`quality.observed_at_estimated` lo hace explícito. No se debe modificar el
historial inmutable para corregirlo ni simular mediciones ausentes.

Consultas de visualización, con sesión y predio autorizado:

- `GET /hardware/overview`: última lectura y última posición válida por collar.
- `GET /hardware/telemetry?day=AAAA-MM-DD&hardware_id=REAL01&limit=100&offset=0`: historial del día en la zona horaria del predio, con paginación (máximo 500).
- `GET /hardware/daily?hardware_id=REAL01&days=30`: conteos de muestras y extremos de temperatura; `days` entre 1 y 366.
- `GET /hardware/receiver`: estado del puente USB; solo dueño/administrador. Un estado de más de 30 s se considera vencido.

Las asignaciones a bovinos siguen usando su fecha efectiva. El collar puede
consultarse antes de asignarlo; las capturas antiguas sin asignación se conservan.
Las pruebas de referencia están en `qa/test_lora_json.py`, `qa/test_lora_usb.py`,
`qa/test_esp32_contract.py` y `qa/test_hardware_api.py`.

## Registro de colaboradores mediante el dueño

- `POST /v3/invitations`: solo el dueño en su predio, con autorización MFA para esa operación. Admite correo y rol `worker` o `veterinarian`. Soporte administra colaboradores existentes pero no emite altas nuevas.
- `POST /v3/enrol/preview` `{token}`: valida vigencia, no consumo/revocación y cuenta/predio activos del entorno. Devuelve `{email,role_code,farm_name,expires_at,account_exists}`. El token se envía en el cuerpo. No crea cuenta ni membresía.
- `POST /v3/enrol` `{token,password,full_name?}`: consume la invitación. Cuenta nueva: nombre y contraseña de al menos doce caracteres. Cuenta existente: contraseña actual, sin cambiar nombre/hash. El rol y el predio proceden exclusivamente de la invitación.

Invitación manual, válida durante 48 horas y de un uso. Sin registro público libre ni envío automático de correo. Guía: [USUARIOS_Y_REGISTRO.md](USUARIOS_Y_REGISTRO.md).

## Configuración desde el panel de alertas

El dueño y el administrador con predio seleccionado pueden ajustar los parámetros mediante **Alertas y atención → Configurar alertas**. Se comparte formulario y versión con **Reglas del predio**. GET/PUT `/settings` incorporan `capabilities` con permisos de edición, entorno y disponibilidad de activación preventiva; esa metadata no se acepta como parámetro de escritura ni forma parte del historial de reglas. El contrato de campos y la validación existentes se conservan. Ver [CONFIGURACION_ALERTAS.md](CONFIGURACION_ALERTAS.md).
