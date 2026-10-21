# Validación de la propuesta V3

Fecha de revisión: 20 de octubre de 2026. Estado: diseño y esquema físico comprobados en entorno temporal; aplicación V3 no implementada.

## Entorno ejecutado

- Imagen local `postgis/postgis:16-3.4`.
- PostgreSQL 16.4 y PostGIS 3.4.3.
- Contenedor temporal sin red, sin puertos publicados y sin volúmenes del proyecto.
- Base vacía `v3_final`; instalación con `psql -v ON_ERROR_STOP=1`.
- Resultado: COMMIT correcto, 48 tablas, 155 claves foráneas y 7 restricciones de exclusión.

## Pruebas ejecutadas

`VALIDACION_SQL.sql` pasó 32 comprobaciones sintéticas. Incluyeron reasignación histórica, rechazo de solapamientos de collar y permanencia, rechazo de asociaciones entre predios, cupo de predios, DIIO único, mínimo de vértices, geometría versionada, atribución de lectura atrasada, rechazo de animal/fecha incorrectos, deduplicación, inmutabilidad y recepción multiantena.

El flujo de cambios comprobó: pendiente sin efecto clínico; prohibición de aprobación por trabajador, veterinario revisor y dueño ajeno; límites de la ficha técnica del trabajador; rechazo sin aplicación; veterinario directo; trabajador directo solo con confianza; aplicación única; decisión aceptada sin aplicación bloqueada; corrección sanitaria que conserva original; sucesor único; auditoría inmutable y KPI de inventario coherente.

Los datos de prueba se revirtieron mediante ROLLBACK. La consulta posterior devolvió cero usuarios de prueba. El contenedor se retira al terminar la revisión.

## Consistencia documental

- Las 48 tablas coinciden entre catálogo JSON, DDL y entidades del diagrama lógico Mermaid.
- Las referencias FK del DDL tienen destino definido.
- Los documentos contienen 29 casos, 44 RF y 22 RNF; las referencias de RF a casos existen.
- Los archivos Draw.io y SVG tienen XML válido.
- El resumen SVG se renderizó localmente a PNG y se inspeccionó visualmente: tarjetas, textos y cardinalidades legibles.
- Los diagramas Mermaid se verificaron estructuralmente; no se ejecutó un compilador Mermaid ni se inspeccionó visualmente cada página de Draw.io.

## Límites de esta evidencia

Las pruebas SQL fueron secuenciales. No constituyen un ensayo de carga, concurrencia real, radio, cobertura, autonomía, precisión GNSS, disponibilidad ni recuperación.

No se probaron MFA/TOTP/WebAuthn, correo, recuperación real de cuenta, sesiones HTTP, RLS, autorización de todos los endpoints, cola externa ni interfaz de usuario: requieren implementación. El SQL no activa RLS y el despliegue debe restringir acceso mediante API y roles de base separados. Las validaciones de versión/payload y el vínculo de aplicación polimórfica con el registro efectivamente modificado son responsabilidades explícitas del backend.

Las tablas FMA se crearon y sus FK se comprobaron durante instalación, pero el flujo documental oficial y sus transiciones no se ensayaron. No existe integración SIPEC validada.

La base actual de la aplicación y sus migraciones no se modificaron. Este SQL es una propuesta para una base nueva de revisión, no una migración de producción.
