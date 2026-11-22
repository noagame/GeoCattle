# Aplicación GeoCattle

## Propósito y alcance

`main.py` monta los routers. `v3_api.py` contiene operaciones V3, `hardware_api.py` atiende captura y `v3_receptions.py` alimenta consultas de recepción. `domain.py`, `worker.py` e `ingestor.py` contienen reglas y procesamiento. La configuración central está en `settings.py`.

## Contratos locales

- Reutiliza los controles de `security.py`, `v3_auth.py`, `v3_security.py` y `v3_operation_auth.py` según el router. Si cambia una operación con alcance de predio, revisa las consultas y permisos de lectura y escritura.
- Para cambios de API revisa `schemas.py`, los tipos y clientes de [frontend](../../frontend/src/AGENTS.md) y el [contrato de API](../../docs/CONTRATO_API.md). Para cambios de almacenamiento revisa `models.py` y [database](../../database/AGENTS.md).
- Conserva el origen y las fechas de observación y recepción al procesar telemetría. Las alertas y su atención conservan estados distintos. [Arquitectura](../../docs/ARQUITECTURA.md)
- `device_candidates.py` registra detecciones físicas por predio. La captura académica HTTP conserva un recibo por hardware, sesión y secuencia hasta después de resolver el candidato. `v3_device_candidates.py` aplica la autorización del predio y usa `device_inventory.py` para compartir validación y auditoría con el alta manual.
- `ADMIN_LOGIN_MFA` y producción obligan a verificar TOTP al administrador. En desarrollo, `LOCAL_ADMIN_PASSWORD_ONLY` limita el acceso por contraseña al prototipo nativo en loopback. El inicio de sesión y la validación de sesiones aplican la misma política.
- Las solicitudes de soporte son privadas de cuenta. El autor consulta su caso y el administrador lo gestiona desde el contexto global. Los motivos y respuestas se guardan en `support_requests`. Excluye los registros privados históricos de las consultas de auditoría del dueño en ambas versiones de la API.
- Los detalles, listados y conteos de solicitudes del predio respetan el contexto y la autoría. La consulta de contadores en segundo plano conserva el vencimiento por inactividad de la sesión.
- Vacuna y antibiótico requieren un producto aplicado y una vía de su catálogo. Entre esos dos catálogos, la vía oral corresponde a antibiótico. Procedimiento admite productos opcionales. Los demás eventos y las anulaciones excluyen productos. Usa `HEALTH_PRODUCT_POLICIES` para exponer y validar las reglas al registrar, corregir y aprobar. Una corrección puede conservar una vía histórica del mismo producto y tipo de evento, salvo la vía oral para vacuna. La agenda de vacunación y antibiótico se completa con un evento efectivo del mismo tipo y de la misma permanencia. Conserva la autoría y los registros sanitarios históricos.
- `v3_animal_reports.py` genera la vista previa y los CSV de registros de bovinos en el predio activo. Restringe el acceso a dueño, administrador, trabajador y veterinario, utiliza días de la zona horaria del predio y mantiene el mismo conjunto de filtros en ambos formatos.
- `v3_farm_indicators.py` define los totales, la serie de alertas y los rankings del predio activo. El router de reportes los restringe a dueño y administrador. Para los rankings usa la asignación vigente al observar la muestra, separa simulación y datos físicos y exige cobertura antes de asignar un puesto.
- `invitation_mail.py` integra SMTP con STARTTLS o TLS implícito en la cola de invitación y su confirmación. El worker reintenta fallos temporales y retira el token cifrado al cerrar el envío. Registra el identificador, la clase de error y el código numérico SMTP.
- `v3_auth.py` verifica el desafío contra el factor asociado. `v3_account.py` reautentica al titular para reemplazar o quitar TOTP. El factor vigente se retira tras verificar el nuevo o confirmar el retiro. Serializa los cambios de credenciales y autorizaciones MFA con el bloqueo de la identidad.
- `account_maintenance.py` expone comandos locales para probar SMTP y restablecer TOTP. El restablecimiento invalida todas las sesiones e impone una nueva inscripción antes de abrir la próxima sesión.

## Verificación

Usa las suites correspondientes en [tests](../tests/AGENTS.md) y las pruebas de contrato de [QA](../../qa/AGENTS.md) si cambia captura o entrega.
