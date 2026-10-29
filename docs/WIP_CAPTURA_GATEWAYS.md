# Captura de gateways: trabajo en curso

Este documento acompaña la rama `dev/hardware-captura`. Conserva el trabajo local de BorBP que estaba pendiente al separar las áreas de desarrollo el 29 de octubre de 2026. No declara terminada ni desplegada esa integración.

Se preservan los adaptadores de bus/ACK y perfiles USB, la selección previa Directo/Gateways, los accesos de captura, su indicador en HardwarePage y las pruebas preparadas. Estos cambios pueden incluir frontend o backend cuando la recepción de collares lo requiere; las ramas no limitan qué archivos puede modificar cada colaborador.

## Verificación pendiente antes de integrar

- Actualizar e incorporar las pruebas de lotes y de alternancia que quedaron preparadas fuera del repositorio durante la pausa. Las expectativas antiguas de `qa/test_lora_bus.py` todavía no reflejan los perfiles separados.
- Completar la validación del selector y del cambio de receptor, con cierre del puerto anterior antes de abrir el siguiente.
- Compilar el frontend actualizado y ejecutar los controles comunes contra la versión de software integrada.
- Probar ambos métodos con las placas reales, confirmar el ACK después del archivo local duradero y verificar la entrega a PostgreSQL.

Las 75 pruebas confirmadas durante el trabajo del 28 de octubre cubrían regresión y perfiles; no prueban la integración completa ni la radio física. Los lotes y los receptores nuevos permanecen como desarrollo en curso hasta superar los controles de su PR.

## Datos locales

Los archivos `.runtime`, bases, colas, capturas, credenciales y respaldos se conservan fuera de Git. La separación de ramas no aplica migraciones a la base, no reprograma placas y no inicia servicios.
