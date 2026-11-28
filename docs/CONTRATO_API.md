# Contrato de integración GeoCattle V1

Base `/api/v1`. Fechas ISO 8601 con zona horaria y UUID textuales. GeoJSON WGS84 `[longitud, latitud]`. La API usa la cookie de sesión HttpOnly `geocattle_session` y exige `X-CSRF-Token` para escrituras de usuarios. La ingesta usa `X-Ingest-Key`. Los roles V3 son `admin`, `owner`, `worker` y `veterinarian`. También se admiten los perfiles legados `operator` y `viewer`. Las operaciones del predio usan el contexto autorizado de la sesión.

## Sesión

- `POST /auth/login` `{username,password}` → `{user:{id,username,role,farm_id},csrf_token}` y cookie, o un desafío cuando se requiere TOTP. El desafío incluye `mfa_required`, `challenge_token` y `setup_required`. Solo la inscripción incluye `secret` y `otpauth_uri`; la sesión se abre después de verificar el código.
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
- `GET /reports/telemetry.csv` y `GET /reports/telemetry.xlsx` → exportación autorizada de lecturas. Véase [Exportaciones tabulares](#exportaciones-tabulares).
- `GET /health` sin sesión → estado sin datos del predio.

## Escrituras

- `POST /animals` `{diio,name,orientation:"meat"|"milk",sector_id?}` → Animal.
- `PATCH /animals/{id}` `{name?,orientation?,sector_id?,enabled?}` → Animal.
- `POST /devices` `{hardware_id,dev_eui?,name,transport:"academic"|"lorawan",interval_seconds:300}` → Device.
- `POST /assignments` `{animal_id,device_id,effective_at?,replace:false}` → asignación. `replace:true` cierra explícitamente la anterior.
- `POST /assignments/{id}/close` `{effective_at?}` (cuerpo opcional) → asignación cerrada. No crea otra asignación.
- `POST /sectors` `{name}` → Sector.
- `POST /geofences` `{sector_id,name,geometry:GeoJSONPolygon,expected_version:0,confirm_impact:true}` → Geofence (inicial expected_version 0; cambios conservan versiones).
- `POST /pasture-assignments` `{animal_id,geofence_id,effective_at?}` → asignación.
- `POST /events/{id}/actions` `{action:"acknowledge"|"review"|"conclude"|"reopen",note}` → Event. Atención y condición independientes.
- `POST /devices/{id}/config` `{interval_seconds,expected_version}` → configuración solicitada pendiente. Confirmar aplicación mediante telemetría `config_version`.
- `PATCH /devices/{id}` `{enabled:boolean}` → Device; retiro (`false`) o reactivación (`true`) auditable.
- `DELETE /devices/{id}` → 204 si el collar no tiene historial operativo.
- `POST /maintenance` `{device_id,battery_id?,kind:"inspection"|"recharge"|"replacement"|"retirement",at?,result}` → registro; responsable de la sesión.
- `PUT /settings` `{expected_version,battery_low_mv,temperature_high_c?,activity_low_threshold?,activity_window_minutes,proximity_meters,temperature_enabled,activity_enabled,proximity_enabled}` → reglas; sensores preventivos deshabilitados por defecto fuera de simulación.
- `POST /simulation/scenarios` `{scenario:"normal"|"escape"|"return"|"low_battery"|"no_fix"|"timeout",animal_id?}` → resultado. Sólo entorno simulation, identifica origen `sim`.

### Ciclo de vida de collares

- Solo escribe el dueño o el administrador con ese predio activo. Rigen la sesión, el CSRF y la política MFA de inventario. Un rol no autorizado o un recurso fuera del predio devuelve 403.
- Desvincular fija `valid_to` (fin exclusivo) a `effective_at` o a la hora del servidor si se omite. Una marca sin zona horaria o futura devuelve 422; una asociación ya cerrada, un fin igual o anterior al inicio, o una lectura atribuida observada en o después del fin devuelven 409. Se conserva el historial, se resuelven los eventos activos del par sin cambiar su evidencia ni atención, se limpia el monitoreo del bovino y se audita `assignment/close`. Las nuevas lecturas se atribuyen según `observed_at`: desde el fin quedan sin bovino hasta otra asignación; las lecturas tardías dentro de la vigencia aún corresponden al bovino original.
- Retirar conserva el dispositivo y su historial, deshabilita la ingesta y resuelve las alertas activas de comunicación. No cierra asociaciones automáticamente: si existe una vigente o que aún no termina, devuelve 409; primero hay que desvincular. Reactivar permite recibir y reasignar sin reabrir vigencias anteriores. Se modifica solo `devices.enabled`, ya usado por la ingesta y el monitoreo. El campo `devices.status` de la migración V3 no gobierna este flujo; el `status` del API V3 de gateways describe otro equipo.
- Eliminar corrige un alta sin uso. Devuelve 409 si existen asignaciones (incluidas las históricas), telemetría, mantenimiento, eventos, configuraciones o solicitudes vinculadas. En esos casos solo procede retirar para conservar la trazabilidad. Cuando hubo aprobación de una detección, esta pasa a `dismissed` sin referencia al dispositivo y conserva sus recibos de deduplicación; un paquete nuevo puede crear otra detección. Ambas acciones son auditables.

## Objetos

Animal: `{id,diio,name,orientation,enabled,sector_id,sector_name,device_id,device_name,status:"normal"|"warning"|"critical"|"unknown",position_status:"fresh"|"stale"|"unknown",communication_status:"recent"|"absent"|"unknown",geofence_status:"inside"|"outside"|"pending"|"unknown",last_telemetry:Telemetry|null,last_position:Telemetry|null,position_age_seconds:number|null,active_events:number}`.

Telemetry: `{id,device_id,animal_id,session_id,seq,observed_at,received_at,longitude:number|null,latitude:number|null,gnss_valid:boolean,surface_temperature_c:number|null,activity_index:number|null,battery_mv:number|null,source:"sim"|"academic"|"lorawan",quality:{},config_version?}`. Contrato de ingesta incluye `hardware_id` en lugar de device_id/animal_id; animal se resuelve mediante asociación histórica. `observed_at` con zona horaria obligatoria. Unique hardware/session/seq. Sin fix, lat/lon nulos; paquete tardío no rejuvenece estado ni recepción efectiva de comunicación.

La ingesta exige que `quality` sea un objeto JSON con valores finitos y hasta 16.384 caracteres al serializarlo.

Device: `{id,hardware_id,dev_eui,name,transport,enabled,interval_seconds,config_version,pending_config:{version,interval_seconds,status}|null,animal_id,assignment_id,last_received_at,can_delete}`. `animal_id` y `assignment_id` son `null` si no hay asociación vigente; `can_delete` indica ausencia de historial operativo, no autorización de escritura.

Sector: `{id,name}`. Geofence: `{id,sector_id,name,version,active,geometry,created_at}`. Event: `{id,animal_id,animal_name,diio,device_id,type,severity,condition:"active"|"resolved",attention:"pending"|"acknowledged"|"in_review"|"concluded",opened_at,resolved_at,detail,actions:[]}`.

Errores `{detail:string}` con 401 sin sesión, 403 permisos/CSRF/predio, 409 conflicto versión/identidad/asociación, 422 validación. Las pantallas mantienen el estado anterior si falla una escritura.


## Asociación actual e historial por animal

`collar_assignment`: `{id,device_id,valid_from,valid_to}` o `null`.

`pasture_assignment`: `{id,geofence_id,geofence_name,geofence_version,sector_id,sector_name,valid_from,valid_to}` o `null`.

`Association`: `{id,kind:"collar"|"pasture",valid_from,valid_to,active,assigned_by,assigned_by_name,device_id,device_name,hardware_id,geofence_id,geofence_name,geofence_version,sector_id,sector_name}`. Los campos de la otra clase de asociación son `null`. El acceso requiere sesión y animal del predio autorizado; las lecturas conservan su asignación histórica.

Cambiar de sector manualmente contradiciendo una asignación de pastoreo vigente devuelve 409; se debe asignar la nueva zona. Las nuevas geocercas y asignaciones exigen sector activo. Un reemplazo de collar no puede recortar lecturas ya persistidas de la asociación anterior. El cierre de eventos por reasignación conserva evidencia y atención, y no representa recuperación física del sensor.

## Detección y alta de collares

- `GET /v3/device-candidates?status=pending` → `{"items":[Candidate]}`. Usa el predio activo de la sesión. También admite `approved` y `dismissed`.
- `POST /v3/device-candidates` → 201 y `Candidate`. Envía `{hardware_id,transport,interval_seconds,dev_eui?,firmware_version?,source}`. `transport` admite `academic` y `lorawan`. `source` admite `usb` y `radio`. Usa la sesión del dueño o administrador con CSRF, o `X-Ingest-Key` para captura.
- `POST /v3/device-candidates/{id}/approve` → 200 y `{"device":Device,"candidate":Candidate}`. Envía `{name?,interval_seconds?,installed_at?,dev_eui?,enabled?}`. Puede enviarse `{}` para usar el nombre sugerido y los valores del candidato. La fecha omitida es la del alta y la habilitación predeterminada es `true`. LoRaWAN exige DevEUI. La creación queda auditada y la asignación al bovino se hace por separado. Un identificador ya registrado devuelve 409.
- `POST /v3/device-candidates/{id}/dismiss` → 200 y `Candidate` con `status:"dismissed"`. El descarte conserva el historial. Una detección nueva puede crear otro pendiente. Aprobar y descartar requiere sesión de dueño o administrador con predio activo y CSRF, con la misma política de MFA del alta manual.

La auditoría registra `device_candidate/detect` solo en la primera detección (el actor es el usuario en USB web y el servicio en captura), además de `approve` y `dismiss` con el estado anterior y posterior. `device/create` guarda en `after.origin` el origen del alta: `{"source":"manual"}` o `{"source":"usb"|"radio","candidate_id":…}`. Los gateways auditan `gateway_candidate/detect` en la primera detección USB o radio, y también `reserve`, `approve` y `dismiss`.

`Candidate` tiene `{id,hardware_id,transport,dev_eui,interval_seconds,firmware_version,source,first_seen_at,last_seen_at,seen_count,last_payload,status,suggested_name}`. `suggested_name` es el primer nombre libre de la serie `Collar 01`, `Collar 02`, etc. `last_payload` conserva el último mensaje de identificación o la trama normalizada, con coordenadas nulas si el GPS carece de fix.

La captura autenticada puede seleccionar un predio activo del mismo entorno con `X-Farm-ID`. Si se omite el encabezado, las detecciones requieren que exista un solo predio físico activo. De otro modo la API devuelve 409 y el capturador debe indicar el UUID. `GET /api/v1/v3/device-candidates/capture-farms` con `X-Ingest-Key` devuelve `items` con `id` y `name` de los predios físicos activos del entorno para que el asistente USB ofrezca la elección. Los despliegues en simulación rechazan detecciones físicas y esa consulta.

`POST /ingest/telemetry` y su alias `POST /telemetry` confirman collares académicos desconocidos con HTTP 201 y `{id,status:"candidate",duplicate,animal_id:null}`. En esta respuesta, `id` identifica el candidato. Una reentrega del mismo `hardware_id`, `session_id` y `seq` conserva su recibo aun después de la aprobación o el descarte. Las tramas detectadas permanecen fuera de `telemetry`. Después del alta, las nuevas tramas ingresan como telemetría.

Estos dos POST corresponden a los flujos locales. En producción la T3 base usa el lote HTTPS descrito abajo.

## Detección y alta de gateways

Rutas bajo `/api/v1/v3/gateway-candidates`, con autorización por predio y rol igual que el inventario de gateways.

- `GET ?status=pending|approved|dismissed` lista las detecciones del predio activo.
- `POST` registra una detección USB (`gateway_eui`, `node_id` opcional, `firmware`) con la clave de captura o la sesión de dueño o administrador con CSRF.
- `POST /{id}/reserve` reserva un nodo libre (1 o 2) para una detección USB pendiente; 409 si no quedan nodos.
- `POST /{id}/approve` crea el gateway con `name`, coordenadas opcionales y, para USB, `confirmed_eui` y `confirmed_node_id` devueltos por la placa tras `GEOCATTLE_SET_NODE_V1`. 409 si el EUI ya está registrado o el nodo está ocupado.
- `POST /{id}/dismiss` descarta la detección.

Un lote bus_v1 cuyo `origin_gateway` no corresponde a un gateway vigente crea una detección de origen radio sin bloquear la telemetría. Los gateways vinculados guardan `node_id` y las recepciones de primer salto se atribuyen al gateway de ese nodo.

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
| `p` | Intervalo anunciado, entre 30000 y 45000 ms |
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
- `GET /hardware/receiver` devuelve el estado del predio activo a dueño o administrador. En el PC, si existe el archivo del puente USB, usa ese estado con vigencia de 30 s. Una instalación de producción fuera de réplica recurre al último estado de la T3, con vigencia de 90 s desde su recepción en el servidor, cuando falta el archivo USB. En réplica consulta el [estado replicado del predio](#estado-usb-en-modo-espejo). Para el predio simulado devuelve estado no disponible.

### Lotes HTTPS de la receptora T3

`POST /api/v1/ingest/receiver-batch` requiere producción, `X-Ingest-Key` y `X-Farm-ID` de un predio físico activo. El cuerpo tiene `version: 1`, `status` y `records` con hasta ocho entradas. Cada entrada tiene `ref` positiva y única en el lote, `line` con el sobre bus_v1 de hasta 8192 bytes, `received_at` ISO 8601 con zona y `clock` (`synced`, `reconstructed` o `recovery`). La T3 puede enviar un sobre por lectura y conserva paquete, RSSI/SNR y ruta. Como en la base USB, `origin_gateway: 0` con `hops` y `path` en 0 indica un collar oído directo por la receptora.

El servidor comparte el parser USB y usa collar, sesión y secuencia para deduplicar. Resta el retardo del gateway, conserva coordenadas nulas sin fix y marca `quality.observed_at_estimated`, `quality.base_clock` y la recepción de la base en `quality.transport.base_received_at`. `recovery` indica que el reloj original de un arranque anterior carecía de calibración recuperable.

HTTP 200 devuelve `records` con `{ref,ids:[...]}` por sobre aceptado y persistido. Un sobre mal formado o rechazado devuelve `{ref,error}` sin aplicar cambios para ese sobre. Una reentrega mantiene los mismos identificadores. Un lote vacío informa el estado sin lecturas.

`status` incluye `connected`, `wifi_ssid`, `wifi_rssi_dbm`, `firmware`, `buffer_capacity`, `captured`, `pending`, `delivered`, `dropped`, `error`, `last_capture` y `updated_at`. El estado más reciente se guarda por predio y vence según la hora de recepción del servidor. [WAF y Access](DESPLIEGUE_DEBIAN_CLOUDFLARE.md#t3-base-almacenamiento-y-entrega)

Las asignaciones a bovinos siguen usando su fecha efectiva. El collar puede
consultarse antes de asignarlo; las capturas antiguas sin asignación se conservan.
Las pruebas de referencia están en `qa/test_lora_json.py`, `qa/test_lora_usb.py`,
`qa/test_esp32_contract.py` y `qa/test_hardware_api.py`.

## Registro de colaboradores mediante el dueño

- `POST /v3/invitations`: solo el dueño en su predio, con autorización MFA para esa operación. Admite correo y rol `worker` o `veterinarian`. Soporte administra colaboradores existentes pero no emite altas nuevas.
- `POST /v3/enrol/preview` `{token}`: valida vigencia, no consumo/revocación y cuenta/predio activos del entorno. Devuelve `{email,role_code,farm_name,expires_at,account_exists}`. El token se envía en el cuerpo. No crea cuenta ni membresía.
- `POST /v3/enrol` `{token,password,full_name?}`: consume la invitación. Cuenta nueva: nombre y contraseña de al menos doce caracteres. Cuenta existente: contraseña actual, sin cambiar nombre/hash. El rol y el predio proceden exclusivamente de la invitación.

La invitación dura 48 horas y se utiliza una sola vez. `POST /v3/invitations` devuelve el token y `delivery` con valor `manual` o `queued`. En modo automático incluye `invitation_url`, construida desde `INVITATION_BASE_URL`. La API encola el correo y el worker realiza el envío de forma asíncrona. `GET /v3/invitations` devuelve el estado de la invitación, `email_status` para el correo inicial y `acceptance_email_status` para la confirmación al dueño. `sent` indica que el servidor SMTP aceptó el mensaje. [Configuración SMTP](OPERACION.md#correo-smtp-de-invitaciones)

## Ficha y agenda sanitaria

- `GET /v3/health/product-policies` devuelve las reglas para el formulario autenticado. Cada tipo que admite productos indica si son obligatorios (`required`) y las vías disponibles (`routes`). En un procedimiento las vías son texto libre (`routes: null`).
- `POST /v3/changes` exige al menos un producto para vacuna y antibiótico. La vía oral figura en el catálogo de antibiótico. Procedimiento permite registrar productos cuando hubo una aplicación. Los demás eventos y las anulaciones deben omitir `treatments` o enviarlo vacío. Al corregir, se puede conservar una vía histórica del mismo producto y tipo de evento, salvo la vía oral para vacuna.
- La aprobación vuelve a validar las reglas. Las propuestas históricas incompatibles se pueden consultar y rechazar desde la bandeja del dueño.
- Al completar una atención se conserva el tipo del plan vigente. `completed_event_id` identifica un evento efectivo de la misma permanencia. Para vacunación y antibiótico, el evento debe coincidir con el tipo planificado.
- `GET /v3/animals/{id}/record` devuelve los productos completos de cada evento sanitario incluido en la ficha, con los campos de lote, registro del producto y fundamento del resguardo cuando constan.

## Reportes del rebaño

- `GET /v3/animal-reports/{kind}` consulta el predio activo para dueño, administrador con predio, veterinario o trabajador. `kind` admite `inventario`, `sanidad`, `agenda`, `mediciones`, `observaciones`, `asignaciones`, `alertas` y `actividad`. `animal_id` es opcional y se valida dentro del predio.
- `start` y `end` son fechas inclusivas en la zona horaria del predio. Una fecha consulta ese día. Sin fechas se usa el día actual del predio. El período admite hasta 366 días. El inventario muestra el estado actual.
- El JSON devuelve `columns`, hasta 25 filas en `items`, `total`, `timezone`, `start` y `end`. `format=xlsx` y `format=csv` descargan todas las filas del mismo filtro. Si el resultado supera 50.000 filas, ambos formatos responden 422 para acotar el filtro. Un resultado vacío conserva los encabezados.
- Sanidad incluye únicamente eventos efectivos. Cada producto tiene una fila con el mismo identificador del evento. Los eventos sin producto ocupan una fila. Agenda muestra la última versión de cada atención, incluidas completadas y canceladas, por fecha planificada. Asignaciones muestra vigencias que intersectan el período. Alertas usa fecha de apertura. Actividad agrupa por día, bovino y origen. Las cifras de movimiento indican muestras.

### Indicadores del predio

Los reportes `totales`, `serie-alertas`, `ranking-movimiento` y `ranking-salidas` usan la misma URL y formatos que los registros. Requieren sesión de dueño o administrador con un predio activo. El filtro `animal_id` se reserva para los reportes de registros.

- `totales` devuelve el corte actual con bovinos activos de permanencia vigente, collares inventariados y asignados, y el número y nombre de los módulos habilitados.
- `serie-alertas` admite `grain=day|week|month` y `alert_type=all` o un tipo de alerta. Cuenta aperturas por hora local, con semanas desde el lunes e intervalos recortados al rango solicitado. Incluye intervalos con cero aperturas y días con lecturas ligadas a una asignación.
- `ranking-movimiento` usa la proporción de muestras en movimiento entre las clasificadas como movimiento o reposo. `ranking-salidas` cuenta alertas `escape` abiertas en el período e indica sus geocercas. Para la cobertura de salidas usa posiciones GNSS válidas durante una asignación de pastoreo.
- Para asignar un puesto, los rankings de la primera versión exigen 10 muestras válidas para su métrica y cobertura de al menos la mitad de los días transcurridos del período. El ranking de salidas además exige una alerta registrada. Los empates comparten puesto y las filas con cobertura insuficiente muestran sus cifras observadas sin puesto.

### Exportaciones tabulares

- **Excel (`.xlsx`)**: incluye la hoja del reporte con encabezados inmovilizados y autofiltro, y la hoja `Metadatos` con predio, período, filtros, zona horaria y momento de generación. Conserva identificadores como texto (incluidos ceros iniciales), medidas y conteos como números, fechas y horas como celdas de fecha en la zona del predio, y booleanos como `Sí`/`No`. Los textos no se evalúan como fórmulas.
- **Etiquetas**: la vista previa, el CSV y el Excel de Reportes del rebaño muestran en español los valores codificados (tipo y operación sanitaria, tipo de atención, estado vital, orientación, sexo, tipo, severidad, condición y atención de alertas, y origen de la actividad). El libro de telemetría usa encabezados en español, identifica DIIO, bovino y collar en lugar de los identificadores internos, y aplica formatos numéricos a coordenadas, temperatura, actividad y batería; el CSV de telemetría conserva sus columnas y códigos para integraciones.
- **CSV (`.csv`)**: los endpoints conservan el separador `,` y el punto decimal por defecto para integraciones. Ambos emiten UTF-8 con BOM y fechas ISO 8601 (con desplazamiento para marcas de tiempo). Telemetría conserva sus columnas y sus booleanos `True`/`False` por defecto; ahora separa fecha y hora con `T`. Si se solicita `delimiter=semicolon`, emite `;`, coma decimal y booleanos `Sí`/`No`; las horas usan la zona del predio. Los valores de texto que podrían interpretarse como fórmulas se escapan con apóstrofo. La interfaz ofrece Excel primero y solicita el CSV con `delimiter=semicolon` como alternativa regional. Excel nativo es el formato recomendado para conservar los tipos sin depender de cómo se importe el CSV.
- **Telemetría**: ambos endpoints requieren sesión y predio activo. `start` (inclusivo) y `end` (exclusivo) admiten marcas de tiempo con zona; como alternativa se admite `day=AAAA-MM-DD` en la zona del predio. `animal_id` se valida en el predio; `hardware_id` filtra el collar solamente dentro del mismo predio. Ambos formatos conservan las primeras 50.000 lecturas ordenadas por observación y anuncian el tope en `X-Export-Limit`. Las descargas de historial en la interfaz cubren todo el filtro aplicado, no solo la página visible. La exportación JSONL de recepción sigue limitada a la página visible y no cambia.

#### Exportación del dueño

Todas las rutas siguientes son `GET` y usan el predio autorizado seleccionado en la sesión, sin aceptar otro `farm_id`. Acceso de dueño o administrador con predio seleccionado; requieren sesión válida y el MFA que aplica a la sesión de administrador. No requieren CSRF ni autorización de operación, reservados para escrituras. Los reportes no modifican inventario ni telemetría; conservan el registro normal de sesión y métricas HTTP.

| Ruta | Vista previa (`format=json`, por defecto) | Descarga |
| --- | --- | --- |
| `/v3/owner-exports/metricas` | `metrics`: los 7 KPI que el sistema calcula con sus registros (K01, K02, K03, K05, K06, K08 y K09), incluso sin mediciones. K04, K07, K10, K11 y K12 requieren ensayo o registro manual y no se exportan. | `format=xlsx` (`Métricas`, `Metadatos`) o `format=csv`. |
| `/v3/owner-exports/dispositivos` | `summary` con `collars`, `gateways`, `withdrawn_collars`, `withdrawn_gateways`; `collars` y `gateways` con hasta cinco registros de cada tipo. | `format=xlsx` (`Collares`, `Gateways`, `Metadatos`) o `format=csv` (una tabla con `Tipo` = `Collar` o `Gateway`, celdas vacías para campos no aplicables). |
| `/v3/owner-exports/telemetria` | `summary` con `readings`, `collars`, `days`, `first_at`, `last_at`; `daily` con hasta 60 filas del registro diario. | `format=xlsx` (`Lecturas`, `Metadatos`) o `format=csv`: cada lectura del período con collar, DIIO y bovino, secuencia, observación, recepción, GPS, temperatura, actividad, movimiento y batería. 422 sobre 50.000 filas. |
| `/v3/owner-exports/diario` | Igual que `telemetria`. | `format=xlsx` (`Registro diario`, `Metadatos`) o `format=csv`: una fila por día local y collar con lecturas, posiciones, temperaturas mín./máx., reposo/movimiento, batería mín./máx. y primera/última lectura. |
| `/v3/owner-exports/general` | No disponible. | `format=xlsx` (`Métricas`, `Collares`, `Gateways`, `Registro diario`, `Metadatos`). |

- **Período**: `start` y `end` (`AAAA-MM-DD`, inclusivos, hasta 366 días) se interpretan en la zona del predio. Si falta solo uno, se usa el que se informó; si faltan ambos, se usa el día local actual. Alternativamente, `days=7` o `days=30` incluye hoy y los días anteriores. Los conteos usan de medianoche inicial hasta la medianoche posterior al último día, sin contar observaciones futuras. Los rangos invertidos, demasiado largos o combinados con `days` devuelven 422. La vista previa devuelve `farm_id`, `farm_name`, `environment`, `origin`, `timezone`, `start`, `end` y `generated_at`.
- **Origen**: los predios de simulación solo incluyen `telemetry.source='sim'`; los demás, `academic` o `lorawan`. Las recepciones y eventos enlazados respetan esa misma selección. Asignaciones, inventario y métricas HTTP se limitan al ámbito del predio; no se cruzan con otros entornos. Se indica el origen en `Metadatos` y en cada fila CSV. Los KPI excluyen los collares retirados al generar y, para recepciones, también gateways retirados o archivados. El informe de dispositivos incluye las bajas con fecha y motivo cuando constan. Los motivos de retiro de collar se toman del mantenimiento de tipo retiro; los gateways no registran motivo de archivo.
- **Archivos**: `geocattle-<informe>-<predio>-<desde>-<hasta>.<formato>`. Este CSV usa `;`, coma decimal y UTF-8 con BOM por defecto; `delimiter=comma` cambia a coma y punto decimal. Inventario y combinado devuelven 422 si exceden 50.000 filas de dispositivos (collares y gateways sumados). JSON y descargas no se almacenan en caché.
- **Inventario**: una fila por collar (`hardware_id`, `dev_eui`, nombre, transporte, estado, firmware, intervalo, instalación, última observación, última recepción, último voltaje disponible, lecturas del período, DIIO y nombre del bovino vigente, inicio de asignación, cantidad de asignaciones cerradas, fecha y motivo de baja). Una fila por gateway (EUI, nombre, estado, longitud/latitud, instalación, última comunicación, nodo, recepciones del período, baja). Los conteos usan la hora de observación de la lectura o la hora de recepción del gateway, respectivamente. El inventario, las asignaciones vigentes y los campos de última lectura/comunicación son al generar, no al final del período histórico seleccionado.
- **Métrica**: `code`, `name`, `value`, `unit`, `target`, `status` (`Sí`, `No`, `Sin datos`), `numerator`, `denominator` (o tamaño de muestra), `window`, `method`, `observation`, `secondary_value`, `secondary_label`. `null` significa «no disponible» o «no aplica», no cero. Las comparaciones usan el valor antes del redondeo. K01 y K02 evalúan aproximaciones operativas, no certifican la aceptación del informe.

| KPI | Fórmula y alcance | Meta |
| --- | --- | --- |
| K01 Entrega útil | Únicos válidos ÷ suma de `max(seq) − min(seq) + 1` por collar y sesión × 100. Usa lecturas persistidas del período; solo estima pérdidas entre los extremos recibidos y no ve sesiones sin recepción. | ≥95 % |
| K02 Posición vigente | Lecturas con GNSS válido y `0 ≤ received_at − observed_at ≤ 2T + 30 s` ÷ lecturas con asignación bovina válida × 100. Aproximación por lectura, no por animal-minuto; `T` usa `quality.period_ms` numérico entre 1 y 86.400.000 ms o, como respaldo, la configuración aplicada de la versión registrada y luego el intervalo actual. | ≥95 % |
| K03 Procesamiento | p50 y p95 de `events.opened_at − telemetry.received_at` en segundos, para aperturas en el período con lectura desencadenante enlazada. Excluye desconexiones, expiraciones de configuración y duraciones negativas. | p95 ≤2 s |
| K05 Integridad | Únicos por collar, sesión y secuencia ÷ lecturas persistidas × 100. Muestra duplicados persistidos y recepciones adicionales en otros gateways por separado. Un duplicado persistido incumple; en su ausencia, la unicidad no demuestra recuperación y los reintentos descartados no se cuentan: `Sin datos` para la meta. | 100 % de lecturas recuperadas sin duplicados |
| K06 Consulta | p95 de `duration_ms` en segundos y `100 × HTTP ≥400 / GET registrados`: solo `/dashboard`, `/animals`, `/animals/{animal_id}` y `/events`, correspondientes al predio y al período. | p95 ≤1 s y error <1 % |
| K08 Autonomía comercial | Indicador auxiliar: promedio de `último mV − primer mV` por collar con al menos dos lecturas con voltaje. No mide días ni separa recarga/reemplazo. | ≥7 días con T = 300 s; autonomía no medida |
| K09 Falsos avisos | Indicador auxiliar: `100 × alertas de salida / horas-animal` dentro de la intersección entre período, asignación y permanencia bovina. El numerador cuenta salidas enlazadas a una lectura de esa asignación dentro de la intersección. El sistema no clasifica falsos avisos sin contraste de campo. | ≤1 falso aviso / 100 h-animal; clasificación no medida |

## Solicitudes y avisos

- `POST /auth/account/close-request` con `{password,code?,reason}` reautentica al titular y devuelve `{requested,request_id,status}`. Si hay una solicitud de cierre pendiente, devuelve su folio.
- `POST /auth/mfa/setup` con `{password}` inicia la inscripción de una cuenta con sesión y sin factor activo. `POST /auth/mfa/replace` con `{password,code}` o `{password,recovery_code}` inicia el reemplazo de un factor activo. Ambos devuelven un desafío vinculado a la sesión y al factor pendiente, junto con `secret` y `otpauth_uri`.
- `POST /auth/mfa/verify` con `{challenge_token,code}` verifica el factor asociado al desafío. Un desafío iniciado en el perfil requiere la misma sesión y CSRF. El desafío vence en cinco minutos. Al verificar un reemplazo, se conserva la sesión actual, se retira el factor anterior y se invalidan las demás sesiones, los códigos de recuperación y las autorizaciones sensibles pendientes.
- `POST /auth/mfa/remove` con la misma prueba de identidad que `/auth/mfa/replace` retira el factor del titular, limpia la cookie, revoca las sesiones y devuelve `{removed,enrollment_required}`. Si la política exige MFA, el siguiente ingreso requiere inscripción. Reemplazar y quitar requieren sesión y CSRF, comparten el límite de reautenticación y consumen cualquier código de recuperación usado.
- `POST /auth/support-requests` con `{kind,description}` crea un caso privado de tipo `change_email` o `access_issue`. La descripción admite entre 1 y 2000 caracteres tras recortar espacios. En el PC responde `201` con `{request_id,status:"pending"}`. En réplica, la creación se [encola](#escrituras-en-replica). `GET /auth/support-requests` lista los propios, con `status`, `limit` y `offset` opcionales. `admin=true` requiere administrador en contexto global y abre la bandeja de plataforma.
- `POST /auth/support-requests/{id}/decision` requiere administrador en contexto global y guarda `{status,response}` con resultado `resolved` o `rejected`. El titular confirma la lectura mediante `POST /auth/support-requests/{id}/read`. La decisión resuelve el caso y comunica el resultado.
- `GET /v3/changes` acepta `status`, `limit` y `offset`. `GET /v3/changes/{id}` aplica el mismo ámbito de predio y autoría. En el predio, dueño y administrador pueden revisar las propuestas y los demás perfiles consultan las propias.
- `GET /v3/notifications` acepta `unread`, `limit` y `offset`. Los avisos de propuestas incluyen `request_id`. `GET /v3/activity-counts` devuelve `unread_notices`, `pending_changes`, `unread_support` y `pending_support` dentro del ámbito de la sesión.
- La auditoría de predio excluye los casos privados de cuenta. Los nuevos eventos de cambio de contexto guardan `before` y `after` con el ámbito y, para un predio, su identidad y nombre.
- `GET /v3/audit/export?format=xlsx|csv` acepta los mismos filtros que `GET /v3/audit` (`q`, `actor_id`, `action`, `entity`, `farm_id`, `start`, `end`) y el `delimiter` de las exportaciones. Aplica el mismo ámbito: el dueño exporta su predio y el administrador la plataforma o un predio. Las columnas son fecha, actor, usuario, entidad, identificador, acción, predio y los estados anterior y posterior en JSON. Más de 50.000 filas devuelven 422. Cada descarga queda auditada como `audit_log/export_audit`.

## Configuración desde el panel de alertas

El dueño y el administrador con predio seleccionado pueden ajustar los parámetros mediante **Alertas y atención → Configurar alertas**. Se comparte formulario y versión con **Reglas del predio**. GET/PUT `/settings` incorporan `capabilities` con los permisos de edición, el entorno y la disponibilidad de activación preventiva. `temperature_rule_allowed` informa el permiso específico de temperatura. Los permisos se calculan en el servidor y los datos de auditoría conservan los parámetros de la regla. Ver [configuración de alertas](CONFIGURACION_ALERTAS.md).

## Modo espejo

`MIRROR_MODE` define el papel de la instalación ([plan](planificacion/PLAN_MODO_ESPEJO.md)):

- `off` (predeterminado): comportamiento actual.
- `field` identifica al PC del campo que publica las tablas, consulta la bandeja y aplica sus envíos. Requiere `MIRROR_SERVER_URL` con HTTPS. En desarrollo y simulación admite HTTP en `localhost` y `127.0.0.1`. Comparte `MIRROR_SYNC_KEY` con el servidor (32 caracteres o más) y acepta `MIRROR_ACCESS_ID` y `MIRROR_ACCESS_SECRET` como par para Cloudflare Access. `MIRROR_REMOTE_ADMIN` y `MIRROR_REMOTE_CHANGES` (verdaderos por defecto) controlan cada tipo de envío.
- `replica` identifica al servidor web. Las tablas de `mirror_tables.MIRROR` llegan solo por la suscripción y `geocattle_app` tiene únicamente `SELECT` sobre ellas. `MIRROR_SOURCE_ENVIRONMENT` (`development` o `production`, predeterminado `development`) fija el entorno de los predios visibles. Ambas instalaciones usan el mismo `MIRROR_SOURCE` (predeterminado `campo`) para identificar el pulso y la misma clave de cifrado MFA para leer los factores del campo.

### Estado USB en modo espejo

En `field`, el worker lee el archivo definido por `USB_STATUS_PATH` y publica su contenido en `receiver_status`. Usa el mismo destino que la ingesta física. Configura el mismo `INGEST_FARM_ID` en el worker y en la captura cuando hay varios predios físicos activos. Si falta el UUID, el worker publica solo cuando el entorno tiene un único predio físico activo. Un UUID inválido o un archivo ausente o ilegible omite la publicación del ciclo.

El prototipo de Windows entrega al worker la ruta `.runtime/capture/status.json`. En Docker de desarrollo, `compose.usb.yaml` monta `USB_CAPTURE_DIR` como `/capture` de solo lectura para la API y el worker, y les entrega la configuración de campo.

Se conservan los campos del USB, incluidos `receiver_mode`, `captured`, `delivered`, `pending` y `last_capture`. La fila usa `updated_at` del archivo como `received_at`, con tope en la hora actual del worker. Una fecha repetida conserva la fila existente. Un snapshot anterior tampoco reemplaza una fila más reciente.

La réplica devuelve esa misma estructura de estado USB por `GET /hardware/receiver` a dueño y administrador del predio. Calcula `available` con una vigencia de 90 s a partir de `received_at` y devuelve `connected: false` cuando vence.

### Escrituras en `replica`

- Las escrituras de la lista permitida responden `202` con `{"queued": true, "outbox_id": UUID, "status": "queued"}` y guardan el envío en `mirror_outbox`.
- El administrador de plataforma puede encolar `POST /api/v1/v3/admin/owners`, `PATCH /api/v1/v3/admin/owners/{id}`, `PATCH /api/v1/v3/admin/users/{id}`, `POST /api/v1/v3/admin/users/{id}/owner` y `POST /api/v1/auth/support-requests/{id}/decision`. La decisión de soporte requiere el contexto global. Con predio activo también puede encolar `POST /api/v1/v3/changes` y `POST /api/v1/v3/changes/{id}/decision` para solicitudes ajenas al reemplazo de batería. El tipo es `admin_order`. La contraseña inicial de un alta de dueño viaja cifrada en la bandeja.
- El veterinario con predio activo puede encolar `POST /api/v1/v3/changes` con `animal_profile`, `health_record` o `health_schedule` (`remote_change`) y las escrituras de sus borradores (`draft_revision`).
- Cualquier cuenta autenticada puede encolar `POST /api/v1/auth/support-requests` como `support_request`, con `farm_id: null`. Requiere sesión, CSRF, MFA cuando aplica y `MIRROR_REMOTE_CHANGES=true` en la réplica y en el PC.
- Toda otra escritura responde `403` con `Este cambio se registra en el PC del campo`. Las ingestas `/api/v1/ingest/*` también responden `403`, porque la telemetría llega por la réplica.
- El inicio y cierre de sesión, el cambio de predio, la verificación de TOTP ya inscrito, las métricas HTTP y la marca de lectura de avisos se guardan en tablas propias del servidor. El contador anti-reuso de TOTP se guarda en `mirror_totp_use` y la auditoría web en `mirror_audit_log`. La inscripción, recuperación y los demás cambios de credenciales se realizan en el PC.
- El worker no calcula alertas, no envía avisos ni correos y no despacha configuraciones.

### Bandeja y resultados

- `GET /api/v1/mirror/inbox?limit=50` exige `X-Mirror-Key`. Entrega en orden de creación los envíos sin resultado replicado, con `id`, `kind`, `actor_id`, `farm_id`, `method`, `path`, `body` y `created_at`. Marca cada envío como `delivered` y suma un intento. Si se repite, entrega los mismos envíos hasta que llegue su resultado.
- El PC aplica cada envío una sola vez por su `id`. Comprueba que el actor exista, esté activo y cumpla los requisitos del tipo de envío. Reproduce la operación dentro de su propia API con ese actor y guarda el resultado en `mirror_inbox_results` (`applied`, `pending_owner`, `rejected`, `conflict` o `failed`). Ese resultado vuelve al servidor por la réplica.
- `remote_change` usa el `id` del envío como `idempotency_key`. Queda pendiente del dueño aunque el actor pueda aplicar directo en el PC.
- `support_request` usa el `id` del envío como folio y atribuye el caso a la cuenta que lo envió. «Mis envíos» muestra `applied` cuando se crea el caso. «Mis solicitudes a soporte» lo muestra como `pending` hasta la respuesta de administración.
- `GET /api/v1/mirror/info`, con sesión, entrega `mode`, `source_environment`, `heartbeat_at` y `field_online` (pulso de menos de 60 s). En `off` entrega `{"mode":"off"}`. `GET /api/v1/mirror/submissions` entrega `{items,total}` con los envíos del usuario identificados por `outbox_id`, su estado derivado (`queued`, `delivered` o el estado del resultado) y `result`. Un resultado `pending_owner` pasa a `applied` o `rejected` (con `result.reason`) cuando llega por la réplica la decisión del dueño. `GET /api/v1/mirror/status` es exclusivo del administrador e incluye `heartbeat`, `submission_counts` y `subscription` con la edad del último avance WAL informado cuando PostgreSQL expone esa métrica.
- En `field`, el worker actualiza `mirror_heartbeat` cada ciclo con la versión de esquema y la hora de la última consulta a la bandeja.

### Borradores

`/api/v1/v3/drafts` devuelve `{items,total}` con los borradores del autor en el predio activo. `POST` recibe `id` UUID del cliente, `action`, `animal_id` y `payload`, y conserva la versión esperada de la ficha del bovino (`expected_version`, predeterminada a la versión visible al guardar). `PUT /{id}` exige `base_version` y `payload`. `POST /{id}/submit` y `DELETE /{id}` admiten `base_version` y devuelven `409` si la versión indicada ya cambió. Un `PUT` obsoleto devuelve `409`, `draft_id` y `conflict_id` y guarda un borrador hermano con `conflict_of`. Enviar crea la solicitud con el UUID del borrador como clave de idempotencia y lo marca `submitted`.

En `replica` cada escritura se encola como `draft_revision`. `GET` superpone el último cambio pendiente sobre el borrador y devuelve `status: "pending_sync"`, `pending_sync: true` y `pending_operation` (`save`, `submit` o `discard`). Las revisiones, envíos y descartes guardan `after_outbox_id` con el UUID de la última operación del autor sobre ese borrador que aún no tenga resultado, o `null`. Si un envío o descarte omite `base_version`, la réplica registra la versión que se muestra en ese momento. El PC espera el resultado del predecesor y procede cuando su estado es `applied`. Un resultado previo distinto de `applied` marca el envío dependiente como `conflict`. La solicitud nacida de un borrador enviado por el veterinario desde la réplica queda pendiente del dueño.
