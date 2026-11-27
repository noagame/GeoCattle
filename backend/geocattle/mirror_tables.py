"""Clasificación de tablas del modo espejo (docs/planificacion/PLAN_MODO_ESPEJO.md).

MIRROR: el PC del campo es el único que escribe; se publican y el servidor las recibe por
replicación lógica. En el servidor la API solo las lee.
FIELD_ONLY: viven solo en el PC (sesiones, códigos y correos del campo).
SERVER_ONLY: viven solo en el servidor espejo (sesiones web, bandeja, auditoría web).
Toda tabla de las migraciones pertenece a exactamente una clase (qa/test_mirror_tables.py).
"""

PUBLICATION = 'geocattle_espejo'
SUBSCRIPTION = 'geocattle_espejo'
REPLICA_ROLE = 'geocattle_replica'

MIRROR = frozenset({
    # Cuentas, predios y permisos.
    'farms', 'users', 'owner_accounts', 'platform_admins', 'roles', 'permissions',
    'role_permissions', 'farm_memberships', 'trust_grants', 'mfa_factors', 'features',
    'farm_features',
    # Territorio y rebaño.
    'sectors', 'geofences', 'geofence_sectors', 'pasture_assignments', 'animals',
    'animal_holdings', 'animal_states', 'animal_measurements', 'animal_reports',
    'sag_movements', 'movement_animals', 'movement_status_events',
    # Equipos y captura.
    'devices', 'device_configs', 'assignments', 'gateways', 'gateway_candidates',
    'gateway_bus_receipts', 'device_candidates', 'device_candidate_captures', 'receiver_status',
    'maintenance',
    # Telemetría, alertas y avisos.
    'telemetry', 'telemetry_receptions', 'events', 'event_actions', 'rule_settings',
    'notifications', 'notification_attempts',
    # Salud, solicitudes y borradores.
    'health_events', 'health_treatments', 'health_schedules', 'change_requests',
    'change_decisions', 'change_applications', 'change_drafts',
    # Soporte, auditoría y estado del espejo.
    'support_requests', 'audit_log', 'mirror_heartbeat', 'mirror_inbox_results',
})

FIELD_ONLY = frozenset({
    'login_sessions', 'auth_challenges', 'account_tokens', 'mfa_recovery_codes', 'invitations',
    'invitation_mail', 'request_metrics', 'schema_migrations',
})

SERVER_ONLY = frozenset({
    'mirror_outbox', 'mirror_totp_use', 'mirror_audit_log', 'mirror_notification_reads',
})

# El servidor también tiene sus propias filas en estas tablas (no replicadas).
SERVER_LOCAL = SERVER_ONLY | {'login_sessions', 'auth_challenges', 'request_metrics',
                              'schema_migrations'}


def mirror_tables():
    """Tablas publicadas, en orden estable para SQL y pruebas."""
    return sorted(MIRROR)
