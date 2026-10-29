export type AnimalStatus = 'normal' | 'warning' | 'critical' | 'unknown';
export type User = { id: string; username: string; role: 'admin' | 'owner' | 'worker' | 'veterinarian' | 'operator' | 'viewer'; farm_id: string | null; full_name?: string; email?: string; phone?: string | null; mfa_enabled?: boolean; farms?: { id: string; name: string; role: 'admin' | 'owner' | 'worker' | 'veterinarian' }[] };
export type Session = { user: User; csrf_token: string };
export type Telemetry = {
  id: string; device_id: string; animal_id: string | null; session_id: string; seq: number;
  observed_at: string; received_at: string; longitude: number | null; latitude: number | null;
  gnss_valid: boolean; surface_temperature_c: number | null; activity_index: number | null;
  battery_mv: number | null; source: 'sim' | 'academic' | 'lorawan'; quality: Record<string, unknown>;
  config_version?: number;
};
export type Animal = {
  id: string; diio: string; name: string; orientation: 'meat' | 'milk'; enabled: boolean;
  sector_id: string | null; sector_name: string | null; device_id: string | null; device_name: string | null;
  status: AnimalStatus; position_status: 'fresh' | 'stale' | 'unknown';
  communication_status: 'recent' | 'absent' | 'unknown';
  geofence_status: 'inside' | 'outside' | 'pending' | 'unknown'; last_telemetry: Telemetry | null; last_position: Telemetry | null;
  position_age_seconds: number | null; active_events: number;
  pasture_assignment?: { id: string; geofence_id: string; geofence_name: string; geofence_version: number; sector_id: string; sector_name: string; valid_from: string; valid_to: string | null } | null;
  collar_assignment?: { id: string; device_id: string; valid_from: string; valid_to: string | null } | null;
};
export type Device = {
  id: string; hardware_id: string; dev_eui: string | null; name: string;
  transport: 'academic' | 'lorawan'; enabled: boolean; interval_seconds: number; config_version: number;
  pending_config: { version: number; interval_seconds: number; status: string } | null;
  animal_id?: string | null; last_received_at?: string | null;
};
export type Sector = { id: string; name: string; land_use?: 'grazing' | 'available' | 'cropped' | 'restricted' | 'other'; description?: string | null; active?: boolean };
export type Polygon = { type: 'Polygon'; coordinates: number[][][] };
export type Geofence = { id: string; geofence_key: string; sector_ids: string[]; sector_id: string; name: string; version: number; active: boolean; geometry: Polygon; created_at: string };
export type EventAction = { id?: string; action: string; note: string; at?: string; actor_id?: string; created_at?: string; performed_at?: string; username?: string; actor?: string; user_id?: string };
export type CattleEvent = {
  id: string; animal_id: string; animal_name: string; diio: string; device_id: string;
  type: string; severity: string; condition: 'active' | 'resolved';
  attention: 'pending' | 'acknowledged' | 'in_review' | 'concluded';
  opened_at: string; resolved_at: string | null; detail: string | Record<string, unknown>; actions: EventAction[];
  last_known_position?: { telemetry: Telemetry; age_at_detection_seconds: number; hardware_id: string } | null;
  telemetry?: Telemetry | null; evidence?: Telemetry | null; device_name?: string; geofence_name?: string; geofence_version?: number | null;
};
export type Dashboard = {
  farm: { id: string; name: string; environment: string };
  summary: { normal: number; warning: number; critical: number; unknown: number; total: number; active_events: number };
  animals: Animal[]; sectors: Sector[];
};
export type Overview = Dashboard & { events: CattleEvent[] };
export type Settings = {
  version: number; battery_low_mv: number; temperature_high_c: number | null; activity_low_threshold: number | null;
  activity_window_minutes: number; proximity_meters: number;
  temperature_enabled: boolean; activity_enabled: boolean; proximity_enabled: boolean;
  capabilities?: { can_edit: boolean; environment: 'simulation' | 'development' | 'production'; preventive_rules_validated: boolean; preventive_rules_allowed: boolean };
  [key: string]: unknown;
};
export type Audit = { id: string; action: string; at: string; actor_id: string | null; object_type: string; object_id: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null };
export type Notification = { id: string; status: string; created_at: string; channel: string; event_id: string; attempts: { attempt: number; at: string; status: string; provider_id?: string | null; error?: string | null }[] };
export type Maintenance = { id: string; device_id: string; device_name: string; battery_id: string | null; kind: 'inspection' | 'recharge' | 'replacement' | 'retirement'; at: string; responsible_id: string; responsible_name: string; result: string };
export type List<T> = { items: T[]; total: number };

export type AssociationHistory = { id: string; kind: 'collar' | 'pasture'; valid_from: string; valid_to: string | null; active: boolean; assigned_by: string | null; assigned_by_name: string | null; device_id: string | null; device_name: string | null; hardware_id: string | null; geofence_id: string | null; geofence_name: string | null; geofence_version: number | null; sector_id: string | null; sector_name: string | null };
