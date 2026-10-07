# GeoCattle: requisitos derivados del segundo informe

Revisión del 7 de octubre de 2026. Este documento convierte las decisiones del informe en requisitos verificables para frontend, backend y base de datos. Una especificación, una prueba simulada y una validación de terreno son evidencias distintas: aquí no se declara que las metas hayan sido alcanzadas.

## Fuente y método

- Fuente: `Entregables_GeoCattle_2026-10-04/Informe_2_GeoCattle_con_Viabilidad_y_Flujo_Caja_2026-10-04.docx`, «Segundo informe de desarrollo GeoCattle: Diseño del sistema, viabilidad y flujo de caja», 4 de octubre de 2026.
- SHA-256: `a3d50cb791fa35a62999cdaa6294a71a1e27193b00c5541364d9df341d03cb2e`.
- Es la ampliación más reciente del segundo informe disponible; incorpora viabilidad y flujo de caja a la versión `Informe_2_GeoCattle_Componentes_Integrados_2026-10-04.docx`.
- Se extrajeron 1.756 párrafos no vacíos de `word/document.xml`, incluyendo tablas, respetando su orden. [informe2_fuente.txt](informe2_fuente.txt) conserva la extracción numerada. `¶774` refiere al párrafo 0774, no a la página Word.
- Las figuras embebidas no se convierten en texto; sus contratos/diccionarios acompañantes sí se incluyen. Los informes originales se conservaron intactos.
- No se encontraron `AGENTS.md` en el workspace ni en el directorio padre examinado.

## Resultado y alcance

El propietario debe supervisar bovinos por DIIO, consultar ubicación y sensores con calidad y antigüedad, configurar geocercas, mantener asociaciones temporales animal/collar y atender eventos auditables. Captura, persistencia, reglas y consulta deben funcionar aun sin Internet cuando LAN, radioenlace y servidor local siguen operativos (¶6, ¶31–40, ¶861, ¶1172).

Hay dos realizaciones: demo académica ESP32/XBee o Wi-Fi/MQTT y cliente Wio E5/LoRaWAN con 70 bovinos. Comparten contrato y aplicación; datos, credenciales y evidencia deben separarse. El resultado académico no acredita montaje, autonomía ni cobertura comercial (¶41–68, ¶810, ¶984).

El pedido de SaaS se implementa como aplicación con cuentas y autorización por predio. El informe no exige suscripciones, cobro automático, pasarela de pago ni facturación; tampoco sustituir la supervisión local por nube pública. Estas funciones necesitarían una especificación adicional.

## Arquitectura y controles transversales

| Capa | Decisión del informe | Fuente/condición |
| --- | --- | --- |
| Frontend | React/Leaflet, gestión y mapa geográfico. | ¶169. Grafana apoya soporte, no reemplaza gestión. |
| API/reglas | FastAPI sobre Linux, servicios reproducibles. | ¶211, ¶808–827. |
| Base | PostgreSQL/PostGIS, relaciones temporales, transacciones y consultas espaciales. | ¶171, ¶831–834. SQLite sólo demo reducida con migración posterior. |
| Transporte | Mosquitto/MQTT QoS1, ingestor, deduplicación y cola persistente antes de DB. | ¶211, ¶810–811. ACK MQTT/LoRaWAN no acredita escritura de aplicación. |
| Radio | ChirpStack, AU915, clase A/OTAA y claves únicas. | ¶164, ¶835–860. Perfil interoperable requiere hardware. |
| Redis/red | Dependencias ChirpStack separadas de base de negocio. | ¶860. |
| Acceso | HTTPS en LAN; remoto autenticado/controlado. | ¶848–849. |
| Avisos | Canal contratado HTTPS; cola/intentados/resultados sin bloquear evento local. | ¶850–851, ¶937–938, ¶1589–1590. |
| Fechas | UTC con zona en DB; presentación America/Santiago. | ¶834. |
| Ambientes | Desarrollo/simulación/piloto con bases y credenciales separadas. | ¶827, ¶984, ¶1593–1594. |

Privilegio mínimo por predio, sesión/autorización en cada escritura, secretos fuera del código, credencial de servicio para ingestión, validación de rangos/fechas, auditoría de cambios, respaldos y finalidad/retención/acceso de datos son controles requeridos (¶807, ¶826–827, ¶1052–1064). Una FK por sí sola no autoriza a un usuario (¶1501). No se declara certificación ni conformidad legal sólo por citar normas.

## Trazabilidad funcional: RF01–RF24

Los RF del anexo 5 mantienen identificadores del primer informe (¶1598–1699). La interpretación implementable usa cuerpo y anexos 2–4.

| RF | Capacidad y aceptación implementable | CU | Prueba/KPI | Fuente |
| --- | --- | --- | --- | --- |
| 01 | Animal con DIIO único, orientación y habilitado; duplicidad rechazada sin cambiar historial. | 01 | SW03 | ¶1603–1606, ¶1483–1485 |
| 02 | Ubicación periódica; nulo sin fix, calidad/antigüedad explícitas. | 05 | HW03, RF02 radio, K02 | ¶1607–1610, ¶1537–1540 |
| 03 | Polygon autorizado válido, versionado y recuperable. | 02 | SW04 | ¶1611–1614, ¶1560–1562 |
| 04 | Salida tras dos posiciones válidas consecutivas exteriores; borde interior. | 06 | SW01, K04 | ¶1615–1618, ¶774 |
| 05 | Evento local tras detección y aviso externo encolado. | 06,09 | SW06, K03 | ¶1619–1622, ¶777–779 |
| 06 | Animal/DIIO, dispositivo y evento identificables en detalle/mapa/lista. | 03,07 | SW05 | ¶1623–1626, ¶830 |
| 07 | Historial de ubicación ordenado/paginado sin duplicados. | 04 | SW02 | ¶1627–1630, ¶1568–1570 |
| 08 | Índice de actividad con ventana/algoritmo versionados; no diagnóstico. | 05 | HW03 | ¶1631–1634, ¶1543–1544 |
| 09 | Baja actividad prolongada sólo con ventana y línea base individual validadas; demo sintética explícita. | 06 | SW01 ventana validada | ¶1635–1638, ¶1552, ¶1699 |
| 10 | Temperatura superficial asociada temporalmente al animal; nulo ante fallo. | 05 | HW03 interfaz térmica | ¶1639–1642, ¶1541–1542 |
| 11 | Aviso térmico configurable; operacional tras validar contacto/interpretación. | 06 | SW01 umbral sintético | ¶1643–1646, ¶1552, ¶1699 |
| 12 | Sensores y calidad de lectura que motivó evento. | 07 | SW06 | ¶1647–1650, ¶830 |
| 13 | Propietario destinatario autorizado; canal/intentados/resultados registrados. | 09 | SW12 | ¶1651–1654, ¶779 |
| 14 | Consulta web autorizada por sesión/predio. | 03 | SW11 | ¶1655–1658, ¶1563–1566 |
| 15 | Historial de eventos, estados y acciones humanas conservados. | 04 | SW06 | ¶1659–1662, ¶778–779 |
| 16 | Intervalo solicitado/enviado/aplicado, versión confirmada por nodo. | 08 | SW07 | ¶1663–1666, ¶1553 |
| 17 | Asociación DIIO/módulo temporal sin solapamientos; reasignación conserva historia. | 01 | SW03 | ¶1667–1670, ¶1490–1491 |
| 18 | Control independiente de pérdida de comunicación. | 06 | CO02, K02 | ¶1671–1674, ¶772, ¶1551 |
| 19 | Severidad normal/advertencia/crítico; calidad desconocida no se pinta normal. | 06 | SW06 | ¶1675–1678, ¶1551 |
| 20 | Consultar rebaño/sector/animal; lista y ficha coherentes. | 03 | SW11 | ¶1679–1682, ¶1565–1566 |
| 21 | Contexto evento: animal/módulo/tipo/severidad/times/lectura/geocerca-versión, acciones y avisos. | 07 | SW05,SW06 | ¶1683–1686, ¶1510–1518 |
| 22 | 24h/7d/30d/rango válido, paginado; vacío explícito sin datos. | 04 | SW02,SW11 | ¶1687–1690, ¶1569 |
| 23 | Orientación carne o leche. | 01 | SW03 | ¶1691–1694, ¶1484 |
| 24 | Recomendar revisión presencial sin afirmar enfermedad o abigeato. | 06 | SW06 texto | ¶1695–1698, ¶39–40, ¶1552 |

RF02 aparece tanto como requisito funcional como prueba de radio: usar REQ-RF02 y TEST-RF02 evita confundirlos en registros.

## Flujos CU01–CU10

| Caso | Flujo, excepciones y postcondición |
| --- | --- |
| CU01 | Sesión autorizada; registrar DIIO/orientación; módulo habilitado mismo predio; cerrar asignación previa/abrir nueva transaccionalmente. Duplicidad/solapamiento rechazan sin alterar historia. ¶1555–1558. |
| CU02 | Sector/versión; dibujar GeoJSON; validar, revisar impacto, guardar versión con autor/fecha. Geometría inválida/edición concurrente conserva activa/borrador. ¶1560–1562. |
| CU03 | Abrir mapa/lista, filtrar sector, seleccionar animal, revisar antigüedad. Sin mapa externo mostrar geometrías locales; vencido conserva hora. ¶1563–1566. |
| CU04 | Elegir período/rango válido; paginar en orden. Vacío explícito; no se promete historia de 30d antes de acumularla. ¶807, ¶1567–1570. |
| CU05 | Servicio autenticado: validar, decodificar, deduplicar, resolver asignación temporal, persistir/evaluar. Duplicado sin nueva escritura; falla DB conserva cola; sin asociación a revisión. ¶1580–1583. |
| CU06 | Lecturas válidas evalúan variables; temporizador evalúa comunicación. Incompleto desconocido/degradado. Condición activa única; resolución con evidencia. ¶771–775, ¶1584–1586. |
| CU07 | Consultar contexto, reconocer, inspeccionar, concluir atención; actor/fecha/nota inmutables. Reconocer no resuelve condición; error API no muestra éxito. ¶1571–1574. |
| CU08 | Validar T/versión, solicitado→downlink→enviado→versión aplicada por nodo. Clase A espera uplink/ventana. Sin nodo queda pendiente hasta timeout/revisión. ¶1553, ¶1575–1578. |
| CU09 | Encolar/procesar según WAN/proveedor; guardar pendiente/aceptado/fallido/expirado e intentos. Aceptado no prueba lectura humana; fallo no elimina evento. ¶779, ¶1589–1590. |
| CU10 | Escenario reproducible aislado, source=sim. No compartir base/tópicos/credenciales con piloto. ¶827, ¶1591–1595. |

## Reglas exactas

1. T activo es el **aplicado y confirmado**, no un cambio solicitado (¶1553).
2. Posición vigente: válida con edad ≤2T+30s; T300→630s, T180→390s (¶774).
3. Ausencia comunicación: última recepción de paquete **nuevo y autenticado** excede 3T+30s; T300→930s, T180→570s. Temporizador independiente (¶1551, ¶1073–1075).
4. Frescura por variable: GNSS nulo puede coexistir con temperatura válida y comunicación reciente. Desconocido nunca se representa normal (¶771–772, ¶1551).
5. Salida: **dos exteriores válidos consecutivos**. Inválido rompe consecutividad y no prueba regreso. Borde interior por ST_Covers (¶774).
6. Tardío: sólo historial, no reemplazar estado reciente. Asignación a observed_at, no al recibo (¶775, ¶782).
7. Duplicado: clave global device_id/session_id/seq antes de asociación; no rejuvenece posición/comunicación (¶811, ¶832, ¶1089).
8. Geometrías WGS84/SRID4326; GeoJSON longitud/latitud, Leaflet orden adaptado. Distancias en metros vía geography/proyección (¶833).
9. No se fijan números operacionales para proximidad/tolerancia GNSS, batería, actividad o temperatura. Deben validarse; umbral demo etiquetado sintético (¶215, ¶774, ¶1552).
10. Detección hasta 2T+5s con GNSS/radio: T300→605s, T180→365s. Recepción→evento≤2s es otra métrica, no detección instantánea (¶854, ¶873–878).

Condición técnica activa/resuelta y atención pendiente/reconocida/en revisión/concluida son independientes. Evento activo sigue visible tras reconocimiento; resuelto conserva auditoría. Revisión puede abrir nuevo ciclo humano (¶778–779). Tipos: salida, comunicación, batería, actividad y anomalía térmica configuradas (¶39, ¶1510–1512).

## Modelo de datos

Anexo2 ¶1470–1527, UUID y tipos PostgreSQL propuestos; autorización además de restricciones DB.

| Entidad | Campos | Integridad |
| --- | --- | --- |
| user | id, name, phone?, password_hash, active | Hash, no contraseña plana. |
| farm | id, owner_id→user, name, timezone | Propietario autorizado; America/Santiago. |
| sector | id, farm_id, name | Un predio. |
| animal | id, farm_id, diio:text, orientation:carne/leche, enabled | DIIO único global; preservar ceros. |
| device | id, dev_eui, hw_rev, fw_version, enabled, installed_at | DevEUI único; secretos separados. |
| assignment | id, animal_id, device_id, valid_from, valid_to? | Fin>inicio; sin solapamiento por animal/dispositivo. |
| geofence | id, sector_id, version, Polygon4326, valid_from/to | Válida; versiones activas no superpuestas. |
| animal_zone | id, animal_id, geofence_id, vigencia | Mismo predio; historial de zona. |
| telemetry | id, device_id, assignment_id?, session_id, seq:bigint, observed_at/received_at, Point4326?, temperature_c?, activity_index?, battery_mv, quality:jsonb, source:device/sim | Único device/session/seq; rangos/tiempos; sin asociación a revisión. |
| event | id, animal_id?, device_id, telemetry_id?/geofence_id?, type, severity, opened_at/resolved_at?, condition | Una activa por clave; resolver con evidencia. |
| event_action | id, event_id, actor_id, action, at, note | Inmutable: reconocer/revisar/concluir. |
| notification_attempt | id, event_id, channel, attempt, at, status, provider_id?/error? | Único evento/canal/intento. |
| device_config | id, device_id, version, interval, requested_at/applied_at?, status | Intervalo válido; solicitado/enviado/aplicado/fallo. |
| audit_log | id, actor_id?, object_type/id, action, at, before/after:jsonb | Restringir acceso/datos sensibles; motivo/autor. |
| maintenance | id, device_id, battery_id?, kind, at, responsible_id, result | Recarga/inspección/sustitución/retiro. |

Índices: telemetría por dispositivo/hora y animal/hora; vigencias; eventos/condición; GiST geometrías. Exclusión temporal o bloqueo transaccional para asignaciones. Fechas timestamptz UTC, null indica ausencia, nunca coordenada0 inventada. FK deben pertenecer al mismo predio (¶832–834, ¶1525–1527).

Retención propuesta: **30d alta resolución en preserie**, revisión con productor antes de borrar. No habilita borrado automático ni garantiza historia ya acumulada. Cliente define política por uso/costos/obligaciones (¶1526).

### Vacíos del diccionario que requieren decisión explícita

- Device no lista farm_id, pero CU01/¶834 exigen pertenencia módulo/animal al mismo predio: añadir pertenencia explícita o inventario equivalente.
- Animal no lista sector_id: puede derivarse animal_zone→geofence→sector; si se agrega, mantener consistencia.
- Geocerca requiere identidad lógica además de fila/version para validar versión esperada e impacto (¶781, ¶817–818).
- Login y enum de roles no están definidos: email/username y propietario/soporte/servicio son extensiones técnicas posibles, con aislamiento por predio.
- DIIO corregido conserva autor/motivo; retiro formal evita ausencia esperada (¶1502).
- OTAA secreto no viaja en telemetría ni respuestas públicas (¶1488, ¶1549).

## API y contrato

| Operación | Aceptación | Fuente |
| --- | --- | --- |
| POST /animals, /assignments | DIIO único; mismo predio; temporal sin solapamiento. | ¶815–816 |
| POST /geofences | Geometría válida, versión esperada, confirmación impacto. | ¶817–818 |
| GET /animals, /history | Sesión/autorización, paginación, filtros UTC válidos. | ¶819–820 |
| POST /events/{id}/actions | Actor/acción/fecha; reconocer no cierra condición. | ¶821–822 |
| POST /devices/{id}/config | Intervalo/versión, estados solicitado/enviado/aplicado. | ¶823–824 |
| Ingestión interna | Credencial de servicio, no anónima, idempotente. | ¶825–826 |

Errores no muestran éxito; escrituras transaccionales; frontend espera confirmación (¶827). Prefijo técnico/version API permitido sin alterar semántica.

Contrato lógico (¶1528–1549): schema_version, device_id/DevEUI, session_id/seq, observed_at UTC, received_at añadido por servidor, position o null/calidad, surface_temperature_c o null, activity_index/ventana/algoritmo, battery_mv/flags, source=device|sim. No enviar DIIO como identidad del collar: se resuelve por asignación.

JSON entre servicios no es payload LoRaWAN final. Longitud/FPort/enteros escalados/bitmap/codec se liberan juntos al validar tasa/región. Porcentaje batería sólo con curva validada; mV no se transforma arbitrariamente (¶1545–1549).

## No funcionales RNF01–RNF11

| RNF | Condición | Evidencia | Fuente |
| --- | --- | --- | --- |
| 01 | Cobertura predio/obstáculos. | RF02 radio/mapa/K01/K02, campo. | ¶1704–1706 |
| 02 | Comunicación rural. | RF01/RF02 radio, CO01. | ¶1707–1709 |
| 03 | Autonomía. | HW04/K08 collar final, no demo USB. | ¶1710–1712 |
| 04 | Exteriores. | ME01/gabinete/sellos, sin IP supuesto. | ¶1713–1715 |
| 05 | Seguridad animal. | ME01/responsable/retiro si molesta. | ¶1716–1718 |
| 06 | Costo accesible. | BOM/instalado/aceptación productor. | ¶1719–1721 |
| 07 | Latencia. | K03/K04/acuerdo T. | ¶1722–1724 |
| 08 | Local sin WAN. | CO01 LAN/radio/servidor activos. | ¶1725–1727 |
| 09 | Avisos externos separados. | CO01/SW12/evento local/cola. | ¶1728–1730 |
| 10 | Web adaptable. | SW11 escritorio/teléfono. | ¶1731–1733 |
| 11 | Retención definida. | Política/CO03/restauración. | ¶1734–1736 |

## KPI y SLA propuestos

| KPI | Meta | Ventana/evidencia |
| --- | --- | --- |
| K01 | ≥95% paquetes únicos válidos recibidos/emitidos. | 3 sesiones/sector, ≥100 emisiones/escenario. |
| K02 | ≥95% animal-minuto con GNSS válido edad≤2T+30s. | 7d preserie. |
| K03 | p95 recepción→evento≤2s. | ≥100 eventos controlados, reloj servidor. |
| K04 | Aviso cruce≤2T+5s, GNSS/radio válidos. | 20 cruces observados/sincronizados. |
| K05 | 100% lecturas únicas recuperadas sin duplicados. | Corte30min, 1.000 mensajes numerados. |
| K06 | p95 GET estado≤1s, error<1%. | 5 clientes/10min/carga70nodos. |
| K07 | ≥99% disponibilidad bruta local. | 7d, monitor1min; incluye mantenimiento. |
| K08 | ≥7d autonomía T300 hasta umbral seguro. | 2 ciclos/unidad Wio E5 y preserie. |
| K09 | ≤1 falso aviso/100 horas-animal. | ≥200 horas-animal con referencia. |
| K10 | ≥4/5 tareas sin ayuda; mediana localizar≤30s. | Productor/tareas/ayuda registrados. |
| K11 | RTO≤2h, RPO≤24h. | Restauración limpia previa piloto. |
| K12 | ≥25% reducción búsqueda/conteo. | 7d base vs7d piloto comparable. |

¶862–905: metas propuestas, no conseguidas. Academia se centra K03/K05/K06/K10. K08 y radio requieren hardware final; K10/K12 productor; K07 ventana temporal. El 99% en7d permite100,8min de indisponibilidad.

Capacidad ¶853–855: 70 nodos T300=20.160/día,604.800/30d; T180=33.600/día,1.008.000/30d. A1kB con índices ~0,60–1,01GB/mes antes de eventos/logs/backups; medir real. Cinco consultas concurrentes y ráfagas.

SLA ¶923–940: local24×7 en piloto, soporte horario pactado, backup diario RTO2h/RPO24h, mantenimiento propuesto≤30min/aviso24h, atención crítica inicial≤2h dentro de soporte. Aviso externo condicionado a Internet/SIM/proveedor, sin SLA hasta contratación/prueba. Disponibilidad web no garantiza posición de todo rebaño. No hay SLA contractual firmado.

## Plan de pruebas y aceptación

Ficha por ejecución: ID/versión/precondiciones/datos/pasos/esperado/observado/fecha/responsable/evidencia; aprobado/fallido/no ejecutado. Meta no sustituye registro (¶942).

| ID | Prueba y aceptación |
| --- | --- |
| SW01 | Dentro/borde/fuera/null; dos exteriores válidos; inválido rompe consecutividad; desconocido distinto de normal. |
| SW02 | Duplicado/tardío: una escritura, estado actual intacto. |
| SW03 | DIIO repetido/asignación solapada/reasignación: rechazo transaccional, historial temporal correcto. |
| SW04 | Polygon inválido/versión obsoleta: error y activa conservada. |
| SW05 | Humo lectura→persistencia→mapa/historial→evento, sin críticos. |
| SW06 | Reconocer activo no resuelve; retorno evidencia; atención auditada. |
| SW07 | T solicitado con nodo desconectado: pendiente hasta confirmación, no aplicado ficticio. |
| SW08 | Sin sesión/otro predio/credencial inválida/HTML:401/403, sin acceso ajeno/script. |
| SW09 | 70nodos/5clientes/10min: K03/K06, sin pérdida/error inesperado. |
| SW10 | Carga creciente aislada: umbral degradación registrado y recuperación al reducir. |
| SW11 | Productor registra/consulta/filtra/reconoce/historia: K10, bitácora, escritorio/teléfono. |
| SW12 | Rechazo proveedor/reintentos/WAN vuelve: evento intacto, intentos visibles, sin duplicación. |
| CO01 | WAN cortada30min con LAN/radio/servidor: captura/persistencia/consulta continúan, avisos pendientes. |
| CO02 | Puente cortado/buffer reenvío: K05, historia no rejuvenece estado. |
| CO03 | Backup en instancia limpia: K11 y DIIO/asociaciones/geometrías/lecturas/eventos coherentes. |
| CO04 | Energía controlada: UPS/apagado seguro, arranque sin corrupción/cola recuperable. |

¶941–984, ¶1016–1027: SW01/SW02 automáticas; integrales con servicios/dispositivos reales. HW01–04, RF01–03 radio, ME01, EN01 y AC01–03 (¶985–1038) no se aprueban sólo con software.

Salida (¶65, ¶984, ¶1067–1068, ¶1756): demo humo aprobado/sin críticos; preserie integración+seguridad+recuperación y5–10unidades/2–4semanas; lote70 además radio/energía/montaje/aceptación, manual/inventario/versiones/actas.

## Decisiones pendientes y límites

| Tema | Decisión requerida |
| --- | --- |
| Batería | Umbral mV/corte/curva porcentaje no definidos; conservar mV/configuración y no afirmar autonomía. |
| Temperatura | Validar contacto/interfaz; aviso preventivo, no corporal/diagnóstico. |
| Actividad | Definir algoritmo/version/ventana/línea base individual, no regla clínica universal. |
| T/proximidad | 180–300s dimensiona capacidad; límites y tolerancia no totalmente fijados; documentar decisión y confirmación. |
| Resolver salida | Dos exteriores definidos; número de interiores no especificado. Política explícita; null nunca resuelve. |
| Unicidad evento | Componentes de clave activa no exhaustivos; clave estable dispositivo/tipo/zona y concurrencia verificadas. |
| Avisos | Proveedor/canal/retry policy no contratados; adaptador/cola auditada sin declarar entrega real simulada. |
| Cuenta/roles | Login/perfiles detallados no definidos; extensión mínima documentada y test IDs ajenos. |
| Geocerca | Identidad/version/API impacto requiere precisión; bloqueo optimista e historia conservada. |
| Sin asignación | Conservar revisión, no atribuir aproximando al animal actual. |
| WAN/offline | Geometrías locales deben mostrarse aunque tiles no disponibles; probar entorno sin Internet. |
| Retención | 30d propuesto, consulta al productor antes de eliminar. |
| Payload radio | FPort/longitud/codec final por validar; JSON no acredita hardware interoperable. |
| Viabilidad | Informe no recomienda70como inversión recuperable en base; continuar académico/piloto condicionado. |

¶7, ¶215, ¶774, ¶1552–1553, ¶1699, ¶1737–1756. Estos límites permiten implementar frontend/backend/esquema, pero no certificar campo ni presentar decisiones sin validación como resultados conseguidos.

Guion ¶1596–1597: registrar nodo/animal; lectura real GNSS/ADXL345/DS18B20; recepción/historia; salida controlada; reconocer sin resolver; cortar WAN/continuar LAN; silenciar/transmisión-vencida; recuperar secuencia sin duplicar. Si se usa simulador, etiquetar origen y evidencia. Segundo nodo real sólo con hardware completo confirmado.
