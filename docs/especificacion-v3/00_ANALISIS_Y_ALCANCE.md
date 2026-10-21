# GeoCattle V3 — Análisis de usuarios y decisiones de alcance

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
