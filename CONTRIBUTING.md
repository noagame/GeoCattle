# Colaborar en GeoCattle

El repositorio conserva su estructura. Las ramas separan el trabajo en curso; la aplicacion, su contrato de telemetria y sus pruebas siguen siendo un proyecto compartido.

- `main`: version estable. Recibe una integracion revisada mediante pull request.
- `develop`: integracion y revision antes de actualizar `main`.
- `dev/software`: interfaz, API y reglas de negocio; coordinacion principal de Fabian Del Villar (`@noagame`). Boris (`@BorBP`) tambien puede contribuir al software.
- `dev/hardware-captura`: recepcion de collares, gateways, protocolos y captura; coordinacion principal de Boris (`@BorBP`).

Ambos colaboradores conservan la posibilidad de modificar cualquier area. Los archivos de contrato, migraciones y arranque requieren coordinacion; una rama no bloquea esos archivos.

## Trabajo habitual

1. Antes de cambiar de rama, ejecutar `git status`. Guardar el trabajo propio en commits de su rama; no reemplazar carpetas completas para sincronizar.
2. Ejecutar `git fetch origin` y seleccionar la rama de trabajo con `git switch dev/software` o `git switch dev/hardware-captura`.
3. Actualizar la rama remota correspondiente y revisar los cambios de `develop`. La guia ampliada muestra los comandos.
4. Crear commits pequenos, con el problema y resultado descritos, y subirlos a la rama de trabajo.
5. Abrir un pull request hacia `develop`. Mantenerlo en borrador mientras existan verificaciones o integraciones pendientes.
6. Solicitar la revision del otro integrante y completar los checks de CI, incluida la integracion con PostGIS. Integrar por merge normal para conservar el historial. No forzar subidas sobre ramas compartidas.
7. Promover `develop` a `main` cuando la revision funcional correspondiente este completada.

No incluir archivos `.env` con valores reales, `.runtime/`, colas SQLite, datos de collares, credenciales, `node_modules/` ni otros archivos generados. `.env.example` puede actualizarse con valores de ejemplo sin secretos. Las pruebas de base de datos deben usar una instalacion aislada, no los datos operativos.

Ver [Desarrollo colaborativo](docs/DESARROLLO_COLABORATIVO.md) para el mapa de areas, los contratos compartidos, las pruebas y las protecciones recomendadas en GitHub.
