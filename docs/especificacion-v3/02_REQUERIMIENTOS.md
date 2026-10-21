# GeoCattle V3 — Requerimientos

Requisitos propuestos a partir de los cuatro perfiles y del alcance previo. Las metas cuantitativas son criterios de aceptación, no resultados alcanzados. RF-43 es extensión P2; los demás cubren núcleo y flujo solicitado.

## Funcionales

| ID | Requisito | Criterio de aceptación | Casos |
|---|---|---|---|
| RF-01 | Autenticar identidad única | Correo normalizado y contraseña válida; usuario suspendido no obtiene sesión. No se duplica una cuenta por trabajar en varios predios. | CU-01 |
| RF-02 | Exigir MFA al administrador | El panel global no emite sesión utilizable sin segundo factor verificado; recuperación no omite MFA permanentemente. | CU-01 |
| RF-03 | Verificar operaciones sensibles del dueño | Administrar colaboradores exige step-up reciente: lectura de lista en ventana de 10 min y desafío de un solo uso ligado al contenido de cada alta, cambio o baja. Cambiar correo, clave o factor exige reautenticación. | CU-13, CU-07 |
| RF-04 | Cerrar y recuperar sesiones | Cerrar sesión revoca token; cambio de contraseña o suspensión revoca todas las sesiones; recuperación usa token de un solo uso y vencimiento. | CU-02 |
| RF-05 | Administrar clientes | Administrador crea, consulta, modifica y desactiva dueños/cuentas; suspensión no elimina animales ni auditoría. | CU-03 |
| RF-06 | Administrar colaboradores desde plataforma | Administrador administra trabajadores y veterinarios existentes, conserva creador/contexto y no se convierte en el usuario mediante su contraseña. | CU-04 |
| RF-07 | Mostrar KPIs globales y por dueño | Reportar usuarios globales únicos, animales con permanencia activa, predios/sectores activos, collares instalados y módulos de software habilitados; filtrar por cuenta sin duplicar personas por membresías. | CU-05 |
| RF-08 | Contar alertas diarias | Agrupar alertas por fecha de apertura en zona del predio, con filtros de dueño/predio/período; un reintento de aviso no incrementa alertas. | CU-05 |
| RF-09 | Consultar auditoría | Administrador filtra auditoría global y predial por actor, fecha, entidad y acción; la lectura de auditoría queda registrada; ningún perfil edita sus filas. | CU-06 |
| RF-10 | Inspeccionar consumo y peticiones | Ver volumen de peticiones, errores, p95 de duración y bytes por período/cuenta, más métricas de CPU/RAM/disco del sistema de observabilidad; no registrar cuerpos ni secretos. | CU-06 |
| RF-11 | Administrar predios propios | Dueño crea uno o varios predios hasta cupo configurado, consulta, modifica y desactiva sin borrar historia. Dos altas concurrentes no exceden cupo. | CU-08 |
| RF-12 | Administrar sectores | Crear, consultar, modificar uso/nombre y desactivar sectores de predios propios; uso distingue pastoreo, disponible, siembra, restringido y otro. | CU-09 |
| RF-13 | Editar puntos de geocerca | Crear/mover/agregar/quitar puntos y previsualizar; guardar exige al menos cuatro vértices distintos, cierre automático y polígono simple válido. Cada cambio crea versión. | CU-10 |
| RF-14 | Registrar bovinos | Dueño registra DIIO único como texto, especie bovina, sexo, raza/color opcionales y fecha de nacimiento conocida o estimada; un duplicado se rechaza. | CU-11 |
| RF-15 | Conservar mediciones | Peso en kg y altura en cm con fecha y autor; no sobrescribir medidas históricas. Edad calculada desde nacimiento; fecha desconocida se muestra desconocida. | CU-11, CU-22 |
| RF-16 | Asignar collar al bovino | Un collar y un animal tienen como máximo una asignación simultánea, mismo predio y dentro de permanencia; reasignar conserva historia. | CU-12 |
| RF-17 | Asignar pastoreo | Una geocerca por animal en cada instante, varios animales por geocerca; vigencia contenida en permanencia y versión de geocerca. | CU-12 |
| RF-18 | Invitar trabajador o veterinario | Dueño elige predio, correo y rol; se crea invitación con token hash, expiración 48 h propuesta y notificación. No enviar contraseña inicial reutilizable. | CU-13 |
| RF-19 | Aceptar enrolamiento | Invitado verifica correo, acepta invitación vigente y define credencial o usa cuenta existente del mismo correo; se crea membresía una sola vez. | CU-14 |
| RF-20 | Administrar acceso de colaboradores | Dueño consulta/modifica/cierra membresías solo en sus predios con verificación; retirar acceso no borra la cuenta si participa en otro predio. | CU-13 |
| RF-21 | Administrar perfil propio | Cada usuario consulta y cambia nombre/teléfono; correo requiere verificación; no modifica rol, predio, confianza ni identidad de otro. Eliminar perfil implica solicitar cierre, no borrar auditoría. | CU-07 |
| RF-22 | Consultar mapa autorizado | Dueño, trabajador y veterinario ven predio, sectores, geocercas, animales y gateways de su alcance; cada lectura muestra calidad y antigüedad. | CU-15 |
| RF-23 | Consultar ficha completa | Mostrar DIIO/collar, descripción, estado vital y técnico separados, temperatura superficial con hora, últimas medidas, historia sanitaria y próximas atenciones; valores ausentes no se muestran como cero. | CU-16 |
| RF-24 | Proponer registro sanitario por trabajador | Vacuna/antibiótico administrado se guarda como solicitud pendiente; se notifica al dueño y la ficha efectiva no cambia antes de aprobación. No equivale a prescripción. | CU-17 |
| RF-25 | Proponer estado o reporte | Trabajador propone cambio de estado o reporte del animal con motivo; pendiente se diferencia de efectivo. | CU-18 |
| RF-26 | Reportar reemplazo de batería | Trabajador identifica módulo, batería/observación y hora; aprobación afecta el registro confirmado, nunca inventa mV de sensor. | CU-19 |
| RF-27 | Aprobar o rechazar cambios | Dueño revisa contenido/autor/fecha y versión base; aprobar aplica exactamente una vez en transacción; rechazar exige motivo y no cambia el registro efectivo. | CU-20 |
| RF-28 | Detectar conflictos de aprobación | Si cambió la versión base, responder conflicto y conservar solicitud pendiente para reformulación/rechazo; nunca sobrescribir silenciosamente datos más nuevos. | CU-20 |
| RF-29 | Configurar confianza granular | Dueño concede/revoca por trabajador, predio y acción permitida. Se valida al aplicar, registra concesión utilizada y no autoriza gestión de cuentas ni geocercas. | CU-21 |
| RF-30 | Aplicar cambios directos veterinarios | Veterinario vigente edita ficha técnica y registra/corrige/anula salud directamente, con solicitud y decisión directa auditadas, sin aprobación del dueño. | CU-22, CU-23 |
| RF-31 | Preservar historia sanitaria | Corrección o baja lógica agrega sucesor al evento original; no permite cambiar DIIO, predio ni permisos desde una ficha. Los originales siguen consultables. | CU-23 |
| RF-32 | Detallar tratamientos | Registrar producto, dosis/unidad, vía, hora, lote opcional y resguardo informado; varios productos por evento. Datos no conocidos se distinguen explícitamente. | CU-17, CU-23 |
| RF-33 | Planificar próximas atenciones | Dueño/veterinario registra vacuna, control o antibiótico planificado con fecha, reemplaza/cancela por sucesor y vincula administración real al completar. Recordatorio no certifica administración. | CU-24 |
| RF-34 | Gestionar gateways | Dueño/admin registra gateway, ubicación y estado; mapa lo diferencia de collar; contador y última recepción no implican cobertura comprobada. | CU-25 |
| RF-35 | Ingerir telemetría idempotente | Servicio autenticado valida y deduplica por dispositivo/sesión/secuencia; lectura atrasada conserva asignación de captura y no reemplaza estado más reciente. | CU-26 |
| RF-36 | Conservar recepción multiantena | Una lectura recibida por varias antenas permanece una sola lectura con varias recepciones RSSI/SNR. | CU-26 |
| RF-37 | Evaluar y atender alertas | Preservar reglas actuales: dos posiciones exteriores válidas, borde interior, comunicación independiente y estado desconocido ante datos insuficientes; atención no resuelve condición técnica. | CU-27 |
| RF-38 | Consultar historias y filtros | Mapa/ficha permite filtros por predio/sector/animal y períodos 24 h, 7 d, 30 d o rango; paginación, orden estable y vacío explícito. | CU-16 |
| RF-39 | Confirmar configuración IoT | Dueño solicita intervalo y seguimiento solicitado/enviado/aplicado/fallido; solo versión confirmada cambia intervalo efectivo. | CU-28 |
| RF-40 | Notificar sin bloquear operación | Aviso interno persistido con operación, envío externo con reintentos y resultados; fallo externo no borra la solicitud ni la alerta. | CU-17, CU-20, CU-24, CU-28 |
| RF-41 | Auditar cambios de privilegios y negocio | Registrar actor, contexto, acción, fecha y cambios pertinentes; jamás contraseña/token/semilla MFA. Administración global también se audita. | CU-03, CU-04, CU-06, CU-21 |
| RF-42 | Separar consulta global y predial | Administrador global ve todas las cuentas mediante panel global; dueño solo su cuenta; colaborador solo predios con membresía vigente. Cada API valida alcance. | CU-01, CU-15 |
| RF-43 | Gestionar FMA como extensión | Conservar cabecera/detalle/historia de movimiento; borrador editable, confirmado congelado; confirmar externamente exige evidencia y ejecución verificada actualiza permanencias. | CU-29 |
| RF-44 | Distinguir módulos físicos y funcionales | Panel nombra collares instalados, collares inventariados y módulos de software habilitados por separado; no agrega denominadores diferentes. | CU-05 |

## No funcionales

| ID | Atributo | Criterio verificable | Evidencia |
|---|---|---|---|
| RNF-01 | Aislamiento | 100% de operaciones con IDs ajenos deben responder denegación sin filtrar datos; matriz de prueba con dos dueños y un colaborador compartido. | API y pruebas de autorización negativas. |
| RNF-02 | MFA y step-up | Administradores sin MFA no acceden al panel; retos de escritura de un uso, ligados a operación, con 5 min de vigencia; lectura sensible 10 min propuesta. | Pruebas de replay, caducidad y cambio de payload. |
| RNF-03 | Credenciales y transporte | TLS en despliegue; contraseñas con Argon2id y parámetros medidos; secretos MFA cifrados con clave fuera de la BD; tokens almacenados con hash. | Revisión de configuración, datos y respuestas. |
| RNF-04 | Sesiones | Cookie HttpOnly/Secure/SameSite; CSRF en escrituras; propuesta de 30 min inactiva y 12 h absoluta, ajustable; suspensión revoca. | Pruebas de sesión/CSRF y relojes controlados. |
| RNF-05 | Resistencia a abuso | 5 fallos consecutivos por cuenta/contexto disparan espera progresiva y límites por IP, sin bloqueo permanente; recuperación no revela existencia de cuenta. | Pruebas de fuerza bruta y enumeración. |
| RNF-06 | Atomicidad e idempotencia | Una decisión y una aplicación por solicitud; ningún cambio efectivo sobrevive si falla auditoría/cola transaccional; un uplink duplicado no crea lectura. | Pruebas con fallos inyectados y concurrencia. |
| RNF-07 | Integridad histórica | Exclusión de intervalos, FK de predio y triggers de inmutabilidad rechazan entradas inválidas; usuario runtime no es propietario del esquema ni puede desactivar triggers. | Pruebas SQL y revisión de grants. |
| RNF-08 | Rendimiento de consulta | Meta heredada: p95 GET estado <=1 s y error <1%, con 70 nodos, 5 clientes concurrentes y 10 min de carga; no es medición conseguida. | Ensayo de carga reproducible. |
| RNF-09 | Procesamiento | Meta heredada: p95 recepción a evento <=2 s en >=100 eventos controlados; detección del cruce depende de frecuencia, GNSS y radio. | Medición de marcas del servidor. |
| RNF-10 | Capacidad | Escenario inicial 70 collares a 300 s: 20.160 lecturas/día; dimensionar índices, recepciones y backups con bytes reales. | Carga con datos realistas, no aproximación como capacidad certificada. |
| RNF-11 | Disponibilidad local | Meta heredada >=99% en 7 días con monitor cada minuto, incluyendo mantenimiento, condicionada a energía/LAN/servidor/radio. | Registro continuo del piloto. |
| RNF-12 | Recuperación | Meta heredada RPO <=24 h y RTO <=2 h; backup diario y restauración en base vacía antes del piloto. | Ensayo documentado de restauración. |
| RNF-13 | Sin Internet | Conservar ingestión, ficha, mapa vectorial local y alertas mientras infraestructura local esté disponible; avisos externos quedan pendientes. | Corte WAN controlado y recuperación de cola. |
| RNF-14 | Usabilidad | Diseño adaptable desde 360 px; 4 de 5 tareas sin ayuda y mediana de localizar animal <=30 s en ensayo con usuario; pendiente visible y estados sin depender solo del color. | Prueba de tareas en móvil y escritorio. |
| RNF-15 | Tiempos y unidades | UTC/timestamptz, visualización por zona del predio, kg/cm/mV/°C superficial, edad derivada y valores desconocidos explícitos. | Pruebas de cambio horario, datos ausentes y conversiones. |
| RNF-16 | Observabilidad | Cada petición lleva ID correlacionable; registrar ruta plantilla, estado, duración y bytes; no body ni secretos; CPU/RAM/disco se recolectan fuera de tabla de negocio. | Comparar petición, log, métrica y auditoría por correlación. |
| RNF-17 | Privacidad y retención | Acceso mínimo, exportación autorizada y retención configurable aprobada antes del piloto; no activar purga histórica indiscriminada; logs de acceso administrativo incluidos. | Inventario de datos y prueba de permisos/retención. |
| RNF-18 | Mantenibilidad | Migraciones versionadas con respaldo, configuración externa y módulos separados por dominio; pruebas para permisos, geometrías, temporalidad y aprobación. | CI y revisión de migración en copia. |
| RNF-19 | Geometría | WGS84, cuatro vértices distintos más cierre, polígonos válidos; distancias en metros vía geography o proyección adecuada. | Casos borde, autointersección y puntos repetidos. |
| RNF-20 | Separación de ambientes | Simulación/piloto separados por base, credenciales y tópicos; datos sintéticos identificados; no se declara validación de campo desde simulación. | Revisión de despliegue y fuente de telemetría. |
| RNF-21 | Paginar y limitar | Listados con límite máximo propuesto de 100 filas/página, consultas con rango y orden estable; KPIs no descargan historia completa al navegador. | Ensayos con 30 días de telemetría. |
| RNF-22 | Conectividad de vistas globales | Mostrar hora de corte y última sincronización/disponibilidad; si hay instalaciones desconectadas no afirmar KPIs globales en tiempo real. | Prueba con fuente no disponible. |

## Trazabilidad con los datos

| Requisito | Entidades principales |
|---|---|
| RF-01 | users, login_sessions |
| RF-02 | platform_admins, mfa_factors, mfa_recovery_codes |
| RF-03 | security_challenges, login_sessions |
| RF-04 | login_sessions, account_tokens |
| RF-05 | users, owner_accounts, audit_log |
| RF-06 | users, farm_memberships, audit_log |
| RF-07 | owner_accounts, farm_memberships, animal_holdings, devices, assignments, farm_features |
| RF-08 | events, farms |
| RF-09 | audit_log |
| RF-10 | request_metrics |
| RF-11 | owner_accounts, farms |
| RF-12 | sectors |
| RF-13 | geofences, sectors |
| RF-14 | animals, animal_holdings |
| RF-15 | animal_measurements, animals |
| RF-16 | assignments, devices, animal_holdings |
| RF-17 | pasture_assignments, geofences |
| RF-18 | invitations, notifications |
| RF-19 | invitations, users, farm_memberships |
| RF-20 | farm_memberships, login_sessions |
| RF-21 | users, security_challenges, account_tokens |
| RF-22 | farms, sectors, geofences, gateways, telemetry |
| RF-23 | animals, animal_states, telemetry, health_events, health_schedules |
| RF-24 | change_requests, notifications |
| RF-25 | change_requests, animal_reports |
| RF-26 | change_requests, maintenance |
| RF-27 | change_requests, change_decisions, change_applications |
| RF-28 | animals, change_requests |
| RF-29 | trust_grants, farm_memberships |
| RF-30 | change_requests, change_decisions, animals, health_events |
| RF-31 | health_events, health_treatments |
| RF-32 | health_treatments |
| RF-33 | health_schedules, health_events, notifications |
| RF-34 | gateways, telemetry_receptions |
| RF-35 | telemetry, assignments, animal_states |
| RF-36 | telemetry_receptions, gateways |
| RF-37 | events, event_actions, rule_settings |
| RF-38 | telemetry, events, health_events |
| RF-39 | device_configs, devices |
| RF-40 | notifications, notification_attempts |
| RF-41 | audit_log |
| RF-42 | platform_admins, owner_accounts, farm_memberships |
| RF-43 | sag_movements, movement_animals, movement_status_events |
| RF-44 | devices, assignments, features, farm_features |

## Reglas heredadas que continúan vigentes

- Intervalo efectivo T = aplicado y confirmado por nodo. Posición vigente si edad <= 2T+30 s; comunicación ausente si recepción de paquete nuevo excede 3T+30 s.
- Dos posiciones GNSS válidas consecutivas fuera para alertar salida; el borde pertenece al interior y un dato inválido interrumpe consecutividad.
- Dato tardío modifica historia, no estado más reciente. Un reintento no actualiza artificialmente la frescura.
- Temperatura superficial y actividad apoyan revisión; no diagnostican enfermedad ni confirman abigeato.
- Reglas de campo y radio deben validarse; la propuesta de datos no demuestra autonomía, cobertura o precisión.

## Fuentes y límites

- Solicitud de los cuatro perfiles y confirmación expresa del cambio directo veterinario, 20 de octubre de 2026.
- `../REQUISITOS_INFORME_2.md`: reglas de operación y metas de 70 nodos, latencia, disponibilidad y recuperación.
- [OWASP: MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html): diferencia entre factores y autenticación reforzada.
- [OWASP: sesiones](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): controles de sesión y reautenticación.
- [PostgreSQL 16: restricciones](https://www.postgresql.org/docs/16/ddl-constraints.html): FK y exclusión; reglas entre tablas requieren mecanismos adicionales.
- No se declara cumplimiento legal ni se fijan períodos de conservación obligatorios. Se requiere una política de datos definida para el despliegue.
