# GeoCattle V3 — Implementación y verificación local

Corte: **21 de octubre de 2026**. La aplicación incorpora los cuatro perfiles acordados, gestión multipredio, colaboración con aprobación, salud histórica y administración global. La decisión confirmada se mantiene: **el veterinario aplica cambios técnicos y sanitarios directamente**; el trabajador requiere aprobación del dueño salvo confianza vigente para una acción precisa.

## Acceso a la instancia

La aplicación está disponible en [http://localhost:8080](http://localhost:8080) en el equipo donde se ejecuta Docker. Es una instancia local de simulación; las posiciones y los bovinos de demostración no representan mediciones prediales reales.

- **Dueño existente:** conserva su identidad y contraseña. La instalación de demostración utiliza `demo@geocattle.local`; su credencial está en el archivo privado `.env`, variable `DEMO_PASSWORD`.
- **Administrador inicial de esta actualización:** sus datos de acceso están en `.runtime/acceso_administrador_v3.json`, con permisos privados y excluido de Git. Consultarlos localmente; no copiar el archivo al informe ni al repositorio.
- **Trabajador y veterinario:** ingresan con una identidad propia después de aceptar una invitación del dueño. No se comparten credenciales del titular.

El administrador introduce su contraseña, registra la clave de configuración en una aplicación autenticadora TOTP al primer ingreso y confirma el código de seis dígitos. En los ingresos posteriores se exige contraseña y código. El dueño puede activar TOTP desde **Mi perfil → Activar doble verificación**; lo necesita para administrar equipo y confianza.

La clave TOTP se entrega durante su configuración y se guarda cifrada en el servidor. Los códigos ya utilizados no se aceptan de nuevo: si se acaba de verificar una operación, esperar al siguiente código de la aplicación autenticadora. Los retos tienen vigencia limitada y límites de intentos por identidad.

Para revisar o reiniciar los servicios sin eliminar los datos:

```bash
cd geocattle-saas
bash scripts/compose.sh ps
bash scripts/compose.sh up -d
```

## Vistas y operaciones por perfil

| Perfil | Vista y funciones disponibles | Alcance aplicado por la API |
|---|---|---|
| Administrador | Panel con usuarios, animales, predios, sectores, collares y módulos; filtro por dueño, alertas diarias, peticiones y errores, métricas de consumo; administración de dueños y usuarios; auditoría. | Plataforma completa; puede seleccionar un predio autorizado para consultar su contexto. MFA obligatorio. |
| Dueño | Resumen y mapa; predios, sectores, geocercas, bovinos, collares y asignaciones; gateways; equipo e invitaciones; aprobación de propuestas; confianza por acción; ficha sanitaria y agenda. | Cuenta propia y sus predios. El alta respeta el cupo de predios activos de la cuenta. |
| Trabajador | Mapa, ubicación y estado, ficha del bovino, historial y perfil personal; propuestas de vacuna/antibiótico, estado, reporte y reemplazo de batería. | Predios con membresía vigente. Las propuestas pendientes se muestran separadas de los registros efectivos. |
| Veterinario | Mapa, consulta del rebaño, edición de ficha técnica, eventos sanitarios, tratamientos, correcciones y agenda; perfil personal. | Predios con membresía vigente. Sus cambios técnicos y sanitarios se aplican directamente y conservan autoría. |

Cambiar el predio del selector cambia el contexto de la sesión. La interfaz vuelve a cargar los datos del contexto seleccionado y el servidor comprueba su alcance en cada operación. La consulta global del administrador se selecciona sin un predio activo.

Los KPIs distinguen los **collares físicos** de los **módulos de software habilitados**. Se filtran por dueño, predio y período: los conteos representan el estado actual; alertas y consumo utilizan el intervalo seleccionado. Sin un período explícito se muestran alertas de treinta días y consumo de las últimas veinticuatro horas. La vista administrativa presenta bytes HTTP declarados, latencia p95, tamaño de la base, memoria residente de la API, espacio libre y carga observada del sistema. Son medidas de la instancia; no constituyen un historial completo de infraestructura ni contabilizan todo el tráfico de red.

La auditoría filtra en el servidor por actor, acción, entidad, predio y fechas, con búsqueda y paginación. El dueño conserva el alcance de su predio aun al introducir filtros. Cada respuesta incorpora `X-Request-ID`, asociado a su registro en `request_metrics`, para relacionar una petición con su evidencia técnica sin registrar cuerpos ni secretos.

## Seguridad de la cuenta y recuperación

Desde **Mi perfil → Seguridad y acceso** se puede cambiar contraseña, generar códigos de recuperación y solicitar el cierre. Estas operaciones revalidan la contraseña y, si existe MFA activo, un código TOTP nuevo.

- **Cambiar contraseña:** exige al menos doce caracteres, revoca todas las sesiones e invalida los enlaces de recuperación pendientes. El usuario vuelve a iniciar sesión; su factor MFA permanece activo.
- **Códigos de recuperación:** con MFA activo se generan ocho códigos que se muestran una sola vez y se guardan con hash. Cada código permite un ingreso junto con la contraseña y se consume una sola vez. Generar otro conjunto invalida los anteriores. La recuperación no desactiva MFA para los siguientes ingresos.
- **Recuperación asistida:** el administrador entra a **Usuarios de la plataforma → Restablecer contraseña**, verifica sus propias credenciales y obtiene un enlace privado de un solo uso, vigente durante quince minutos. Lo entrega al titular por un canal privado. El destinatario puede abrirlo sin sesión, definir la nueva contraseña y volver a ingresar; se revocan las sesiones previas y se conserva MFA. Un enlace nuevo invalida los anteriores.
- **Solicitud de cierre:** requiere motivo y reautenticación. Devuelve una referencia y queda auditada como pendiente de revisión administrativa; el perfil, el acceso y los registros se conservan hasta resolverla. No ejecuta un borrado autónomo.

La verificación y el cambio de correo siguen pendientes. Los enlaces de recuperación e invitación se entregan manualmente; no se ha configurado ni acreditado su envío automático.

## Equipo, enrolamiento y confianza

1. El dueño selecciona el predio, entra a **Equipo y permisos** y verifica contraseña y código TOTP. La lectura sensible se habilita durante diez minutos.
2. En **Invitar usuario** introduce correo y perfil —trabajador o veterinario—, revisa los datos y verifica esa escritura con contraseña y un código TOTP nuevo.
3. La aplicación genera un enlace privado de enrolamiento, vigente durante 48 horas y de un solo uso. El dueño lo comunica al destinatario por un canal privado. **No se ha acreditado entrega automática por correo.**
4. El destinatario abre el enlace, introduce su nombre y define una contraseña de al menos doce caracteres. Si ya existe una identidad del mismo correo, debe utilizar su contraseña vigente; no se reemplaza su contraseña al aceptar otra membresía.
5. El dueño puede modificar el perfil o cerrar el acceso al predio. La baja conserva la identidad y su autoría histórica, así como las membresías de otros predios.
6. La confianza se concede a una membresía de trabajador y a una acción concreta: registro sanitario permitido, estado, reporte o batería. Revocarla afecta las siguientes operaciones y conserva la historia de concesiones.

Las altas y cambios de colaboradores, concesiones y revocaciones de confianza incorporan un reto de un solo uso ligado a usuario, sesión, predio, método, ruta y contenido exacto. Caduca a los cinco minutos y se consume dentro de la misma transacción de la operación; no habilita una escritura distinta. Esta capa aprobó nueve pruebas de integración, incluidas alteración del contenido, reutilización, caducidad, cambio de sesión/contexto y reversión transaccional.

## Cambios del trabajador y registro veterinario

Una propuesta guarda autor, fecha, acción, contenido y versión base. Antes de aprobarla no modifica la ficha efectiva; el dueño recibe un aviso interno y puede revisarla en el panel de solicitudes. Aprobar registra decisión y aplicación en una transacción. Rechazar exige motivo y conserva la propuesta sin aplicarla. Si el bovino cambió desde la versión propuesta, se informa conflicto para evitar sobrescribir datos nuevos.

Una concesión de confianza vigente permite aplicar directamente solo la acción autorizada y registra qué concesión se utilizó. No concede administración de personas, geocercas o permisos. El trabajador no puede corregir un diagnóstico veterinario ajeno mediante una propuesta sanitaria.

El veterinario registra hechos clínicos y tratamientos sin aprobación posterior del dueño. La ficha guarda producto, dosis y unidad, vía, fecha, lote y resguardos informados. Las medidas de peso y altura permanecen fechadas. Corregir o anular crea un registro sucesor: los originales permanecen consultables. La agenda diferencia lo planificado de lo realmente administrado y permite relacionar ambos registros al completar una atención.

Los avisos internos de próximos controles se generan para planes efectivos. Un recordatorio no acredita que se haya administrado un tratamiento. La temperatura mostrada es superficial; los datos de sensores no se presentan como diagnóstico.

## Predios, mapa e infraestructura

El dueño administra sectores por nombre, uso, descripción y estado. Las geocercas se editan mediante puntos y requieren al menos cuatro vértices distintos, cierre y geometría simple válida; cada guardado crea una versión. La asignación de pastoreo y la asignación de collar conservan sus intervalos históricos.

El mapa muestra sectores, geocercas, bovinos y gateways, con calidad y antigüedad de la información. Un gateway se registra como infraestructura separada del collar. Tener ubicación y estado de un gateway no demuestra cobertura radioeléctrica.

La ingestión conserva hasta diez recepciones por lectura y transforma `rxInfo` de ChirpStack a gateway, RSSI, SNR y fecha informada. Solo persiste gateways registrados en el mismo predio. Un uplink duplicado puede añadir una segunda antena sin duplicar la lectura ni rejuvenecer la comunicación del collar. Los metadatos de radio inválidos se omiten de esa transformación y permanecen en `quality` del ingestor; no sustituyen sensores ni crean cobertura. El reloj del gateway avanza con una nueva recepción y la llegada al servidor/cola, de forma monotónica. La ruta de software está implementada y tiene seis pruebas; la recepción radio real sigue pendiente de ensayo con equipos.

## Base de datos y conservación

La actualización ejecutable es [003_application_v3.sql](../database/migrations/003_application_v3.sql). Es aditiva: conserva claves, credenciales y registros previos, agrega estructuras V3 y concilia las referencias heredadas. El migrador registra las versiones aplicadas y serializa sus ejecuciones; el procedimiento está en [MIGRACION_V3.md](MIGRACION_V3.md).

| Comprobación de la instancia local | Resultado registrado |
|---|---|
| Tablas de negocio y soporte | 48; `schema_migrations` es una tabla técnica adicional. |
| Animales conservados | 70. |
| Dispositivos conservados | 70. |
| Lecturas conservadas | 569. |
| Respaldo previo | `backups/geocattle-20261021T040427Z.dump`, fuera de Git. |
| Restauración del respaldo | Verificada en una base desechable, con migración V3 posterior; no sustituyó la instancia. |

El modelo **propuesto** de [especificacion-v3/](especificacion-v3/README.md) y el esquema **instalado** contienen 48 tablas, pero conservan diferencias de compatibilidad: la aplicación mantiene `farms`, `animals`, `devices`, `assignments`, `pasture_assignments`, los campos legados de auditoría y `auth_challenges`. La tabla `users.farm_id` se conserva; el alcance V3 depende de cuenta y membresías.

La documentación de nombres, columnas, tipos y restricciones reales está en [MODELO_BASE_DATOS.md](MODELO_BASE_DATOS.md), [diagrama instalado](MODELO_IMPLEMENTADO_V3.mmd) y [extracción JSON](MODELO_IMPLEMENTADO_V3.json). El SQL físico propuesto independiente no debe ejecutarse sobre la base operativa. La telemetría continúa en PostgreSQL/PostGIS; esta actualización no la convierte en una hypertable de TimescaleDB.

La ficha histórica, decisiones y aplicaciones disponen de restricciones y controles de inmutabilidad. El rol de ejecución carece de actualización y borrado sobre las tablas históricas protegidas. El catálogo FMA y sus tablas se conservan como extensión P2, **deshabilitada por defecto**: no existe emisión oficial ni integración SIPEC verificada.

## Evidencia de verificación

| Área | Evidencia y alcance |
|---|---|
| Suite de reglas/API/regresión | **61 pruebas aprobadas en la ejecución integral final, en 47,23 segundos.** Incluye 31 previas, 9 de operación MFA, 12 de cuenta/recuperación, 6 multiantena y 3 de filtros/trazabilidad. Se ejecutó sobre PostgreSQL de prueba separado. |
| Integridad SQL | 23 comprobaciones positivas/negativas; restricciones históricas, alcance y decisiones. |
| Migración | Creación desde base vacía, actualización V1, repetición sin duplicados, conciliación y restauración del respaldo. |
| Permisos de base | Verificación del rol de ejecución en 12 tablas históricas representativas. |
| Cliente web | Compilación y comprobación TypeScript realizadas; construcción final de las imágenes Docker aprobada. |
| Navegador | Ingreso y navegación de los cuatro perfiles; administrador con segundo factor; cuentas y registros sintéticos en base desechable. |

Las pruebas incluyen sesión y CSRF, límites MFA por identidad, acceso cruzado denegado, pendiente sin efecto, aprobación y confianza granular, veterinario directo, correcciones inmutables, versiones obsoletas y conservación de asignaciones al versionar una geocerca. Las nuevas suites verifican autorización por operación, cambio y recuperación de credenciales sin perder MFA, solicitud de cierre sin eliminación, recepción multiantena idempotente, filtros de auditoría/KPIs y correlación de petición. Los veintiún casos de cuenta y operación MFA, los seis de recepción y los tres de filtros se aprobaron en ejecuciones específicas.

Las capturas son evidencia de **QA con datos sintéticos**, no de animales o clientes reales: [Administrador](../qa/v3/panel_admin_qa.jpg), [Dueño](../qa/v3/panel_dueno_qa.jpg), [Trabajador](../qa/v3/panel_trabajador_qa.jpg) y [Veterinario](../qa/v3/panel_veterinario_qa.jpg).

## Planificación y actualización del informe

La [carta Gantt editable](planificacion/Carta_Gantt_GeoCattle_V3_2026-10-21.xlsx), su [vista SVG](planificacion/Carta_Gantt_GeoCattle_V3_2026-10-21.svg) y el [detalle de tareas](planificacion/CARTA_GANTT_V3.md) distinguen integración local, revisión y pruebas externas. Incluyen 25 tareas y 410 horas estimadas para dos responsables, con línea base del 21/10/2026 al 12/01/2027. Las fechas requieren confirmación académica y disponibilidad predial; las horas no son tiempo de ejecución de subagentes.

[actualizacion_informe.md](../../actualizacion_informe.md) contiene 19 bloques con ubicación verificable en el documento fuente y el texto exacto propuesto. Los informes originales se conservan. La [evidencia de implementación](planificacion/EVIDENCIA_IMPLEMENTACION.md) alimenta ese archivo y debe mantenerse coherente con las pruebas finales.

## Funciones y aceptación aún pendientes

La existencia del código y las tablas no acredita los 44 RF y 22 RNF completos. Continúan por cerrar la verificación y el cambio de correo, y la resolución administrativa de las solicitudes de cierre. El cierre disponible es una solicitud auditada, conserva el perfil y espera revisión. El perfil permite modificar nombre y teléfono; la recuperación asistida y los códigos de un solo uso están implementados. El envío externo de invitaciones, recuperación y avisos requiere proveedor configurado y pruebas de entrega.

Quedan pendientes la observabilidad histórica dedicada, carga con 70 nodos y cinco clientes, medición continua de disponibilidad, RPO/RTO, corte WAN y recuperación de cola, cobertura LoRaWAN, autonomía, montaje y recepción real multiantena. Dosis y resguardos deben verificarse con el responsable sanitario. La aceptación del productor y la preserie predial permanecen como hitos externos de la Gantt.
