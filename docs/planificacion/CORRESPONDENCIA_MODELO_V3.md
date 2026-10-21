# Correspondencia del modelo lógico V3 con las migraciones operativas

Inventario obtenido de las sentencias CREATE TABLE de las migraciones 001, 002 y 003. Las tablas preexistentes pueden recibir columnas, restricciones y triggers adicionales en 003. Esta tabla compara nombres y procedencia; no equipara todas las columnas de la propuesta con las del esquema operativo.

| Tabla del modelo objetivo | Tabla física operativa | Migración de creación |
|---|---|---|
| `users` | `users` | `001_schema.sql` |
| `platform_admins` | `platform_admins` | `003_application_v3.sql` |
| `mfa_factors` | `mfa_factors` | `003_application_v3.sql` |
| `mfa_recovery_codes` | `mfa_recovery_codes` | `003_application_v3.sql` |
| `login_sessions` | `login_sessions` | `001_schema.sql` |
| `security_challenges` | `auth_challenges` | `003_application_v3.sql` |
| `account_tokens` | `account_tokens` | `003_application_v3.sql` |
| `roles` | `roles` | `003_application_v3.sql` |
| `permissions` | `permissions` | `003_application_v3.sql` |
| `role_permissions` | `role_permissions` | `003_application_v3.sql` |
| `owner_accounts` | `owner_accounts` | `003_application_v3.sql` |
| `farms` | `farms` | `001_schema.sql` |
| `farm_memberships` | `farm_memberships` | `003_application_v3.sql` |
| `invitations` | `invitations` | `003_application_v3.sql` |
| `trust_grants` | `trust_grants` | `003_application_v3.sql` |
| `sectors` | `sectors` | `001_schema.sql` |
| `geofences` | `geofences` | `001_schema.sql` |
| `animals` | `animals` | `001_schema.sql` |
| `animal_holdings` | `animal_holdings` | `003_application_v3.sql` |
| `gateways` | `gateways` | `003_application_v3.sql` |
| `devices` | `devices` | `001_schema.sql` |
| `assignments` | `assignments` | `001_schema.sql` |
| `pasture_assignments` | `pasture_assignments` | `001_schema.sql` |
| `telemetry` | `telemetry` | `001_schema.sql` |
| `telemetry_receptions` | `telemetry_receptions` | `003_application_v3.sql` |
| `animal_states` | `animal_states` | `001_schema.sql` |
| `rule_settings` | `rule_settings` | `001_schema.sql` |
| `events` | `events` | `001_schema.sql` |
| `event_actions` | `event_actions` | `001_schema.sql` |
| `device_configs` | `device_configs` | `001_schema.sql` |
| `change_requests` | `change_requests` | `003_application_v3.sql` |
| `change_decisions` | `change_decisions` | `003_application_v3.sql` |
| `change_applications` | `change_applications` | `003_application_v3.sql` |
| `animal_measurements` | `animal_measurements` | `003_application_v3.sql` |
| `animal_reports` | `animal_reports` | `003_application_v3.sql` |
| `health_events` | `health_events` | `003_application_v3.sql` |
| `health_treatments` | `health_treatments` | `003_application_v3.sql` |
| `health_schedules` | `health_schedules` | `003_application_v3.sql` |
| `maintenance` | `maintenance` | `002_maintenance.sql` |
| `notifications` | `notifications` | `001_schema.sql` |
| `notification_attempts` | `notification_attempts` | `001_schema.sql` |
| `audit_log` | `audit_log` | `001_schema.sql` |
| `request_metrics` | `request_metrics` | `003_application_v3.sql` |
| `features` | `features` | `003_application_v3.sql` |
| `farm_features` | `farm_features` | `003_application_v3.sql` |
| `sag_movements` | `sag_movements` | `003_application_v3.sql` |
| `movement_animals` | `movement_animals` | `003_application_v3.sql` |
| `movement_status_events` | `movement_status_events` | `003_application_v3.sql` |

`security_challenges` de la propuesta se implementa como `auth_challenges`. El historial de cambios operativo se consulta en `003_application_v3.sql`.
