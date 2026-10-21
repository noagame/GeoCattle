# GeoCattle V3 — Diagramas de casos de uso

Ocho vistas UML de los 29 casos definidos en la especificación V3. Las imágenes son resúmenes visuales de los casos documentados; no agregan permisos nuevos.

| Vista | Imagen | Vector | Fuente |
|---|---|---|---|
| Vista general de actores y funciones | [PNG](01_general.png) | [SVG](01_general.svg) | [PlantUML](01_general.puml) |
| Administrador · plataforma | [PNG](02_administrador.png) | [SVG](02_administrador.svg) | [PlantUML](02_administrador.puml) |
| Dueño · predios, colaboradores y aprobación | [PNG](03_dueno_gestion.png) | [SVG](03_dueno_gestion.svg) | [PlantUML](03_dueno_gestion.puml) |
| Dueño · monitoreo y salud | [PNG](04_dueno_monitoreo_salud.png) | [SVG](04_dueno_monitoreo_salud.svg) | [PlantUML](04_dueno_monitoreo_salud.puml) |
| Trabajador · consultas y propuestas | [PNG](05_trabajador.png) | [SVG](05_trabajador.svg) | [PlantUML](05_trabajador.puml) |
| Veterinario · ficha técnica y sanitaria | [PNG](06_veterinario.png) | [SVG](06_veterinario.svg) | [PlantUML](06_veterinario.puml) |
| Propuestas del trabajador y decisiones del dueño | [PNG](07_aprobacion.png) | [SVG](07_aprobacion.svg) | [PlantUML](07_aprobacion.puml) |
| Servicios técnicos · ingestión, alertas y avisos | [PNG](08_actores_tecnicos.png) | [SVG](08_actores_tecnicos.svg) | [PlantUML](08_actores_tecnicos.puml) |

Archivo editable multipágina: [CASOS_DE_USO_V3.drawio](CASOS_DE_USO_V3.drawio).

## Convenciones UML

- Actor fuera del límite del sistema; elipse dentro del sistema = caso de uso.
- Línea continua sin flecha = asociación; no representa orden de pasos.
- `include`: flecha discontinua desde el caso que incluye hacia el comportamiento obligatorio.
- `extend`: flecha desde la extensión hacia el caso base; condición indicada entre corchetes.
- No se dibuja el inicio de sesión como `include` de cada operación: una sesión válida es precondición.
- AUX-01 a AUX-03 descomponen comportamiento ya definido; no son CU-30 ni requisitos adicionales.
- El diagrama de aprobación no es un diagrama de secuencia: el orden transaccional sigue en el documento de casos.
- Persistir y notificar significa guardar propuesta y cola de aviso; el envío externo puede ocurrir después.

## Decisiones representadas

Administrador global separado de dueño; MFA para administrador y step-up para acciones sensibles del dueño. Trabajador sujeto a revisión salvo confianza por acción. Veterinario con cambios directos. FMA continúa como extensión P2.

## Cobertura completa

| Caso | Nombre | Vistas |
|---|---|---|
| CU-01 | Iniciar sesión y seleccionar contexto | 02_administrador, 04_dueno_monitoreo_salud, 05_trabajador, 06_veterinario |
| CU-02 | Cerrar sesión o recuperar acceso | 02_administrador, 04_dueno_monitoreo_salud, 05_trabajador, 06_veterinario |
| CU-03 | Administrar dueños/clientes | 01_general, 02_administrador |
| CU-04 | Administrar colaboradores desde plataforma | 02_administrador |
| CU-05 | Consultar KPIs | 01_general, 02_administrador |
| CU-06 | Auditar actividad y consumo | 01_general, 02_administrador |
| CU-07 | Administrar perfil propio | 02_administrador, 04_dueno_monitoreo_salud, 05_trabajador, 06_veterinario |
| CU-08 | Administrar predios | 01_general, 03_dueno_gestion |
| CU-09 | Configurar sectores | 03_dueno_gestion |
| CU-10 | Crear o editar geocerca | 03_dueno_gestion |
| CU-11 | Registrar y mantener bovino | 03_dueno_gestion |
| CU-12 | Asignar collar o pastoreo | 03_dueno_gestion |
| CU-13 | Invitar y administrar colaboradores | 01_general, 03_dueno_gestion |
| CU-14 | Enrolarse por invitación | 05_trabajador, 06_veterinario |
| CU-15 | Consultar mapa del predio | 01_general, 04_dueno_monitoreo_salud, 05_trabajador, 06_veterinario |
| CU-16 | Consultar ficha e historial | 04_dueno_monitoreo_salud, 05_trabajador, 06_veterinario |
| CU-17 | Registrar vacuna o antibiótico por trabajador | 01_general, 05_trabajador, 07_aprobacion |
| CU-18 | Solicitar estado o reporte del bovino | 05_trabajador, 07_aprobacion |
| CU-19 | Reportar cambio de batería | 04_dueno_monitoreo_salud, 05_trabajador, 07_aprobacion |
| CU-20 | Aprobar o rechazar solicitud | 01_general, 03_dueno_gestion, 07_aprobacion |
| CU-21 | Conceder o revocar confianza | 03_dueno_gestion, 07_aprobacion |
| CU-22 | Modificar ficha técnica | 04_dueno_monitoreo_salud, 06_veterinario |
| CU-23 | Gestionar ficha sanitaria | 01_general, 04_dueno_monitoreo_salud, 06_veterinario |
| CU-24 | Planificar próxima atención | 04_dueno_monitoreo_salud, 06_veterinario |
| CU-25 | Administrar gateways e inventario | 03_dueno_gestion |
| CU-26 | Recibir telemetría | 01_general, 08_actores_tecnicos |
| CU-27 | Generar y atender alerta | 04_dueno_monitoreo_salud, 05_trabajador, 06_veterinario, 08_actores_tecnicos |
| CU-28 | Configurar collar y entregar avisos | 01_general, 04_dueno_monitoreo_salud, 08_actores_tecnicos |
| CU-29 | Gestionar movimiento FMA (extensión) | 03_dueno_gestion |
