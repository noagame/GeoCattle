# Aplicación GeoCattle

## Propósito y alcance

`main.py` monta los routers. `v3_api.py` contiene operaciones V3, `hardware_api.py` atiende captura y `v3_receptions.py` alimenta consultas de recepción. `domain.py`, `worker.py` e `ingestor.py` contienen reglas y procesamiento. La configuración central está en `settings.py`.

## Contratos locales

- Reutiliza los controles de `security.py`, `v3_auth.py`, `v3_security.py` y `v3_operation_auth.py` según el router. Si cambia una operación con alcance de predio, revisa las consultas y permisos de lectura y escritura.
- Para cambios de API revisa `schemas.py`, los tipos y clientes de [frontend](../../frontend/src/AGENTS.md) y el [contrato de API](../../docs/CONTRATO_API.md). Para cambios de almacenamiento revisa `models.py` y [database](../../database/AGENTS.md).
- Conserva el origen y las fechas de observación y recepción al procesar telemetría. Las alertas y su atención conservan estados distintos. [Arquitectura](../../docs/ARQUITECTURA.md)
- `ADMIN_LOGIN_MFA` y producción obligan a verificar TOTP al administrador. En desarrollo, `LOCAL_ADMIN_PASSWORD_ONLY` limita el acceso por contraseña al prototipo nativo en loopback. El inicio de sesión y la validación de sesiones aplican la misma política.
- Las solicitudes de soporte son privadas de cuenta. El autor consulta su caso y el administrador lo gestiona desde el contexto global. Los motivos y respuestas se guardan en `support_requests`. Excluye los registros privados históricos de las consultas de auditoría del dueño en ambas versiones de la API.
- Los detalles, listados y conteos de solicitudes del predio respetan el contexto y la autoría. La consulta de contadores en segundo plano conserva el vencimiento por inactividad de la sesión.
- Vacuna y antibiótico requieren un producto aplicado y una vía de su catálogo. Entre esos dos catálogos, la vía oral corresponde a antibiótico. Procedimiento admite productos opcionales. Los demás eventos y las anulaciones excluyen productos. Usa `HEALTH_PRODUCT_POLICIES` para exponer y validar las reglas al registrar, corregir y aprobar. Una corrección puede conservar una vía histórica del mismo producto y tipo de evento, salvo la vía oral para vacuna. La agenda de vacunación y antibiótico se completa con un evento efectivo del mismo tipo y de la misma permanencia. Conserva la autoría y los registros sanitarios históricos.
- `v3_animal_reports.py` genera la vista previa y los CSV de registros de bovinos en el predio activo. Restringe el acceso a dueño, administrador, trabajador y veterinario, utiliza días de la zona horaria del predio y mantiene el mismo conjunto de filtros en ambos formatos.
- `v3_farm_indicators.py` define los totales, la serie de alertas y los rankings del predio activo. El router de reportes los restringe a dueño y administrador. Para los rankings usa la asignación vigente al observar la muestra, separa simulación y datos físicos y exige cobertura antes de asignar un puesto.

## Verificación

Usa las suites correspondientes en [tests](../tests/AGENTS.md) y las pruebas de contrato de [QA](../../qa/AGENTS.md) si cambia captura o entrega.
