# GeoCattle — Especificación V3

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

- `MODELO_CONCEPTUAL_V3.png` y `.svg`: resumen visual renderizado y revisado.
- `MODELO_CONCEPTUAL_V3.mmd`: conceptos y cardinalidades de negocio.
- `MODELO_LOGICO_V3.mmd`: entidades, atributos y relaciones principales. Las FK compuestas completas están en el diccionario/SQL.
- `MODELO_V3.drawio`: páginas por dominio con entidades y referencias, editable en diagrams.net.
- `RESUMEN_VISUAL.html`: vista local con diagrama conceptual y navegación de entidades.
- `catalogo_modelo.json`: catálogo fuente.
- `generar_entregables.py` + `controles_fisicos.sql`: regeneración de SQL/diccionario/diagrama lógico.
- `generar_especificacion.py`: regeneración de casos, requisitos y documentos de análisis.
- `generar_visuales.py`: regeneración de diagramas editables y vista local.

## Cambios frente a V2

Administrador global separado del dueño; cuenta cliente multipredio; enrolamiento por invitación; MFA y step-up; aprobación granular para trabajador con confianza revocable; veterinario directo; gateways; medidas históricas; agenda sanitaria; KPIs/consumo. Se conservan operación IoT, alertas, notificaciones y FMA como extensión.

El modelo actual implementado y la propuesta V2 permanecen como referencia. V3 es la nueva propuesta de diseño; adoptarla requiere migraciones y cambios de aplicación.
