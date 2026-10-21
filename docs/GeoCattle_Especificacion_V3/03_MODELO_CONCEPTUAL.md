# GeoCattle V3 — Modelo conceptual entidad-relación

Este nivel describe conceptos y cardinalidades de negocio, sin UUID, tipos PostgreSQL, PK ni índices. El diagrama lógico separado muestra su transformación a tablas.

```mermaid
erDiagram
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
```

## Cardinalidades y participación

| Relación | Cardinalidad | Interpretación |
|---|---|---|
| Usuario – cuenta de dueño | 1 : 0..1 | Cada cuenta tiene un dueño principal; un usuario puede no ser dueño. |
| Cuenta – predio | 1 : 0..N | Cuenta recién creada puede no tener predios; cada predio tiene una cuenta. |
| Usuario – predio | N : M mediante membresía | Trabajadores/veterinarios pueden colaborar en varios predios; dueño accede mediante su cuenta. |
| Predio – sector – geocerca versión | 1:N y 1:N | Sector estable; geometría cambia mediante versiones temporales. |
| Animal – predio | N:M histórica mediante permanencia | A lo sumo una permanencia activa por animal. |
| Animal – collar | N:M histórica mediante asignación | En un instante, a lo sumo un collar por animal y un animal por collar. |
| Animal – geocerca | N:M histórica mediante pastoreo | Una geocerca vigente por animal; varios animales simultáneos por geocerca. |
| Collar – lectura | 1:0..N | Cada lectura proviene de un collar, aunque no tenga animal atribuido. |
| Lectura – gateway | N:M mediante recepción | Un uplink puede recibirse por varias antenas. |
| Solicitud – decisión – aplicación | 1:0..1 y 1:0..1 | Pendiente no tiene decisión; rechazada no tiene aplicación; aceptada/directa exige aplicación. |
| Permanencia – evento sanitario – tratamiento | 1:N y 1:N | Historia sanitaria contextualizada y varios productos posibles. |
| Agenda – evento sanitario | N:0..1 por entrada completada | Planificar no demuestra administrar; completar exige evento real del mismo animal. |

El diagrama omite conceptos de soporte (retos, factores, proyecciones, métricas y configuración) para mantener el nivel conceptual. La extensión FMA conserva relación documento N:M animal mediante detalle, definida en el modelo lógico. Ninguna cardinalidad por sí sola demuestra autorización o ausencia de solapamientos.
