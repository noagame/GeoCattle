# Colaborar en GeoCattle

`main` contiene la aplicación, captura, firmware y documentación del proyecto. Antes de iniciar, revisa `git status` y actualiza tu copia de `main` con `git pull --ff-only`. Guarda tus cambios en commits acotados y verifica la compatibilidad de los contratos que modifiques.

La validación de GitHub comprueba el frontend, los adaptadores y contratos de captura, las reglas de dominio y la integración con PostGIS. Consulta el [desarrollo local](docs/DESARROLLO_LOCAL.md) para ejecutar y probar el proyecto.

Conserva fuera de Git la configuración privada, `.runtime/`, los respaldos, la telemetría real y los archivos generados. Las pruebas de base de datos usan un entorno aislado.
