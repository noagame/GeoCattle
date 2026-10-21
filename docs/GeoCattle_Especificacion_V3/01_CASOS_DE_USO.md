# GeoCattle V3 — Casos de uso

Cada caso incluye autorización, flujo y resultado verificable. El servicio de ingestión y el de avisos son actores técnicos; no son perfiles humanos adicionales. El propietario o administrador actúa según el alcance descrito en `00_ANALISIS_Y_ALCANCE.md`.

| ID | Caso | Actor principal |
|---|---|---|
| CU-01 | Iniciar sesión y seleccionar contexto | Todos; MFA obligatorio para administrador |
| CU-02 | Cerrar sesión o recuperar acceso | Todos |
| CU-03 | Administrar dueños/clientes | Administrador |
| CU-04 | Administrar colaboradores desde plataforma | Administrador |
| CU-05 | Consultar KPIs | Administrador |
| CU-06 | Auditar actividad y consumo | Administrador |
| CU-07 | Administrar perfil propio | Todos |
| CU-08 | Administrar predios | Dueño; administrador |
| CU-09 | Configurar sectores | Dueño; administrador |
| CU-10 | Crear o editar geocerca | Dueño; administrador |
| CU-11 | Registrar y mantener bovino | Dueño; administrador |
| CU-12 | Asignar collar o pastoreo | Dueño; administrador |
| CU-13 | Invitar y administrar colaboradores | Dueño; administrador |
| CU-14 | Enrolarse por invitación | Trabajador; veterinario |
| CU-15 | Consultar mapa del predio | Dueño; trabajador; veterinario; administrador |
| CU-16 | Consultar ficha e historial | Dueño; trabajador; veterinario; administrador |
| CU-17 | Registrar vacuna o antibiótico por trabajador | Trabajador |
| CU-18 | Solicitar estado o reporte del bovino | Trabajador |
| CU-19 | Reportar cambio de batería | Trabajador; dueño |
| CU-20 | Aprobar o rechazar solicitud | Dueño; administrador |
| CU-21 | Conceder o revocar confianza | Dueño; administrador |
| CU-22 | Modificar ficha técnica | Veterinario; dueño; administrador |
| CU-23 | Gestionar ficha sanitaria | Veterinario; dueño; administrador |
| CU-24 | Planificar próxima atención | Veterinario; dueño; administrador |
| CU-25 | Administrar gateways e inventario | Dueño; administrador |
| CU-26 | Recibir telemetría | Servicio de ingestión |
| CU-27 | Generar y atender alerta | Servicio; dueño; trabajador; veterinario |
| CU-28 | Configurar collar y entregar avisos | Dueño; administrador; servicio |
| CU-29 | Gestionar movimiento FMA (extensión) | Dueño; administrador |

## CU-01 — Iniciar sesión y seleccionar contexto

- Actor: Todos; MFA obligatorio para administrador.
- Precondición: Cuenta activa; administrador con factor enrolado.
- Disparador y flujo principal: Introducir correo/contraseña; verificar segundo factor si corresponde; emitir sesión; seleccionar panel global o contexto autorizado.
- Alternativas/excepciones: Credencial incorrecta, factor vencido o usuario suspendido: negar; limitar intentos.
- Postcondición: Sesión emitida con nivel de autenticación y alcance explícitos.
- Requisitos relacionados: RF-01, RF-02, RF-42.

## CU-02 — Cerrar sesión o recuperar acceso

- Actor: Todos.
- Precondición: Cuenta o sesión identificable sin revelar existencia a terceros.
- Disparador y flujo principal: Revocar sesión; para recuperación emitir enlace de un solo uso, verificar identidad y cambiar clave; administrador conserva requisito MFA.
- Alternativas/excepciones: Token vencido/reutilizado: no cambiar clave; no omitir MFA mediante recuperación.
- Postcondición: Tokens anteriores revocados y acción auditada.
- Requisitos relacionados: RF-04.

## CU-03 — Administrar dueños/clientes

- Actor: Administrador.
- Precondición: Sesión global con MFA vigente.
- Disparador y flujo principal: Buscar cliente; crear cuenta y cupo o modificar/suspender; confirmar operación sensible; registrar auditoría.
- Alternativas/excepciones: Correo repetido o cuenta con historia: reutilizar identidad o baja lógica; no borrar referencias.
- Postcondición: Cliente actualizado sin pérdida de sus registros.
- Requisitos relacionados: RF-05, RF-41.

## CU-04 — Administrar colaboradores desde plataforma

- Actor: Administrador.
- Precondición: Colaborador incorporado por dueño y contexto cliente identificado.
- Disparador y flujo principal: Consultar usuario y membresías; corregir datos o suspender acceso; registrar motivo y notificar al dueño.
- Alternativas/excepciones: No reasignar historia a otro usuario ni acceder usando su contraseña.
- Postcondición: Cambio administrativo trazable y sesiones incompatibles revocadas.
- Requisitos relacionados: RF-06, RF-41.

## CU-05 — Consultar KPIs

- Actor: Administrador.
- Precondición: Sesión global con MFA.
- Disparador y flujo principal: Elegir período y dueño opcional; consultar inventario, usuarios, módulos y alertas; mostrar definiciones, corte temporal y zona.
- Alternativas/excepciones: Sin datos: cero o sin medición según métrica; evitar sumas de personas duplicadas.
- Postcondición: Panel coherente con filtros y unidades.
- Requisitos relacionados: RF-07, RF-08, RF-44.

## CU-06 — Auditar actividad y consumo

- Actor: Administrador.
- Precondición: Permiso global y MFA.
- Disparador y flujo principal: Filtrar auditoría/peticiones; inspeccionar actor, estado, latencia/bytes; consultar métricas de infraestructura en observabilidad.
- Alternativas/excepciones: Datos sensibles se enmascaran; consultas paginadas; acceso al auditor se audita.
- Postcondición: Lectura registrada sin editar evidencia.
- Requisitos relacionados: RF-09, RF-10, RF-41.

## CU-07 — Administrar perfil propio

- Actor: Todos.
- Precondición: Sesión propia vigente.
- Disparador y flujo principal: Consultar/editar nombre/teléfono; verificar cambios sensibles; solicitar cierre de cuenta cuando proceda.
- Alternativas/excepciones: No cambiar rol, cupo ni confianza; dueño con predios requiere transferencia/cierre administrativo previo.
- Postcondición: Perfil actualizado o solicitud de cierre registrada.
- Requisitos relacionados: RF-03, RF-21.

## CU-08 — Administrar predios

- Actor: Dueño; administrador.
- Precondición: Cuenta activa y cupo disponible para alta.
- Disparador y flujo principal: Registrar nombre/RUP y ubicación; consultar/editar; desactivar tras resolver asociaciones activas.
- Alternativas/excepciones: Cupo excedido incluso bajo concurrencia: rechazar alta; baja no borra historia.
- Postcondición: Predio pertenece a una cuenta definida.
- Requisitos relacionados: RF-11.

## CU-09 — Configurar sectores

- Actor: Dueño; administrador.
- Precondición: Predio autorizado.
- Disparador y flujo principal: Definir nombre y uso; editar/desactivar sector; revisar geocercas/asignaciones antes de retiro.
- Alternativas/excepciones: Nombre duplicado o relaciones activas incompatibles: pedir resolución explícita.
- Postcondición: Sector y uso guardados con auditoría.
- Requisitos relacionados: RF-12.

## CU-10 — Crear o editar geocerca

- Actor: Dueño; administrador.
- Precondición: Sector autorizado y versión esperada.
- Disparador y flujo principal: Dibujar cuatro o más vértices distintos; mover/agregar/quitar; validar; previsualizar impacto; cerrar asignaciones afectadas y guardar nueva versión.
- Alternativas/excepciones: Autointersección, menos de cuatro vértices o conflicto de versión: no reemplazar la activa.
- Postcondición: Nueva geometría versionada, historia preservada.
- Requisitos relacionados: RF-13.

## CU-11 — Registrar y mantener bovino

- Actor: Dueño; administrador.
- Precondición: Predio autorizado; DIIO disponible.
- Disparador y flujo principal: Registrar identidad/descripción, nacimiento y mediciones; abrir permanencia; consultar y modificar con versión.
- Alternativas/excepciones: DIIO duplicado o fecha inválida: rechazar; retiro cierra asociaciones incompatibles.
- Postcondición: Animal y permanencia consistentes; medidas históricas.
- Requisitos relacionados: RF-14, RF-15.

## CU-12 — Asignar collar o pastoreo

- Actor: Dueño; administrador.
- Precondición: Animal presente; collar o geocerca del mismo predio.
- Disparador y flujo principal: Elegir intervalo; cerrar asignación anterior y abrir nueva en una transacción.
- Alternativas/excepciones: Solapamiento, otro predio o fuera de vigencia: rechazar sin cambios parciales.
- Postcondición: Máximo un collar y una geocerca por animal en cada instante.
- Requisitos relacionados: RF-16, RF-17.

## CU-13 — Invitar y administrar colaboradores

- Actor: Dueño; administrador.
- Precondición: Contexto autorizado y doble verificación exigida.
- Disparador y flujo principal: Verificar acceso; invitar correo/rol/predio o consultar/editar/revocar membresía; confirmar cada escritura con reto ligado a operación.
- Alternativas/excepciones: Invitación vencida se reemite; cuenta de otro predio conserva su identidad y acceso ajeno.
- Postcondición: Invitación o acceso actualizado y auditado.
- Requisitos relacionados: RF-03, RF-18, RF-20.

## CU-14 — Enrolarse por invitación

- Actor: Trabajador; veterinario.
- Precondición: Invitación vigente dirigida a correo verificable.
- Disparador y flujo principal: Abrir enlace; verificar correo; crear credencial o autenticar cuenta existente; aceptar y abrir membresía.
- Alternativas/excepciones: Token reutilizado/revocado o correo diferente: no crear acceso.
- Postcondición: Un usuario y una membresía, sin duplicación por reintento.
- Requisitos relacionados: RF-19.

## CU-15 — Consultar mapa del predio

- Actor: Dueño; trabajador; veterinario; administrador.
- Precondición: Contexto autorizado.
- Disparador y flujo principal: Seleccionar predio/sector; ver límites, animales, gateways y calidad/edad de cada dato; abrir ficha.
- Alternativas/excepciones: Sin Internet del mapa externo: conservar geometrías locales; sin lectura vigente: marcar desconocido.
- Postcondición: Consulta de datos exclusivamente autorizados.
- Requisitos relacionados: RF-22, RF-42.

## CU-16 — Consultar ficha e historial

- Actor: Dueño; trabajador; veterinario; administrador.
- Precondición: Acceso al animal en contexto predial.
- Disparador y flujo principal: Ver DIIO, collar, estado, temperatura superficial, medidas, salud y agenda; filtrar/paginar historia.
- Alternativas/excepciones: Sin sensor o nacimiento conocido: mostrar ausencia; animal trasladado no concede historia futura del destino.
- Postcondición: Vista consistente entre mapa, ficha e historial.
- Requisitos relacionados: RF-23, RF-38.

## CU-17 — Registrar vacuna o antibiótico por trabajador

- Actor: Trabajador.
- Precondición: Membresía vigente y animal del predio.
- Disparador y flujo principal: Introducir hecho observado, producto/dosis/hora y evidencia; validar; guardar solicitud; notificar dueño; si hay confianza vigente, aplicar directamente con evidencia.
- Alternativas/excepciones: Sin confianza queda pendiente; reporte de administración no genera prescripción ni diagnóstico automático.
- Postcondición: Solicitud preservada; ficha efectiva solo cambia tras decisión autorizada.
- Requisitos relacionados: RF-24, RF-32, RF-40.

## CU-18 — Solicitar estado o reporte del bovino

- Actor: Trabajador.
- Precondición: Membresía vigente y versión base conocida.
- Disparador y flujo principal: Elegir estado o redactar reporte; enviar; notificar; aplicar directo solo si existe confianza para esa acción.
- Alternativas/excepciones: Estado incompatible o versión obsoleta: conflicto; no sobrescribir.
- Postcondición: Pendiente o aplicado distinguido visualmente.
- Requisitos relacionados: RF-25.

## CU-19 — Reportar cambio de batería

- Actor: Trabajador; dueño.
- Precondición: Collar identificado en predio autorizado.
- Disparador y flujo principal: Registrar batería, hora y resultado; trabajador solicita o usa confianza; dueño aplica directamente.
- Alternativas/excepciones: No actualizar telemetría de batería a partir de un reporte manual.
- Postcondición: Mantenimiento efectivo o solicitud pendiente trazable.
- Requisitos relacionados: RF-26.

## CU-20 — Aprobar o rechazar solicitud

- Actor: Dueño; administrador.
- Precondición: Solicitud pendiente de predio autorizado.
- Disparador y flujo principal: Revisar antes/después y versión; aprobar o rechazar con motivo; al aprobar aplicar dato, decisión, aplicación, aviso y auditoría en una transacción.
- Alternativas/excepciones: Decisión previa: devolver resultado idempotente; versión cambiada: conflicto y solicitud pendiente.
- Postcondición: Sin cambios parciales y una sola aplicación.
- Requisitos relacionados: RF-27, RF-28, RF-40.

## CU-21 — Conceder o revocar confianza

- Actor: Dueño; administrador.
- Precondición: Trabajador vigente y verificación sensible.
- Disparador y flujo principal: Elegir acción permitida y vigencia; conceder/revocar; registrar y notificar.
- Alternativas/excepciones: No habilitar gestión de usuarios, geocercas o prescripción; revocación se comprueba al aplicar.
- Postcondición: Exención granular auditable; pendientes previos siguen revisión manual.
- Requisitos relacionados: RF-29, RF-41.

## CU-22 — Modificar ficha técnica

- Actor: Veterinario; dueño; administrador.
- Precondición: Animal autorizado y versión base.
- Disparador y flujo principal: Editar descripción técnica y registrar nuevas mediciones; validar campos permitidos; aplicar directamente y auditar.
- Alternativas/excepciones: Veterinario no cambia DIIO, permanencia, collar ni estado vital mediante este formulario; conflicto conserva datos previos.
- Postcondición: Ficha actualizada con medidas e historia de cambios.
- Requisitos relacionados: RF-15, RF-30.

## CU-23 — Gestionar ficha sanitaria

- Actor: Veterinario; dueño; administrador.
- Precondición: Animal autorizado; usuario con permiso directo.
- Disparador y flujo principal: Registrar evento/tratamientos o consultar historia; corregir/anular creando sucesor; aplicar directamente con autoría.
- Alternativas/excepciones: Otro animal o evento ya sustituido: rechazar; jamás borrar el original.
- Postcondición: CRUD funcional mediante alta, lectura, corrección y anulación histórica.
- Requisitos relacionados: RF-30, RF-31, RF-32.

## CU-24 — Planificar próxima atención

- Actor: Veterinario; dueño; administrador.
- Precondición: Animal autorizado.
- Disparador y flujo principal: Elegir tipo/fecha; registrar plan; reprogramar/cancelar por sucesor; recordar; completar vinculando administración real.
- Alternativas/excepciones: Recordatorio vencido no marca administración automáticamente.
- Postcondición: Agenda vigente y hechos realizados separados.
- Requisitos relacionados: RF-33, RF-40.

## CU-25 — Administrar gateways e inventario

- Actor: Dueño; administrador.
- Precondición: Predio autorizado.
- Disparador y flujo principal: Registrar EUI/serie y posición; actualizar estado del gateway/collar; visualizar en mapa.
- Alternativas/excepciones: EUI duplicado u objeto de otro predio: rechazar; retiro con asignación activa exige cierre.
- Postcondición: Infraestructura identificable, sin prometer cobertura por inventario.
- Requisitos relacionados: RF-34.

## CU-26 — Recibir telemetría

- Actor: Servicio de ingestión.
- Precondición: Credencial técnica, codec y dispositivo registrados.
- Disparador y flujo principal: Validar/deduplicar; resolver asignación a captura; guardar lectura y recepciones; actualizar proyecciones solo si nueva; evaluar reglas.
- Alternativas/excepciones: Duplicado no rejuvenece estado; caída de BD conserva cola; lectura no asociada queda para revisión.
- Postcondición: Una lectura por sesión/secuencia y contexto histórico correcto.
- Requisitos relacionados: RF-35, RF-36.

## CU-27 — Generar y atender alerta

- Actor: Servicio; dueño; trabajador; veterinario.
- Precondición: Reglas habilitadas y contexto autorizado.
- Disparador y flujo principal: Evaluar lectura/temporizador; crear alerta única; encolar aviso; usuario reconoce/revisa/concluye atención.
- Alternativas/excepciones: Sensores insuficientes: desconocido; reconocer no demuestra regreso ni enfermedad.
- Postcondición: Condición técnica y atención humana independientes.
- Requisitos relacionados: RF-37.

## CU-28 — Configurar collar y entregar avisos

- Actor: Dueño; administrador; servicio.
- Precondición: Dispositivo autorizado o notificación persistida.
- Disparador y flujo principal: Solicitar intervalo; enviar y esperar confirmación; procesar notificaciones con reintentos y registrar resultado.
- Alternativas/excepciones: Sin nodo/WAN: pendiente o fallo; no fingir aplicación ni lectura humana.
- Postcondición: Configuración confirmada y entregas trazables.
- Requisitos relacionados: RF-39, RF-40.

## CU-29 — Gestionar movimiento FMA (extensión)

- Actor: Dueño; administrador.
- Precondición: Módulo habilitado y datos oficiales verificables cuando corresponda.
- Disparador y flujo principal: Crear borrador y animales; confirmar/congelar; registrar evidencia externa; ejecutar traslado cerrando asignaciones y permanencia.
- Alternativas/excepciones: Sin folio/evidencia no declarar confirmación oficial; cancelación ejecutada requiere regularización.
- Postcondición: Documento e historia preservados; sin integración SIPEC presumida.
- Requisitos relacionados: RF-43.

## Flujo detallado de aprobación

1. La API autentica al actor y resuelve cuenta/predio sin confiar en un `farm_id` enviado sin validar.
2. Valida permiso, objeto, campos y versión; crea solicitud inmutable con clave de idempotencia y payload validado.
3. Trabajador sin confianza: guarda solicitud + aviso + auditoría; no crea registro efectivo. Se responde `pending`.
4. Dueño/admin, veterinario en su alcance, o trabajador con confianza vigente: aplica camino directo dentro de la misma transacción.
5. Revisión manual: bloquear solicitud y objeto; comprobar estado, contexto, versión y vigencia del autor; rechazar exige motivo.
6. Aprobación: insertar decisión, modificar datos efectivos o agregar evento, registrar aplicación, auditoría y aviso; confirmar todo junto. Un fallo revierte toda la transacción.
7. Repetición devuelve la decisión y aplicación ya existentes; payload distinto con la misma clave de idempotencia se rechaza.
8. Si hay conflicto de versión, no se escribe decisión aceptada: la solicitud queda pendiente para reformular o rechazar. La nueva propuesta referencia la anterior en el payload validado para conservar el motivo.
9. La confianza se comprueba dentro de la transacción y se bloquea la concesión contra revocación concurrente. No aplica retroactivamente a solicitudes antiguas.
10. Aprobar un cambio no ejecuta correos antes de commit; la cola persistida se entrega posteriormente.
