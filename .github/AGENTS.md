# GitHub

## Propósito y alcance

`workflows/validacion.yml` ejecuta frontend, contratos de captura y reglas de dominio en trabajos separados. `CODEOWNERS` y `PULL_REQUEST_TEMPLATE.md` organizan la revisión compartida.

## Contratos locales

- Mantén las comprobaciones de captura y dominio independientes de una base operativa. Las extensiones de captura se prueban cuando sus módulos existen en la rama.
- Coordina cualquier renombre de un trabajo con las comprobaciones requeridas de GitHub. Conserva los permisos de lectura y las referencias fijadas por SHA de las acciones al actualizar el flujo.

## Verificación

Usa los comandos de [validacion.yml](workflows/validacion.yml) en el directorio y entorno que declara cada trabajo. Consulta la [guía de colaboración](../docs/DESARROLLO_COLABORATIVO.md) para revisar cambios en los checks requeridos.
