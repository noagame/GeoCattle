# Revisión de implementación y cumplimiento

Fecha: 7 de octubre de 2026. Base normativa del proyecto: [REQUISITOS_INFORME_2.md](REQUISITOS_INFORME_2.md). La revisión de código acredita decisiones implementadas; los resultados de ejecución se registran por separado.

## Controles revisados en el código

- API con sesión HttpOnly, SameSite, hash Argon2, CSRF y validación de Origin. Roles owner/operator/viewer y consultas filtradas por predio. Escrituras reciben el predio de la sesión, no del cuerpo.
- DB PostgreSQL/PostGIS con FK compuestas entre recursos/predios, exclusión temporal de asignaciones, DIIO/DevEUI únicos, telemetría única por dispositivo/sesión/secuencia y condición activa única por dispositivo/tipo.
- Geocercas válidas con ST_Covers, borde interior, versión esperada y preservación de versiones anteriores. Dos exteriores válidos confirman salida; null rompe consecutividad y no resuelve salida.
- Fechas UTC, asociación por hora de observación, paquetes tardíos sólo en historial, variables nulas independientes y última posición válida presentada con antigüedad.
- Condición técnica y atención humana separadas; acciones/telemetría/auditoría inmutables. Configuración solicitada no cambia T hasta confirmación de versión por nodo.
- Simulación protegida por APP_ENV/SIMULATION_ENABLED y ambiente del predio; secretos de entorno fuera del código. API/worker utilizan rol PostgreSQL restringido en el despliegue.
- Cola de avisos e intentos separados; sin proveedor configurado el canal aparece deshabilitado y la alerta local permanece. La aceptación externa no prueba lectura humana.

Durante la revisión se detectaron y comunicaron tres discrepancias: ausencia calculada inicialmente con 2T+30 en vez de 3T+30; dato GNSS nulo representado como normal cuando había posición anterior vigente; contexto del evento sin la lectura/geocerca causantes. El código fue corregido para aplicar 3T+30, degradar calidad y exponer contexto histórico. Las tres correcciones pasaron la verificación HTTP final.

Las primeras pruebas HTTP también detectaron una carrera de persistencia: login200 podía preceder a la confirmación de la transacción, y un GET inmediato devolvía401. Las dependencias DB se corrigieron con scope function para confirmar antes de enviar la respuesta. El smoke final aprobó cinco sesiones consecutivas con GET inmediato, además de las cuentas de roles.

## Evidencia de ejecución

La prueba [smoke_api.py](../qa/smoke_api.py) utiliza HTTP real, cookies y CSRF, con guardas que impiden escrituras si la configuración, el servidor o el predio no son de simulación. Crea identificadores UUID únicos y conserva datos de ensayo; no modifica informes ni configuración privada.

Resultado real del 7 de octubre de 2026, API local http://127.0.0.1:8000 y PostgreSQL/PostGIS: **135 verificaciones aprobadas, 0 fallidas; ejecución completa con exit0**, incluyendo owner/operator/viewer y otra cuenta de predio distinto. Evidencia individual: [smoke_latest.json](../qa/smoke_latest.json). Los secretos y cuerpos de respuesta no se incluyen. Los ensayos se agregaron con identificadores únicos; al finalizar se deshabilitaron sus dos animales y dispositivo, sin borrar historia ni modificar los70 seed.

La guarda también se ensayó con APP_ENV=production: la prueba se interrumpió antes de consultar la API o escribir datos ([guard_production_blocked.json](../qa/guard_production_blocked.json)).

Cobertura ejecutada: login/dashboard de base70, registro/duplicidad DIIO, dispositivo/sector/zona/asignación, borde/dos exteriores, invalidez GNSS y consecutividad, condición/atención independientes, deduplicación, atraso y asociación histórica, configuración pendiente/aplicada, CSRF/sin sesión/Origin, geometría inválida/versión obsoleta, ausencia temporizada/recuperación, auditoría/aviso local/mantenimiento/reporte, reasignación y retiro/logout. Fixtures [seed_test_users.py](../qa/seed_test_users.py) permiten probar otro predio y roles con cuentas exclusivamente simuladas; se ejecutaron con los usernames correspondientes. La fixture opcional browser utiliza una contraseña de entorno QA temporal, nunca la contraseña privada del demo, y puede revocarse conservando auditoría.

## Alcance que requiere validación adicional

- RF09 necesita línea base individual y algoritmo/ventana validados para habilitación operacional. La regla por umbral predial implementada sirve como regla sintética; no acredita una interpretación clínica.
- Umbrales de batería, temperatura, actividad y proximidad son parámetros de desarrollo; el informe no fija valores operacionales universales. Su validación física y con productor está pendiente.
- El canal externo necesita proveedor contratado y pruebas reales de rechazo/reintento/expiración. Arrancar un worker no acredita entrega efectiva.
- El contrato JSON/adaptador no acredita codec binario final, FPort, OTAA, radio, firmware de collar ni aplicación de downlinks físicos.
- El smoke funcional no mide K03/K06 durante diez minutos de carga, K07 en siete días, K08 de autonomía, K09 en campo, K10/K12 con productor ni RTO/RPO mediante restauración. Estas metas conservan estado pendiente hasta su evidencia específica.
- La continuidad sin Internet debe ensayarse con WAN efectivamente cortada y LAN/radio/servidor operativos; el mapa debe mantener geometrías locales aunque no estén disponibles tiles externos.
- Retención inicial propuesta30d requiere acuerdo antes de eliminar datos; la implementación no afirma tener treinta días acumulados ni realiza borrado automático.

La implementación desarrollada proporciona la cadena software; la aprobación de demo, preserie y lote70 depende de las pruebas y evidencias de cada etapa del segundo informe.
