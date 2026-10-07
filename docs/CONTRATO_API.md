# Contrato de integración GeoCattle V1

Base `/api/v1`. Fechas ISO 8601 UTC y UUID textuales. GeoJSON WGS84 `[longitud, latitud]`. API protegida con sesión HttpOnly (cookie `geocattle_session`); encabezado `X-CSRF-Token` para escrituras de usuarios. Ingestión separada mediante `X-Ingest-Key`. Roles `owner`, `operator`, `viewer`. Predio se obtiene de la sesión, nunca del cuerpo enviado por el cliente.

## Sesión

- `POST /auth/login` `{username,password}` → `{user:{id,username,role,farm_id},csrf_token}` y cookie.
- `GET /auth/me` → misma estructura.
- `POST /auth/logout` → 204.

## Consultas

- `GET /dashboard` → `{farm:{id,name,environment},summary:{total,normal,warning,critical,unknown,active_events},animals:Animal[],events:Event[],sectors:Sector[]}`.
- `GET /animals?q=&sector_id=&limit=100&offset=0` → `{items:Animal[],total}`.
- `GET /animals/{id}` → Animal.
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
