# GeoCattle V3 — Modelo físico y contrato de implementación

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
