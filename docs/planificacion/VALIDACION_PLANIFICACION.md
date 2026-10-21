# Verificación de planificación e informe

Fecha de corte: 21 de octubre de 2026.

| Comprobación | Resultado |
|---|---|
| Fuente del informe | Versión de viabilidad y flujo de caja del 04/10/2026; 499 párrafos y 49 tablas inspeccionados. |
| Plan anterior | Localizado en sección VII, párrafo 340 y tabla 38; DOCX original preservado. |
| Guía de actualización | 19 bloques, con anclas textuales y localizadores de sección/párrafo/tabla. |
| Alcance de diseño | 29 CU, 44 RF, 22 RNF y 48 tablas objetivo. |
| Correspondencia SQL | 18 tablas de 001, una de 002 y 29 de 003; única diferencia nominal: security_challenges → auth_challenges. |
| Planificación | 25 tareas con dependencias existentes y orden temporal válido. |
| Carga | 410 horas estimadas: Fabián 200 y Boris 210; máximo seis horas por persona y día. |
| Fórmulas | Fechas WORKDAY contrastadas por tarea con calendario independiente; esfuerzo contrastado por tarea. |
| Recalculo | Cambiar duración de P01 de uno a siete días actualiza fin, esfuerzo y barra de la semana siguiente; valor original restaurado. |
| Errores de fórmula | Búsqueda final sin coincidencias de errores de referencia, división, valor, nombre, número o nulos. |
| Revisión visual | Hoja superior, cronograma semanal y cierre de hoja revisados en tres renders. |
| Límite de verificación | No se ha probado la apertura en Excel o LibreOffice del equipo del usuario; la verificación se realizó mediante Artifact Tool y exportación XLSX. |

La fecha académica oficial y la disponibilidad del equipo/productor no constan en las fuentes. Las fechas de campo y los días no laborables son supuestos explícitos y editables. Las pruebas externas no se presentan como realizadas. La evidencia de ejecución del producto se completa al integrar la implementación.

Las barras de la hoja se recalculan a partir de inicio y fin. Las dependencias son identificadores de planificación; no constituyen un motor de reprogramación automática. Al editar fechas deben revisarse dependencias y carga. El archivo original de Gantt no era una planilla independiente: estaba incorporado como tabla en el informe; la versión V3 es un reemplazo identificado en Excel, SVG y Markdown.
