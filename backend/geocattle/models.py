import uuid
from datetime import date, datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, BigInteger, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

def utcnow(): return datetime.now(timezone.utc)
class Base(DeclarativeBase): pass
class Geometry(UserDefinedType):
    cache_ok = True
    def get_col_spec(self, **kw): return "geometry"
class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
class Farm(Base, IdMixin):
    __tablename__ = "farms"
    name: Mapped[str] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String, default="America/Santiago")
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("owner_accounts.id"))
    rup: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    commune: Mapped[str | None] = mapped_column(Text)
    boundary: Mapped[object | None] = mapped_column(Geometry)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
class User(Base, IdMixin):
    __tablename__ = "users"
    farm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("farms.id"))
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    csrf_token: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active_farm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("farms.id"))
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
class OwnerAccount(Base, IdMixin):
    __tablename__ = "owner_accounts"
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    max_farms: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
class FarmMembership(Base, IdMixin):
    __tablename__ = "farm_memberships"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role_code: Mapped[str] = mapped_column(Text)
    granted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
class MFAFactor(Base, IdMixin):
    __tablename__ = "mfa_factors"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(Text, default="totp")
    credential_id: Mapped[str | None] = mapped_column(Text)
    protected_data: Mapped[bytes] = mapped_column(LargeBinary)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
class AuthChallenge(Base, IdMixin):
    __tablename__ = "auth_challenges"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    purpose: Mapped[str] = mapped_column(Text)
    session_token_hash: Mapped[str | None] = mapped_column(ForeignKey("login_sessions.token_hash"))
    operation_digest: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
class Sector(Base, IdMixin):
    __tablename__ = "sectors"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    name: Mapped[str] = mapped_column(Text)
    land_use: Mapped[str] = mapped_column(Text, default="grazing")
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
class Animal(Base, IdMixin):
    __tablename__ = "animals"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    diio: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(Text)
    orientation: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sector_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sectors.id"))
    species: Mapped[str] = mapped_column(Text, default="bovine")
    breed: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    sex: Mapped[str] = mapped_column(Text, default="unknown")
    birth_date: Mapped[date | None] = mapped_column(Date)
    birth_date_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    production_type: Mapped[str] = mapped_column(Text, default="other")
    status: Mapped[str] = mapped_column(Text, default="active")
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
class Device(Base, IdMixin):
    __tablename__ = "devices"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    hardware_id: Mapped[str] = mapped_column(String, unique=True)
    dev_eui: Mapped[str | None] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(Text)
    transport: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    config_version: Mapped[int] = mapped_column(Integer, default=0)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_telemetry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    serial_number: Mapped[str | None] = mapped_column(Text)
    hardware_revision: Mapped[str | None] = mapped_column(Text)
    firmware_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="available")
class AnimalHolding(Base, IdMixin):
    __tablename__ = "animal_holdings"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    animal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("animals.id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
class Assignment(Base, IdMixin):
    __tablename__ = "assignments"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    animal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("animals.id"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    animal_holding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("animal_holdings.id"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
class Geofence(Base, IdMixin):
    __tablename__ = "geofences"
    geofence_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    sector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sectors.id"))
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    geometry: Mapped[object] = mapped_column(Geometry)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
class GeofenceSector(Base):
    __tablename__ = "geofence_sectors"
    geofence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("geofences.id"), primary_key=True)
    sector_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sectors.id"), primary_key=True)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))

class PastureAssignment(Base, IdMixin):
    __tablename__ = "pasture_assignments"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    animal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("animals.id"))
    geofence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("geofences.id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    animal_holding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("animal_holdings.id"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
class Telemetry(Base, IdMixin):
    __tablename__ = "telemetry"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"))
    animal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("animals.id"))
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assignments.id"))
    session_id: Mapped[str] = mapped_column(String)
    seq: Mapped[int] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    point: Mapped[object | None] = mapped_column(Geometry)
    gnss_valid: Mapped[bool] = mapped_column(Boolean)
    surface_temperature_c: Mapped[float | None] = mapped_column(Float)
    activity_index: Mapped[float | None] = mapped_column(Float)
    battery_mv: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String)
    quality: Mapped[dict] = mapped_column(JSONB, default=dict)
    config_version: Mapped[int | None] = mapped_column(Integer)
class AnimalState(Base):
    __tablename__ = "animal_states"
    animal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("animals.id"), primary_key=True)
    telemetry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("telemetry.id"))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    position_telemetry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("telemetry.id"))
    outside_count: Mapped[int] = mapped_column(Integer, default=0)
    geofence_status: Mapped[str] = mapped_column(String, default="unknown")
class Event(Base, IdMixin):
    __tablename__ = "events"
    last_position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("telemetry.id"))
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    animal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("animals.id"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"))
    telemetry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("telemetry.id"))
    geofence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("geofences.id"))
    type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    condition: Mapped[str] = mapped_column(String, default="active")
    attention: Mapped[str] = mapped_column(String, default="pending")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
class EventAction(Base, IdMixin):
    __tablename__ = "event_actions"
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str] = mapped_column(Text)
class DeviceConfig(Base, IdMixin):
    __tablename__ = "device_configs"
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"))
    version: Mapped[int] = mapped_column(Integer)
    interval_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="requested")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
class RuleSettings(Base):
    __tablename__ = "rule_settings"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    battery_low_mv: Mapped[int] = mapped_column(Integer, default=3300)
    temperature_high_c: Mapped[float | None] = mapped_column(Float, default=39.5)
    activity_low_threshold: Mapped[float | None] = mapped_column(Float, default=0.1)
    activity_window_minutes: Mapped[int] = mapped_column(Integer, default=30)
    proximity_meters: Mapped[float] = mapped_column(Float, default=10)
    temperature_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    activity_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    proximity_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
class Audit(Base, IdMixin):
    __tablename__ = "audit_log"
    farm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("farms.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    object_type: Mapped[str] = mapped_column(String)
    object_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("owner_accounts.id"))
    session_token_hash: Mapped[str | None] = mapped_column(ForeignKey("login_sessions.token_hash"))
    actor_kind: Mapped[str] = mapped_column(Text, default="service")
    ip_address: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(Text)
class Notification(Base, IdMixin):
    __tablename__ = "notifications"
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("events.id"))
    channel: Mapped[str] = mapped_column(String, default="webhook")
    status: Mapped[str] = mapped_column(String, default="pending")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    farm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("farms.id"))
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    recipient_address: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
class NotificationAttempt(Base, IdMixin):
    __tablename__ = "notification_attempts"
    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String)
    provider_id: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
class Maintenance(Base, IdMixin):
    __tablename__ = "maintenance"
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"))
    battery_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    responsible_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    result: Mapped[str] = mapped_column(Text)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
