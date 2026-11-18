# Especificación V3

## Propósito y alcance

Los documentos `00_` a `05_` reúnen alcance, casos de uso, requerimientos y modelos conceptual, lógico y físico. El catálogo JSON, las fuentes editables, los generadores y las exportaciones forman el conjunto de entrega descrito en el [README](README.md).

## Guía de trabajo

- Al cambiar el diseño, revisa las referencias entre requisitos, casos de uso y modelos. Actualiza las fuentes editables y las exportaciones que representa el cambio.
- Usa [las migraciones](../../database/AGENTS.md) para contrastar el esquema implementado. Describe en la especificación las diferencias relevantes con el diseño de entrega.

## Verificación

Consulta [VALIDACION.md](VALIDACION.md) y `VALIDACION_SQL.sql` para las comprobaciones del modelo. Usa una base aislada si ejecutas SQL.

## Child DOX Index

- [diagramas-casos-uso/AGENTS.md](diagramas-casos-uso/AGENTS.md) — catálogo, fuentes y exportaciones de diagramas de actores y casos de uso.
