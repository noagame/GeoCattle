from pathlib import Path
import json,html,re
P=Path(__file__).resolve().parent
T=json.loads((P/'catalogo_modelo.json').read_text())
RF=[]
def rf(code,title,criterion,uc,tables): RF.append((code,title,criterion,uc,tables))
rf('RF-01','Autenticar identidad única','Correo normalizado y contraseña válida; usuario suspendido no obtiene sesión. No se duplica una cuenta por trabajar en varios predios.','CU-01','users, login_sessions')
rf('RF-02','Exigir MFA al administrador','El panel global no emite sesión utilizable sin segundo factor verificado; recuperación no omite MFA permanentemente.','CU-01','platform_admins, mfa_factors, mfa_recovery_codes')
rf('RF-03','Verificar operaciones sensibles del dueño','Administrar colaboradores exige step-up reciente: lectura de lista en ventana de 10 min y desafío de un solo uso ligado al contenido de cada alta, cambio o baja. Cambiar correo, clave o factor exige reautenticación.','CU-13, CU-07','security_challenges, login_sessions')
rf('RF-04','Cerrar y recuperar sesiones','Cerrar sesión revoca token; cambio de contraseña o suspensión revoca todas las sesiones; recuperación usa token de un solo uso y vencimiento.','CU-02','login_sessions, account_tokens')
rf('RF-05','Administrar clientes','Administrador crea, consulta, modifica y desactiva dueños/cuentas; suspensión no elimina animales ni auditoría.','CU-03','users, owner_accounts, audit_log')
rf('RF-06','Administrar colaboradores desde plataforma','Administrador administra trabajadores y veterinarios existentes, conserva creador/contexto y no se convierte en el usuario mediante su contraseña.','CU-04','users, farm_memberships, audit_log')
rf('RF-07','Mostrar KPIs globales y por dueño','Reportar usuarios globales únicos, animales con permanencia activa, predios/sectores activos, collares instalados y módulos de software habilitados; filtrar por cuenta sin duplicar personas por membresías.','CU-05','owner_accounts, farm_memberships, animal_holdings, devices, assignments, farm_features')
rf('RF-08','Contar alertas diarias','Agrupar alertas por fecha de apertura en zona del predio, con filtros de dueño/predio/período; un reintento de aviso no incrementa alertas.','CU-05','events, farms')
rf('RF-09','Consultar auditoría','Administrador filtra auditoría global y predial por actor, fecha, entidad y acción; la lectura de auditoría queda registrada; ningún perfil edita sus filas.','CU-06','audit_log')
rf('RF-10','Inspeccionar consumo y peticiones','Ver volumen de peticiones, errores, p95 de duración y bytes por período/cuenta, más métricas de CPU/RAM/disco del sistema de observabilidad; no registrar cuerpos ni secretos.','CU-06','request_metrics')
rf('RF-11','Administrar predios propios','Dueño crea uno o varios predios hasta cupo configurado, consulta, modifica y desactiva sin borrar historia. Dos altas concurrentes no exceden cupo.','CU-08','owner_accounts, farms')
rf('RF-12','Administrar sectores','Crear, consultar, modificar uso/nombre y desactivar sectores de predios propios; uso distingue pastoreo, disponible, siembra, restringido y otro.','CU-09','sectors')
rf('RF-13','Editar puntos de geocerca','Crear/mover/agregar/quitar puntos y previsualizar; guardar exige al menos cuatro vértices distintos, cierre automático y polígono simple válido. Cada cambio crea versión.','CU-10','geofences, sectors')
rf('RF-14','Registrar bovinos','Dueño registra DIIO único como texto, especie bovina, sexo, raza/color opcionales y fecha de nacimiento conocida o estimada; un duplicado se rechaza.','CU-11','animals, animal_holdings')
rf('RF-15','Conservar mediciones','Peso en kg y altura en cm con fecha y autor; no sobrescribir medidas históricas. Edad calculada desde nacimiento; fecha desconocida se muestra desconocida.','CU-11, CU-22','animal_measurements, animals')
rf('RF-16','Asignar collar al bovino','Un collar y un animal tienen como máximo una asignación simultánea, mismo predio y dentro de permanencia; reasignar conserva historia.','CU-12','assignments, devices, animal_holdings')
rf('RF-17','Asignar pastoreo','Una geocerca por animal en cada instante, varios animales por geocerca; vigencia contenida en permanencia y versión de geocerca.','CU-12','pasture_assignments, geofences')
rf('RF-18','Invitar trabajador o veterinario','Dueño elige predio, correo y rol; se crea invitación con token hash, expiración 48 h propuesta y notificación. No enviar contraseña inicial reutilizable.','CU-13','invitations, notifications')
rf('RF-19','Aceptar enrolamiento','Invitado verifica correo, acepta invitación vigente y define credencial o usa cuenta existente del mismo correo; se crea membresía una sola vez.','CU-14','invitations, users, farm_memberships')
rf('RF-20','Administrar acceso de colaboradores','Dueño consulta/modifica/cierra membresías solo en sus predios con verificación; retirar acceso no borra la cuenta si participa en otro predio.','CU-13','farm_memberships, login_sessions')
rf('RF-21','Administrar perfil propio','Cada usuario consulta y cambia nombre/teléfono; correo requiere verificación; no modifica rol, predio, confianza ni identidad de otro. Eliminar perfil implica solicitar cierre, no borrar auditoría.','CU-07','users, security_challenges, account_tokens')
rf('RF-22','Consultar mapa autorizado','Dueño, trabajador y veterinario ven predio, sectores, geocercas, animales y gateways de su alcance; cada lectura muestra calidad y antigüedad.','CU-15','farms, sectors, geofences, gateways, telemetry')
rf('RF-23','Consultar ficha completa','Mostrar DIIO/collar, descripción, estado vital y técnico separados, temperatura superficial con hora, últimas medidas, historia sanitaria y próximas atenciones; valores ausentes no se muestran como cero.','CU-16','animals, animal_states, telemetry, health_events, health_schedules')
rf('RF-24','Proponer registro sanitario por trabajador','Vacuna/antibiótico administrado se guarda como solicitud pendiente; se notifica al dueño y la ficha efectiva no cambia antes de aprobación. No equivale a prescripción.','CU-17','change_requests, notifications')
rf('RF-25','Proponer estado o reporte','Trabajador propone cambio de estado o reporte del animal con motivo; pendiente se diferencia de efectivo.','CU-18','change_requests, animal_reports')
rf('RF-26','Reportar reemplazo de batería','Trabajador identifica módulo, batería/observación y hora; aprobación afecta el registro confirmado, nunca inventa mV de sensor.','CU-19','change_requests, maintenance')
rf('RF-27','Aprobar o rechazar cambios','Dueño revisa contenido/autor/fecha y versión base; aprobar aplica exactamente una vez en transacción; rechazar exige motivo y no cambia el registro efectivo.','CU-20','change_requests, change_decisions, change_applications')
rf('RF-28','Detectar conflictos de aprobación','Si cambió la versión base, responder conflicto y conservar solicitud pendiente para reformulación/rechazo; nunca sobrescribir silenciosamente datos más nuevos.','CU-20','animals, change_requests')
rf('RF-29','Configurar confianza granular','Dueño concede/revoca por trabajador, predio y acción permitida. Se valida al aplicar, registra concesión utilizada y no autoriza gestión de cuentas ni geocercas.','CU-21','trust_grants, farm_memberships')
rf('RF-30','Aplicar cambios directos veterinarios','Veterinario vigente edita ficha técnica y registra/corrige/anula salud directamente, con solicitud y decisión directa auditadas, sin aprobación del dueño.','CU-22, CU-23','change_requests, change_decisions, animals, health_events')
rf('RF-31','Preservar historia sanitaria','Corrección o baja lógica agrega sucesor al evento original; no permite cambiar DIIO, predio ni permisos desde una ficha. Los originales siguen consultables.','CU-23','health_events, health_treatments')
rf('RF-32','Detallar tratamientos','Registrar producto, dosis/unidad, vía, hora, lote opcional y resguardo informado; varios productos por evento. Datos no conocidos se distinguen explícitamente.','CU-17, CU-23','health_treatments')
rf('RF-33','Planificar próximas atenciones','Dueño/veterinario registra vacuna, control o antibiótico planificado con fecha, reemplaza/cancela por sucesor y vincula administración real al completar. Recordatorio no certifica administración.','CU-24','health_schedules, health_events, notifications')
rf('RF-34','Gestionar gateways','Dueño/admin registra gateway, ubicación y estado; mapa lo diferencia de collar; contador y última recepción no implican cobertura comprobada.','CU-25','gateways, telemetry_receptions')
rf('RF-35','Ingerir telemetría idempotente','Servicio autenticado valida y deduplica por dispositivo/sesión/secuencia; lectura atrasada conserva asignación de captura y no reemplaza estado más reciente.','CU-26','telemetry, assignments, animal_states')
rf('RF-36','Conservar recepción multiantena','Una lectura recibida por varias antenas permanece una sola lectura con varias recepciones RSSI/SNR.','CU-26','telemetry_receptions, gateways')
rf('RF-37','Evaluar y atender alertas','Preservar reglas actuales: dos posiciones exteriores válidas, borde interior, comunicación independiente y estado desconocido ante datos insuficientes; atención no resuelve condición técnica.','CU-27','events, event_actions, rule_settings')
rf('RF-38','Consultar historias y filtros','Mapa/ficha permite filtros por predio/sector/animal y períodos 24 h, 7 d, 30 d o rango; paginación, orden estable y vacío explícito.','CU-16','telemetry, events, health_events')
rf('RF-39','Confirmar configuración IoT','Dueño solicita intervalo y seguimiento solicitado/enviado/aplicado/fallido; solo versión confirmada cambia intervalo efectivo.','CU-28','device_configs, devices')
rf('RF-40','Notificar sin bloquear operación','Aviso interno persistido con operación, envío externo con reintentos y resultados; fallo externo no borra la solicitud ni la alerta.','CU-17, CU-20, CU-24, CU-28','notifications, notification_attempts')
rf('RF-41','Auditar cambios de privilegios y negocio','Registrar actor, contexto, acción, fecha y cambios pertinentes; jamás contraseña/token/semilla MFA. Administración global también se audita.','CU-03, CU-04, CU-06, CU-21','audit_log')
rf('RF-42','Separar consulta global y predial','Administrador global ve todas las cuentas mediante panel global; dueño solo su cuenta; colaborador solo predios con membresía vigente. Cada API valida alcance.','CU-01, CU-15','platform_admins, owner_accounts, farm_memberships')
rf('RF-43','Gestionar FMA como extensión','Conservar cabecera/detalle/historia de movimiento; borrador editable, confirmado congelado; confirmar externamente exige evidencia y ejecución verificada actualiza permanencias.','CU-29','sag_movements, movement_animals, movement_status_events')
rf('RF-44','Distinguir módulos físicos y funcionales','Panel nombra collares instalados, collares inventariados y módulos de software habilitados por separado; no agrega denominadores diferentes.','CU-05','devices, assignments, features, farm_features')

CU=[
('CU-01','Iniciar sesión y seleccionar contexto','Todos; MFA obligatorio para administrador','Cuenta activa; administrador con factor enrolado.','Introducir correo/contraseña; verificar segundo factor si corresponde; emitir sesión; seleccionar panel global o contexto autorizado.','Credencial incorrecta, factor vencido o usuario suspendido: negar; limitar intentos.','Sesión emitida con nivel de autenticación y alcance explícitos.'),
('CU-02','Cerrar sesión o recuperar acceso','Todos','Cuenta o sesión identificable sin revelar existencia a terceros.','Revocar sesión; para recuperación emitir enlace de un solo uso, verificar identidad y cambiar clave; administrador conserva requisito MFA.','Token vencido/reutilizado: no cambiar clave; no omitir MFA mediante recuperación.','Tokens anteriores revocados y acción auditada.'),
('CU-03','Administrar dueños/clientes','Administrador','Sesión global con MFA vigente.','Buscar cliente; crear cuenta y cupo o modificar/suspender; confirmar operación sensible; registrar auditoría.','Correo repetido o cuenta con historia: reutilizar identidad o baja lógica; no borrar referencias.','Cliente actualizado sin pérdida de sus registros.'),
('CU-04','Administrar colaboradores desde plataforma','Administrador','Colaborador incorporado por dueño y contexto cliente identificado.','Consultar usuario y membresías; corregir datos o suspender acceso; registrar motivo y notificar al dueño.','No reasignar historia a otro usuario ni acceder usando su contraseña.','Cambio administrativo trazable y sesiones incompatibles revocadas.'),
('CU-05','Consultar KPIs','Administrador','Sesión global con MFA.','Elegir período y dueño opcional; consultar inventario, usuarios, módulos y alertas; mostrar definiciones, corte temporal y zona.','Sin datos: cero o sin medición según métrica; evitar sumas de personas duplicadas.','Panel coherente con filtros y unidades.'),
('CU-06','Auditar actividad y consumo','Administrador','Permiso global y MFA.','Filtrar auditoría/peticiones; inspeccionar actor, estado, latencia/bytes; consultar métricas de infraestructura en observabilidad.','Datos sensibles se enmascaran; consultas paginadas; acceso al auditor se audita.','Lectura registrada sin editar evidencia.'),
('CU-07','Administrar perfil propio','Todos','Sesión propia vigente.','Consultar/editar nombre/teléfono; verificar cambios sensibles; solicitar cierre de cuenta cuando proceda.','No cambiar rol, cupo ni confianza; dueño con predios requiere transferencia/cierre administrativo previo.','Perfil actualizado o solicitud de cierre registrada.'),
('CU-08','Administrar predios','Dueño; administrador','Cuenta activa y cupo disponible para alta.','Registrar nombre/RUP y ubicación; consultar/editar; desactivar tras resolver asociaciones activas.','Cupo excedido incluso bajo concurrencia: rechazar alta; baja no borra historia.','Predio pertenece a una cuenta definida.'),
('CU-09','Configurar sectores','Dueño; administrador','Predio autorizado.','Definir nombre y uso; editar/desactivar sector; revisar geocercas/asignaciones antes de retiro.','Nombre duplicado o relaciones activas incompatibles: pedir resolución explícita.','Sector y uso guardados con auditoría.'),
('CU-10','Crear o editar geocerca','Dueño; administrador','Sector autorizado y versión esperada.','Dibujar cuatro o más vértices distintos; mover/agregar/quitar; validar; previsualizar impacto; cerrar asignaciones afectadas y guardar nueva versión.','Autointersección, menos de cuatro vértices o conflicto de versión: no reemplazar la activa.','Nueva geometría versionada, historia preservada.'),
('CU-11','Registrar y mantener bovino','Dueño; administrador','Predio autorizado; DIIO disponible.','Registrar identidad/descripción, nacimiento y mediciones; abrir permanencia; consultar y modificar con versión.','DIIO duplicado o fecha inválida: rechazar; retiro cierra asociaciones incompatibles.','Animal y permanencia consistentes; medidas históricas.'),
('CU-12','Asignar collar o pastoreo','Dueño; administrador','Animal presente; collar o geocerca del mismo predio.','Elegir intervalo; cerrar asignación anterior y abrir nueva en una transacción.','Solapamiento, otro predio o fuera de vigencia: rechazar sin cambios parciales.','Máximo un collar y una geocerca por animal en cada instante.'),
('CU-13','Invitar y administrar colaboradores','Dueño; administrador','Contexto autorizado y doble verificación exigida.','Verificar acceso; invitar correo/rol/predio o consultar/editar/revocar membresía; confirmar cada escritura con reto ligado a operación.','Invitación vencida se reemite; cuenta de otro predio conserva su identidad y acceso ajeno.','Invitación o acceso actualizado y auditado.'),
('CU-14','Enrolarse por invitación','Trabajador; veterinario','Invitación vigente dirigida a correo verificable.','Abrir enlace; verificar correo; crear credencial o autenticar cuenta existente; aceptar y abrir membresía.','Token reutilizado/revocado o correo diferente: no crear acceso.','Un usuario y una membresía, sin duplicación por reintento.'),
('CU-15','Consultar mapa del predio','Dueño; trabajador; veterinario; administrador','Contexto autorizado.','Seleccionar predio/sector; ver límites, animales, gateways y calidad/edad de cada dato; abrir ficha.','Sin Internet del mapa externo: conservar geometrías locales; sin lectura vigente: marcar desconocido.','Consulta de datos exclusivamente autorizados.'),
('CU-16','Consultar ficha e historial','Dueño; trabajador; veterinario; administrador','Acceso al animal en contexto predial.','Ver DIIO, collar, estado, temperatura superficial, medidas, salud y agenda; filtrar/paginar historia.','Sin sensor o nacimiento conocido: mostrar ausencia; animal trasladado no concede historia futura del destino.','Vista consistente entre mapa, ficha e historial.'),
('CU-17','Registrar vacuna o antibiótico por trabajador','Trabajador','Membresía vigente y animal del predio.','Introducir hecho observado, producto/dosis/hora y evidencia; validar; guardar solicitud; notificar dueño; si hay confianza vigente, aplicar directamente con evidencia.','Sin confianza queda pendiente; reporte de administración no genera prescripción ni diagnóstico automático.','Solicitud preservada; ficha efectiva solo cambia tras decisión autorizada.'),
('CU-18','Solicitar estado o reporte del bovino','Trabajador','Membresía vigente y versión base conocida.','Elegir estado o redactar reporte; enviar; notificar; aplicar directo solo si existe confianza para esa acción.','Estado incompatible o versión obsoleta: conflicto; no sobrescribir.','Pendiente o aplicado distinguido visualmente.'),
('CU-19','Reportar cambio de batería','Trabajador; dueño','Collar identificado en predio autorizado.','Registrar batería, hora y resultado; trabajador solicita o usa confianza; dueño aplica directamente.','No actualizar telemetría de batería a partir de un reporte manual.','Mantenimiento efectivo o solicitud pendiente trazable.'),
('CU-20','Aprobar o rechazar solicitud','Dueño; administrador','Solicitud pendiente de predio autorizado.','Revisar antes/después y versión; aprobar o rechazar con motivo; al aprobar aplicar dato, decisión, aplicación, aviso y auditoría en una transacción.','Decisión previa: devolver resultado idempotente; versión cambiada: conflicto y solicitud pendiente.','Sin cambios parciales y una sola aplicación.'),
('CU-21','Conceder o revocar confianza','Dueño; administrador','Trabajador vigente y verificación sensible.','Elegir acción permitida y vigencia; conceder/revocar; registrar y notificar.','No habilitar gestión de usuarios, geocercas o prescripción; revocación se comprueba al aplicar.','Exención granular auditable; pendientes previos siguen revisión manual.'),
('CU-22','Modificar ficha técnica','Veterinario; dueño; administrador','Animal autorizado y versión base.','Editar descripción técnica y registrar nuevas mediciones; validar campos permitidos; aplicar directamente y auditar.','Veterinario no cambia DIIO, permanencia, collar ni estado vital mediante este formulario; conflicto conserva datos previos.','Ficha actualizada con medidas e historia de cambios.'),
('CU-23','Gestionar ficha sanitaria','Veterinario; dueño; administrador','Animal autorizado; usuario con permiso directo.','Registrar evento/tratamientos o consultar historia; corregir/anular creando sucesor; aplicar directamente con autoría.','Otro animal o evento ya sustituido: rechazar; jamás borrar el original.','CRUD funcional mediante alta, lectura, corrección y anulación histórica.'),
('CU-24','Planificar próxima atención','Veterinario; dueño; administrador','Animal autorizado.','Elegir tipo/fecha; registrar plan; reprogramar/cancelar por sucesor; recordar; completar vinculando administración real.','Recordatorio vencido no marca administración automáticamente.','Agenda vigente y hechos realizados separados.'),
('CU-25','Administrar gateways e inventario','Dueño; administrador','Predio autorizado.','Registrar EUI/serie y posición; actualizar estado del gateway/collar; visualizar en mapa.','EUI duplicado u objeto de otro predio: rechazar; retiro con asignación activa exige cierre.','Infraestructura identificable, sin prometer cobertura por inventario.'),
('CU-26','Recibir telemetría','Servicio de ingestión','Credencial técnica, codec y dispositivo registrados.','Validar/deduplicar; resolver asignación a captura; guardar lectura y recepciones; actualizar proyecciones solo si nueva; evaluar reglas.','Duplicado no rejuvenece estado; caída de BD conserva cola; lectura no asociada queda para revisión.','Una lectura por sesión/secuencia y contexto histórico correcto.'),
('CU-27','Generar y atender alerta','Servicio; dueño; trabajador; veterinario','Reglas habilitadas y contexto autorizado.','Evaluar lectura/temporizador; crear alerta única; encolar aviso; usuario reconoce/revisa/concluye atención.','Sensores insuficientes: desconocido; reconocer no demuestra regreso ni enfermedad.','Condición técnica y atención humana independientes.'),
('CU-28','Configurar collar y entregar avisos','Dueño; administrador; servicio','Dispositivo autorizado o notificación persistida.','Solicitar intervalo; enviar y esperar confirmación; procesar notificaciones con reintentos y registrar resultado.','Sin nodo/WAN: pendiente o fallo; no fingir aplicación ni lectura humana.','Configuración confirmada y entregas trazables.'),
('CU-29','Gestionar movimiento FMA (extensión)','Dueño; administrador','Módulo habilitado y datos oficiales verificables cuando corresponda.','Crear borrador y animales; confirmar/congelar; registrar evidencia externa; ejecutar traslado cerrando asignaciones y permanencia.','Sin folio/evidencia no declarar confirmación oficial; cancelación ejecutada requiere regularización.','Documento e historia preservados; sin integración SIPEC presumida.')]

intro='''# GeoCattle V3 — Análisis de usuarios y decisiones de alcance

Propuesta del 20 de octubre de 2026 para la aplicación a construir. Esta especificación sustituye las decisiones de roles de la propuesta V2; no modifica la aplicación ejecutable.

## Interpretación de los cuatro perfiles

| Perfil | Alcance | Responsabilidad | Límites operativos |
|---|---|---|---|
| Administrador | Plataforma completa | Clientes, recursos, configuración, KPIs, auditoría y soporte | MFA obligatorio; acciones globales auditadas; acceso de aplicación no significa conocer contraseñas ni borrar evidencia. |
| Dueño | Su cuenta cliente y todos sus predios | Predios, sectores, animales, colaboradores, confianza y aprobación | No consulta cuentas ajenas; acciones sobre colaboradores requieren doble verificación. |
| Trabajador | Predios con membresía vigente | Monitoreo y reportes operativos/sanitarios | Por defecto propone cambios; solo acciones expresamente autorizadas pueden aplicarse sin revisión. |
| Veterinario | Predios con membresía vigente | Ficha técnica, salud y agenda sanitaria | Cambios directos confirmados por el usuario; no administra predios, usuarios, collares o privilegios. |

## Decisiones adoptadas

1. **Administrador global distinto de dueño.** No existe un único rol que mezcle soporte SaaS y propiedad predial. Puede haber varios administradores, cada uno con identidad propia.
2. **Identidad única, varias participaciones.** Un trabajador o veterinario puede pertenecer a varios predios, incluso de dueños diferentes. Cada petición usa un contexto autorizado; no existe cuenta compartida por equipo.
3. **Una cuenta cliente y varios predios.** El dueño principal administra `owner_accounts`; un cupo entero limita altas. No se agregan planes de pago ni facturación no solicitados. La copropiedad queda fuera de esta versión.
4. **MFA no es aprobación de negocio.** MFA acredita autenticación; step-up vuelve a verificar una operación sensible; aprobación decide si un cambio propuesto entra en el registro efectivo. Dos confirmaciones de interfaz no constituyen MFA.
5. **Doble verificación del dueño.** Se propone contraseña más TOTP o WebAuthn para administración de colaboradores. Lectura/listado requiere step-up de hasta 10 min; cada escritura consume un reto de hasta 5 min ligado a acción, recurso y contenido. Son parámetros de diseño ajustables. El alta inicial de MFA exige sesión autenticada y un desafío del factor antes de activarlo.
6. **Veterinario con cambios directos.** Confirmado expresamente en esta conversación. Se conserva autoría y evidencia de aplicación directa; no se añade una aprobación del dueño a este perfil.
7. **Trabajador propone hechos, no prescribe.** Puede reportar vacuna/antibiótico administrado, estado, reporte y batería. La confianza elimina revisión solo para esas acciones; no concede nuevas funciones.
8. **Pendiente significa persistido, pero no efectivo.** La solicitud sí se guarda en la base; la ficha oficial del sistema se modifica al aprobar. Si se reportó una administración real, mostrar advertencia provisional de resguardo aun pendiente o rechazada; rechazo administrativo no prueba que el hecho no ocurrió.
9. **CRUD sanitario con historia.** Actualizar crea corrección; eliminar crea anulación. Un registro clínico histórico no se elimina físicamente desde la aplicación. Esta decisión conserva la trazabilidad solicitada previamente.
10. **Cuatro vértices distintos más cierre automático.** Una geocerca tiene al menos cuatro esquinas distintas; el punto de cierre repetido no cuenta como esquina. Se permiten más puntos y se rechazan autointersecciones.
11. **Edad y medidas.** Edad derivada de nacimiento; peso/altura fechados. Se evita una edad almacenada que quede obsoleta y medidas sin fecha.
12. **Módulo sin ambigüedad.** Collar físico, gateway y módulo funcional de software tienen entidades y KPIs diferentes. No se supone un sensor de pulso ni medición de altura automática.
13. **Eliminar acceso no borra identidad ajena.** Dueño revoca membresía en su predio; solo administración global suspende una identidad completa. Retención/anónimización se definirá aparte, sin romper autoría histórica.
14. **Perfil personal limitado.** CRUD propio no permite cambiar rol, confianza, cupos o membresías. El dueño con activos debe regularizar la cuenta antes del cierre global.
15. **Operación local preservada.** LAN, servidor e ingestión pueden funcionar sin Internet; correo/mapas externos y avisos dependen de su conectividad. El panel global solo ve los despliegues conectados al repositorio de la instancia; no se inventa una sincronización multiinstancia.

## Matriz de autorización

Leyenda: D directo, P propuesta, T directo solo con confianza vigente para esa acción, — sin acceso. Todas las celdas operan dentro del alcance del perfil.

| Operación | Administrador | Dueño | Trabajador | Veterinario |
|---|---|---|---|---|
| Panel global, clientes y consumo | D | — | — | — |
| Administrar predios/sectores/geocercas | D | D | — | — |
| Gestionar colaboradores | D | D + step-up | — | — |
| Conceder confianza/revisar solicitudes | D | D + step-up para confianza | — | — |
| Consultar mapa y ficha | D | D | D | D |
| Registrar animal/DIIO/permanencia | D | D | — | — |
| Cambiar collar/pastoreo o configurar nodo | D | D | — | — |
| Editar descripción técnica/medidas | D | D | — | D |
| Cambiar estado vital / reportar animal | D | D | P / T | — |
| Registrar hecho sanitario administrado | D | D | P / T | D |
| Corregir/anular ficha sanitaria | D | D | P / T dentro del registro sanitario permitido | D |
| Planificar próxima atención | D | D | — | D |
| Reportar batería | D | D | P / T | — |
| Atender alertas | D | D | D | D |
| Consultar auditoría predial | D | D | — | — |
| Modificar datos personales propios | D | D | D | D |

El administrador puede realizar operaciones de soporte en cualquier cuenta con motivo y auditoría; no se permite suplantación silenciosa. La interfaz global y la predial presentan explícitamente el contexto.

## Prioridad para un equipo de dos personas

- **P0, núcleo:** identidad, MFA, clientes/predios/membresías, bovinos, geometría, mapa/telemetría y controles de acceso.
- **P1, flujo solicitado:** aprobaciones/confianza, fichas y agenda sanitaria, baterías, gateways, KPIs y auditoría.
- **P2, extensión anterior:** FMA e integración documental. No se condiciona el MVP a implementar un intercambio oficial con SIPEC.

Las 48 tablas representan el alcance completo y controles de seguridad/operación, no 48 pantallas ni 48 microservicios. Se recomienda un backend modular y una sola base para esta etapa.
'''
(P/'00_ANALISIS_Y_ALCANCE.md').write_text(intro)

use=['# GeoCattle V3 — Casos de uso','', 'Cada caso incluye autorización, flujo y resultado verificable. El servicio de ingestión y el de avisos son actores técnicos; no son perfiles humanos adicionales. El propietario o administrador actúa según el alcance descrito en `00_ANALISIS_Y_ALCANCE.md`.', '', '| ID | Caso | Actor principal |','|---|---|---|']
for x in CU: use.append(f'| {x[0]} | {x[1]} | {x[2]} |')
for code,name,actors,pre,flow,exc,post in CU:
    req=[r[0] for r in RF if code in r[3]]
    use += ['',f'## {code} — {name}','',f'- Actor: {actors}.',f'- Precondición: {pre}',f'- Disparador y flujo principal: {flow}',f'- Alternativas/excepciones: {exc}',f'- Postcondición: {post}',f'- Requisitos relacionados: {", ".join(req)}.']
use+=['','## Flujo detallado de aprobación','',
'1. La API autentica al actor y resuelve cuenta/predio sin confiar en un `farm_id` enviado sin validar.',
'2. Valida permiso, objeto, campos y versión; crea solicitud inmutable con clave de idempotencia y payload validado.',
'3. Trabajador sin confianza: guarda solicitud + aviso + auditoría; no crea registro efectivo. Se responde `pending`.',
'4. Dueño/admin, veterinario en su alcance, o trabajador con confianza vigente: aplica camino directo dentro de la misma transacción.',
'5. Revisión manual: bloquear solicitud y objeto; comprobar estado, contexto, versión y vigencia del autor; rechazar exige motivo.',
'6. Aprobación: insertar decisión, modificar datos efectivos o agregar evento, registrar aplicación, auditoría y aviso; confirmar todo junto. Un fallo revierte toda la transacción.',
'7. Repetición devuelve la decisión y aplicación ya existentes; payload distinto con la misma clave de idempotencia se rechaza.',
'8. Si hay conflicto de versión, no se escribe decisión aceptada: la solicitud queda pendiente para reformular o rechazar. La nueva propuesta referencia la anterior en el payload validado para conservar el motivo.',
'9. La confianza se comprueba dentro de la transacción y se bloquea la concesión contra revocación concurrente. No aplica retroactivamente a solicitudes antiguas.',
'10. Aprobar un cambio no ejecuta correos antes de commit; la cola persistida se entrega posteriormente.']
(P/'01_CASOS_DE_USO.md').write_text('\n'.join(use)+'\n')

nfr=[
('RNF-01','Aislamiento','100% de operaciones con IDs ajenos deben responder denegación sin filtrar datos; matriz de prueba con dos dueños y un colaborador compartido.','API y pruebas de autorización negativas.'),
('RNF-02','MFA y step-up','Administradores sin MFA no acceden al panel; retos de escritura de un uso, ligados a operación, con 5 min de vigencia; lectura sensible 10 min propuesta.','Pruebas de replay, caducidad y cambio de payload.'),
('RNF-03','Credenciales y transporte','TLS en despliegue; contraseñas con Argon2id y parámetros medidos; secretos MFA cifrados con clave fuera de la BD; tokens almacenados con hash.','Revisión de configuración, datos y respuestas.'),
('RNF-04','Sesiones','Cookie HttpOnly/Secure/SameSite; CSRF en escrituras; propuesta de 30 min inactiva y 12 h absoluta, ajustable; suspensión revoca.','Pruebas de sesión/CSRF y relojes controlados.'),
('RNF-05','Resistencia a abuso','5 fallos consecutivos por cuenta/contexto disparan espera progresiva y límites por IP, sin bloqueo permanente; recuperación no revela existencia de cuenta.','Pruebas de fuerza bruta y enumeración.'),
('RNF-06','Atomicidad e idempotencia','Una decisión y una aplicación por solicitud; ningún cambio efectivo sobrevive si falla auditoría/cola transaccional; un uplink duplicado no crea lectura.','Pruebas con fallos inyectados y concurrencia.'),
('RNF-07','Integridad histórica','Exclusión de intervalos, FK de predio y triggers de inmutabilidad rechazan entradas inválidas; usuario runtime no es propietario del esquema ni puede desactivar triggers.','Pruebas SQL y revisión de grants.'),
('RNF-08','Rendimiento de consulta','Meta heredada: p95 GET estado <=1 s y error <1%, con 70 nodos, 5 clientes concurrentes y 10 min de carga; no es medición conseguida.','Ensayo de carga reproducible.'),
('RNF-09','Procesamiento','Meta heredada: p95 recepción a evento <=2 s en >=100 eventos controlados; detección del cruce depende de frecuencia, GNSS y radio.','Medición de marcas del servidor.'),
('RNF-10','Capacidad','Escenario inicial 70 collares a 300 s: 20.160 lecturas/día; dimensionar índices, recepciones y backups con bytes reales.','Carga con datos realistas, no aproximación como capacidad certificada.'),
('RNF-11','Disponibilidad local','Meta heredada >=99% en 7 días con monitor cada minuto, incluyendo mantenimiento, condicionada a energía/LAN/servidor/radio.','Registro continuo del piloto.'),
('RNF-12','Recuperación','Meta heredada RPO <=24 h y RTO <=2 h; backup diario y restauración en base vacía antes del piloto.','Ensayo documentado de restauración.'),
('RNF-13','Sin Internet','Conservar ingestión, ficha, mapa vectorial local y alertas mientras infraestructura local esté disponible; avisos externos quedan pendientes.','Corte WAN controlado y recuperación de cola.'),
('RNF-14','Usabilidad','Diseño adaptable desde 360 px; 4 de 5 tareas sin ayuda y mediana de localizar animal <=30 s en ensayo con usuario; pendiente visible y estados sin depender solo del color.','Prueba de tareas en móvil y escritorio.'),
('RNF-15','Tiempos y unidades','UTC/timestamptz, visualización por zona del predio, kg/cm/mV/°C superficial, edad derivada y valores desconocidos explícitos.','Pruebas de cambio horario, datos ausentes y conversiones.'),
('RNF-16','Observabilidad','Cada petición lleva ID correlacionable; registrar ruta plantilla, estado, duración y bytes; no body ni secretos; CPU/RAM/disco se recolectan fuera de tabla de negocio.','Comparar petición, log, métrica y auditoría por correlación.'),
('RNF-17','Privacidad y retención','Acceso mínimo, exportación autorizada y retención configurable aprobada antes del piloto; no activar purga histórica indiscriminada; logs de acceso administrativo incluidos.','Inventario de datos y prueba de permisos/retención.'),
('RNF-18','Mantenibilidad','Migraciones versionadas con respaldo, configuración externa y módulos separados por dominio; pruebas para permisos, geometrías, temporalidad y aprobación.','CI y revisión de migración en copia.'),
('RNF-19','Geometría','WGS84, cuatro vértices distintos más cierre, polígonos válidos; distancias en metros vía geography o proyección adecuada.','Casos borde, autointersección y puntos repetidos.'),
('RNF-20','Separación de ambientes','Simulación/piloto separados por base, credenciales y tópicos; datos sintéticos identificados; no se declara validación de campo desde simulación.','Revisión de despliegue y fuente de telemetría.'),
('RNF-21','Paginar y limitar','Listados con límite máximo propuesto de 100 filas/página, consultas con rango y orden estable; KPIs no descargan historia completa al navegador.','Ensayos con 30 días de telemetría.'),
('RNF-22','Conectividad de vistas globales','Mostrar hora de corte y última sincronización/disponibilidad; si hay instalaciones desconectadas no afirmar KPIs globales en tiempo real.','Prueba con fuente no disponible.')]
req=['# GeoCattle V3 — Requerimientos','', 'Requisitos propuestos a partir de los cuatro perfiles y del alcance previo. Las metas cuantitativas son criterios de aceptación, no resultados alcanzados. RF-43 es extensión P2; los demás cubren núcleo y flujo solicitado.', '', '## Funcionales','', '| ID | Requisito | Criterio de aceptación | Casos |','|---|---|---|---|']
for a,b,c_,d,e in RF: req.append(f'| {a} | {b} | {c_} | {d} |')
req+=['','## No funcionales','', '| ID | Atributo | Criterio verificable | Evidencia |','|---|---|---|---|']
for row in nfr: req.append('| '+' | '.join(row)+' |')
req+=['','## Trazabilidad con los datos','', '| Requisito | Entidades principales |','|---|---|']
for a,b,c_,d,e in RF: req.append(f'| {a} | {e} |')
req+=['','## Reglas heredadas que continúan vigentes','',
'- Intervalo efectivo T = aplicado y confirmado por nodo. Posición vigente si edad <= 2T+30 s; comunicación ausente si recepción de paquete nuevo excede 3T+30 s.',
'- Dos posiciones GNSS válidas consecutivas fuera para alertar salida; el borde pertenece al interior y un dato inválido interrumpe consecutividad.',
'- Dato tardío modifica historia, no estado más reciente. Un reintento no actualiza artificialmente la frescura.',
'- Temperatura superficial y actividad apoyan revisión; no diagnostican enfermedad ni confirman abigeato.',
'- Reglas de campo y radio deben validarse; la propuesta de datos no demuestra autonomía, cobertura o precisión.',
'', '## Fuentes y límites','',
'- Solicitud de los cuatro perfiles y confirmación expresa del cambio directo veterinario, 20 de octubre de 2026.',
'- `../REQUISITOS_INFORME_2.md`: reglas de operación y metas de 70 nodos, latencia, disponibilidad y recuperación.',
'- [OWASP: MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html): diferencia entre factores y autenticación reforzada.',
'- [OWASP: sesiones](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): controles de sesión y reautenticación.',
'- [PostgreSQL 16: restricciones](https://www.postgresql.org/docs/16/ddl-constraints.html): FK y exclusión; reglas entre tablas requieren mecanismos adicionales.',
'- No se declara cumplimiento legal ni se fijan períodos de conservación obligatorios. Se requiere una política de datos definida para el despliegue.']
(P/'02_REQUERIMIENTOS.md').write_text('\n'.join(req)+'\n')

concept='''erDiagram
    USUARIO ||--o| ADMINISTRADOR : tiene_acceso_global
    USUARIO ||--o| CUENTA_DUENO : administra
    CUENTA_DUENO ||--o{ PREDIO : posee
    USUARIO ||--o{ MEMBRESIA : participa
    PREDIO ||--o{ MEMBRESIA : concede_acceso
    MEMBRESIA ||--o{ CONFIANZA : recibe_exencion
    PREDIO ||--o{ SECTOR : organiza
    SECTOR ||--o{ GEOCERCA_VERSION : delimita
    ANIMAL ||--o{ PERMANENCIA : conserva
    PREDIO ||--o{ PERMANENCIA : alberga
    PERMANENCIA ||--o{ ASIGNACION_COLLAR : vincula
    COLLAR ||--o{ ASIGNACION_COLLAR : registra_historia
    PERMANENCIA ||--o{ ASIGNACION_PASTOREO : planifica
    GEOCERCA_VERSION ||--o{ ASIGNACION_PASTOREO : recibe
    PREDIO ||--o{ GATEWAY : instala
    COLLAR ||--o{ LECTURA : genera
    LECTURA ||--o{ RECEPCION : tiene
    GATEWAY ||--o{ RECEPCION : recibe
    USUARIO ||--o{ SOLICITUD_CAMBIO : propone
    PREDIO ||--o{ SOLICITUD_CAMBIO : delimita
    SOLICITUD_CAMBIO ||--o| DECISION : recibe
    DECISION ||--o| APLICACION : autoriza
    PERMANENCIA ||--o{ EVENTO_SANITARIO : conserva
    EVENTO_SANITARIO ||--o{ TRATAMIENTO : detalla
    PERMANENCIA ||--o{ AGENDA_SANITARIA : planifica
    COLLAR ||--o{ MANTENIMIENTO : conserva
    LECTURA o|--o{ ALERTA : fundamenta
    ALERTA ||--o{ ACCION_ALERTA : recibe
    USUARIO ||--o{ AUDITORIA : ejecuta
    CUENTA_DUENO o|--o{ AUDITORIA : contextualiza
    PREDIO ||--o{ NOTIFICACION : genera
    NOTIFICACION ||--o{ INTENTO_ENVIO : entrega
'''
(P/'MODELO_CONCEPTUAL_V3.mmd').write_text(concept)
cd=['# GeoCattle V3 — Modelo conceptual entidad-relación','', 'Este nivel describe conceptos y cardinalidades de negocio, sin UUID, tipos PostgreSQL, PK ni índices. El diagrama lógico separado muestra su transformación a tablas.', '', '```mermaid',concept.rstrip(),'```','',
'## Cardinalidades y participación','',
'| Relación | Cardinalidad | Interpretación |','|---|---|---|',
'| Usuario – cuenta de dueño | 1 : 0..1 | Cada cuenta tiene un dueño principal; un usuario puede no ser dueño. |',
'| Cuenta – predio | 1 : 0..N | Cuenta recién creada puede no tener predios; cada predio tiene una cuenta. |',
'| Usuario – predio | N : M mediante membresía | Trabajadores/veterinarios pueden colaborar en varios predios; dueño accede mediante su cuenta. |',
'| Predio – sector – geocerca versión | 1:N y 1:N | Sector estable; geometría cambia mediante versiones temporales. |',
'| Animal – predio | N:M histórica mediante permanencia | A lo sumo una permanencia activa por animal. |',
'| Animal – collar | N:M histórica mediante asignación | En un instante, a lo sumo un collar por animal y un animal por collar. |',
'| Animal – geocerca | N:M histórica mediante pastoreo | Una geocerca vigente por animal; varios animales simultáneos por geocerca. |',
'| Collar – lectura | 1:0..N | Cada lectura proviene de un collar, aunque no tenga animal atribuido. |',
'| Lectura – gateway | N:M mediante recepción | Un uplink puede recibirse por varias antenas. |',
'| Solicitud – decisión – aplicación | 1:0..1 y 1:0..1 | Pendiente no tiene decisión; rechazada no tiene aplicación; aceptada/directa exige aplicación. |',
'| Permanencia – evento sanitario – tratamiento | 1:N y 1:N | Historia sanitaria contextualizada y varios productos posibles. |',
'| Agenda – evento sanitario | N:0..1 por entrada completada | Planificar no demuestra administrar; completar exige evento real del mismo animal. |',
'', 'El diagrama omite conceptos de soporte (retos, factores, proyecciones, métricas y configuración) para mantener el nivel conceptual. La extensión FMA conserva relación documento N:M animal mediante detalle, definida en el modelo lógico. Ninguna cardinalidad por sí sola demuestra autorización o ausencia de solapamientos.']
(P/'03_MODELO_CONCEPTUAL.md').write_text('\n'.join(cd)+'\n')

physical='''# GeoCattle V3 — Modelo físico y contrato de implementación

## Entrega y alcance real

`MODELO_FISICO_V3.sql` define 48 tablas, claves, índices, exclusiones, triggers, vistas KPI y catálogos iniciales en el esquema independiente `geocattle_v3`. Destino: PostgreSQL 16 con PostGIS 3.4 y btree_gist. No utiliza TimescaleDB. Se ejecuta una vez en una base vacía de revisión; aborta si el esquema existe. No es una migración sobre la base actual.

Las propuestas y decisiones se almacenan de forma estructurada. El payload JSON de una solicitud es un comando validado por esquema de API, no el reemplazo de tablas clínicas ni una instrucción SQL dinámica.

## Controles incluidos en SQL

- FK, obligatoriedad, dominios, unicidades y claves compuestas por predio.
- Exclusión de solapamientos para membresías, permanencias, collares y pastoreo.
- Cuatro vértices distintos más cierre, polígono válido sin huecos y versiones no superpuestas por sector.
- Contención de asignaciones en permanencia y versión de geocerca; cierre de permanencia exige cerrar asignaciones.
- Identidad de collar/animal y momento de captura coherentes en telemetría; deduplicación dispositivo/sesión/secuencia.
- Decisión única y aplicación única; aceptadas/directas requieren aplicación en la misma transacción mediante trigger diferido.
- Revisión por dueño/admin; aplicación directa veterinaria en acciones permitidas; trabajador directo con concesión vigente identificada.
- Eventos clínicos y agenda con sucesor único y referencias del mismo animal/permanencia.
- Registros históricos protegidos contra UPDATE/DELETE; métricas, auditoría y acciones también inmutables.
- Cupo de predios con bloqueo de cuenta para altas concurrentes.
- Vistas de solicitudes pendientes, salud/agenda efectivas, collares instalados, inventario por dueño y alertas por día.
- Sin permisos públicos sobre esquema, tablas y funciones. La instalación no crea usuarios de aplicación ni configura credenciales.

## Controles que debe implementar el backend

El SQL no es una aplicación terminada. No configura OTP/WebAuthn, correo, cookies, HTTPS, verificación de correo, recuperación, rutas ni gráficas. La base no puede demostrar que un UUID de actor fue autenticado: debe obtenerse de la sesión validada por el servidor, nunca de un campo libre de formulario.

- Resolver contexto y permiso en cada endpoint; administrador global necesita MFA, dueño step-up para colaboradores. Invitar/aceptar debe crear membresía y consumir token en una transacción.
- Validar esquemas de payload y listas de campos por acción/rol. Trabajador no prescribe ni edita ficha técnica; veterinario no cambia DIIO, predio, estado vital ni asociaciones desde la ficha.
- Comparar `expected_version` con el animal bloqueado y aumentar versión al cambiar datos. Cambios de estado a muerto/retirado cierran asociaciones incompatibles.
- Escribir decisión, mutación efectiva, `change_applications`, auditoría y notificación en la misma transacción. `entity_id` de aplicación debe apuntar al registro realmente modificado; por ser polimórfico, esto no es FK universal.
- Validar que el contenido aplicado coincide con el payload aprobado y que mediciones/tratamientos anexos se insertan solo como parte de esa transacción. El DDL no decodifica ni ejecuta JSON arbitrario.
- Comprobar la actividad de cuenta/predio/usuario y vigencia de autor al enviar o revisar solicitudes; revocar un acceso impide nuevas acciones. Las filas históricas siguen referenciando al autor.
- Mantener `animal_states` y tiempos del collar con datos más recientes y coherentes con el animal; son proyecciones reconstruibles, no historias autorizativas.
- Notificar después de persistir la cola. Implementar procesamiento idempotente y no confundir proveedor aceptado con destinatario enterado.
- Registrar altas/cambios de usuarios, lecturas sensibles y operaciones globales en auditoría; el DDL preserva registros, no captura automáticamente todos los accesos HTTP.
- Configurar autorización predial de lectura: este DDL no activa RLS ni concede acceso directo a clientes. Todas las lecturas pasan por API. Adoptar RLS en otra etapa requiere identidad/contexto seguros y pruebas específicas.
- Configurar rol runtime con privilegio mínimo, sin propiedad del esquema, DDL, TRUNCATE ni desactivación de triggers. Separar credencial de migración, API, ingestión y métricas. Otorgar solo operaciones necesarias por servicio; no conectar navegador a PostgreSQL.
- Proteger logs/retención y recolectar CPU/RAM/disco en observabilidad externa; bytes HTTP no equivalen a consumo total de almacenamiento.

## Transacción de aplicación

1. Autenticar sesión/MFA cuando corresponda y resolver actor desde servidor.
2. Bloquear solicitud, objeto y membresía/concesión necesarias.
3. Comprobar permisos, vigencias, versión base y que no haya decisión previa. Repetición idéntica devuelve resultado anterior.
4. Insertar decisión aprobada/directa (o rechazada, sin mutación efectiva).
5. Aplicar campos permitidos o insertar evento/medición/reporte/mantenimiento; incrementar versión si cambia ficha.
6. Insertar aplicación con entidad real, auditoría y cola de aviso.
7. Commit; el trigger diferido rechaza decisión aceptada sin fila de aplicación. Cualquier excepción hace rollback completo.

Una decisión aceptada con fila de aplicación falsa no queda impedida por una FK polimórfica: la API y su rol restringido deben preservar esa correspondencia. No se presenta este DDL como prueba suficiente de autorización de todo el sistema.

## Estados de la solicitud

- Pendiente: solicitud sin decisión.
- Rechazada: decisión `rejected`, sin aplicación.
- Aprobada y aplicada: decisión `approved` y aplicación, ambas comprometidas juntas.
- Directa y aplicada: decisión `direct` y aplicación; veterinario, dueño/admin o trabajador con concesión válida.
- Conflicto: respuesta de API sin decisión terminal; se conserva solicitud pendiente. Una propuesta reformulada usa nueva clave.

## KPI: definiciones

| KPI | Definición |
|---|---|
| Usuarios totales globales | `count(*)` de identidades de `users`, con desglose por estado. Personas únicas; no suma de membresías. |
| Usuarios por dueño | Dueño principal más colaboradores distintos con membresía vigente; si el dueño también colabora, deduplicar unión. |
| Animales | Identidades distintas con permanencia vigente; desglose por estado vital cuando corresponda. |
| Predios/sectores | Activos en el contexto seleccionado. |
| Collares inventariados | Dispositivos del predio; desglose de estados. |
| Collares instalados | Asignaciones vigentes, no conteo arbitrario de `devices.status`. |
| Módulos de software | Códigos funcionales distintos habilitados; separado de número de habilitaciones por predio. |
| Alertas/día | Nuevas alertas por apertura en zona del predio; no intentos ni acciones humanas. |
| Peticiones | Filas de métricas por período/estado/ruta; latencia p95 calculada sobre duración. |
| Consumo | Bytes de tráfico medidos y recursos de infraestructura monitorizados, con unidad y ventana. |

La vista por dueño muestra colaboradores separados del dueño para evitar ambigüedad. Globalmente, una persona colaborando en dos cuentas se cuenta una sola vez.

## FMA y migración

Las tres tablas FMA son extensión P2. La API debe congelar cabecera/detalle al confirmar, validar al menos un animal y transiciones, conservar historial y evidencia externa, y realizar traslado de permanencias explícitamente. No se ha implementado un emisor ni integración oficial.

No ejecutar este SQL sobre producción esperando migrar los datos V1/V2. La migración futura debe mapear `users.role/farm_id` a cuentas/membresías, crear permanencias sin inventar antigüedad, validar DIIO/correos, conservar IDs e historial, y actualizar API/autorización. Requiere copia de seguridad y ensayo.

## Ejecución en base de revisión

```bash
psql "$DATABASE_URL_REVISION" -v ON_ERROR_STOP=1 -f MODELO_FISICO_V3.sql
psql "$DATABASE_URL_REVISION" -v ON_ERROR_STOP=1 -f VALIDACION_SQL.sql
```

Las pruebas usan una transacción con rollback; generan únicamente datos sintéticos. La instalación no modifica el esquema `public` de negocio ni otorga acceso al frontend. El reporte de validación detalla qué se ejecutó realmente.
'''
(P/'05_MODELO_FISICO.md').write_text(physical)

readme='''# GeoCattle — Especificación V3

20 de octubre de 2026. Propuesta basada en Administrador, Dueño, Trabajador y Veterinario. Veterinario con cambios directos, confirmado por el usuario. No implementa pantallas ni modifica la base actual.

## Lectura recomendada

1. [Análisis de usuarios, decisiones y permisos](00_ANALISIS_Y_ALCANCE.md).
2. [29 casos de uso](01_CASOS_DE_USO.md).
3. [44 requisitos funcionales y 22 no funcionales](02_REQUERIMIENTOS.md), con aceptación y trazabilidad.
4. [Modelo conceptual entidad-relación](03_MODELO_CONCEPTUAL.md).
5. [Modelo lógico y diccionario de 48 tablas](04_MODELO_LOGICO.md).
6. [Modelo físico y responsabilidades del backend](05_MODELO_FISICO.md).
7. [SQL PostgreSQL/PostGIS](MODELO_FISICO_V3.sql).
8. [Reporte de validación](VALIDACION.md).

## Diagramas y fuentes editables

- `MODELO_CONCEPTUAL_V3.mmd`: conceptos y cardinalidades de negocio.
- `MODELO_LOGICO_V3.mmd`: entidades, atributos y relaciones principales. Las FK compuestas completas están en el diccionario/SQL.
- `MODELO_V3.drawio`: páginas por dominio con entidades y referencias, editable en diagrams.net.
- `RESUMEN_VISUAL.html`: vista local con diagrama conceptual y navegación de entidades.
- `catalogo_modelo.json`: catálogo fuente.
- `generar_entregables.py` + `controles_fisicos.sql`: regeneración de SQL/diccionario/diagrama lógico.
- `generar_especificacion.py`: regeneración de casos, requisitos y documentos de análisis.
- `generar_visuales.py`: regeneración de diagramas editables y vista local.

## Diagramas de casos de uso

[Ocho vistas UML y cobertura de los 29 casos](diagramas-casos-uso/README.md), con imágenes PNG, vectores SVG, fuentes PlantUML y un Draw.io multipágina.

## Cambios frente a V2

Administrador global separado del dueño; cuenta cliente multipredio; enrolamiento por invitación; MFA y step-up; aprobación granular para trabajador con confianza revocable; veterinario directo; gateways; medidas históricas; agenda sanitaria; KPIs/consumo. Se conservan operación IoT, alertas, notificaciones y FMA como extensión.

El modelo actual implementado y la propuesta V2 permanecen como referencia. V3 es la nueva propuesta de diseño; adoptarla requiere migraciones y cambios de aplicación.
'''
(P/'README.md').write_text(readme)
print(f'Generados {len(CU)} casos, {len(RF)} RF y {len(nfr)} RNF.')
